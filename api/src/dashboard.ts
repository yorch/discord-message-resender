// The dashboard is a single self-contained page served by the API. It is
// embedded as a string rather than a static file so it compiles into dist and
// ships with the existing `COPY dist` step, adding no dependency and no
// asset-copy stage to the Docker build.
//
// The page itself is unauthenticated markup. The data calls it makes to /alerts
// and /stats carry the bearer token, which the viewer pastes once and which is
// kept in localStorage on their own machine only.

const DASHBOARD_TEMPLATE = /* html */ `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Alert Archive</title>
<style nonce="__NONCE__">
  :root {
    --bg: #0f1115; --panel: #171a21; --border: #262b36; --text: #e6e9ef;
    --muted: #8b93a3; --accent: #4f8cff; --danger: #ff6b6b; --chip: #222735;
  }
  @media (prefers-color-scheme: light) {
    :root {
      --bg: #f6f7f9; --panel: #fff; --border: #e2e5ea; --text: #1a1d24;
      --muted: #6b7280; --accent: #2563eb; --danger: #dc2626; --chip: #eef1f6;
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text);
    font: 14px/1.5 system-ui, -apple-system, Segoe UI, Roboto, sans-serif; }
  header { padding: 14px 20px; border-bottom: 1px solid var(--border);
    display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
    position: sticky; top: 0; background: var(--panel); z-index: 5; }
  h1 { font-size: 16px; margin: 0 12px 0 0; }
  input, select, button { font: inherit; color: var(--text);
    background: var(--bg); border: 1px solid var(--border);
    border-radius: 8px; padding: 7px 10px; }
  button { cursor: pointer; background: var(--accent); color: #fff; border: 0; }
  button.secondary { background: var(--chip); color: var(--text); }
  .stats { display: flex; gap: 18px; flex-wrap: wrap; padding: 12px 20px;
    color: var(--muted); border-bottom: 1px solid var(--border); }
  .stats b { color: var(--text); }
  main { padding: 16px 20px; max-width: 1000px; margin: 0 auto; }
  .msg { background: var(--panel); border: 1px solid var(--border);
    border-radius: 10px; padding: 12px 14px; margin-bottom: 10px; }
  .msg.deleted { opacity: .6; border-color: var(--danger); }
  .msg .meta { display: flex; gap: 8px; align-items: center;
    color: var(--muted); font-size: 12px; margin-bottom: 6px; flex-wrap: wrap; }
  .msg .author { color: var(--text); font-weight: 600; }
  .chip { background: var(--chip); border-radius: 20px; padding: 1px 9px; font-size: 12px; }
  .chip.del { background: var(--danger); color: #fff; }
  .content { white-space: pre-wrap; word-break: break-word; }
  .embed { border-left: 3px solid var(--accent); padding: 4px 0 4px 10px;
    margin-top: 8px; }
  .embed .etitle { font-weight: 600; }
  .embed .efield { margin-top: 4px; }
  .embed .efield .en { color: var(--muted); font-size: 12px; }
  .delivery { font-size: 12px; color: var(--muted); margin-top: 6px; }
  .empty, .error { color: var(--muted); padding: 40px; text-align: center; }
  .error { color: var(--danger); }
  #more { display: block; margin: 8px auto 40px; }
  .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
</style>
</head>
<body>
<header>
  <h1>Alert Archive</h1>
  <input id="token" type="password" placeholder="API token" style="min-width:220px" />
  <input id="q" placeholder="search text…" />
  <input id="channelId" placeholder="channel ID" size="18" />
  <select id="deleted">
    <option value="any">all</option>
    <option value="exclude">live only</option>
    <option value="only">deleted only</option>
  </select>
  <label class="row" style="color:var(--muted)">
    <input type="checkbox" id="auto" /> auto-refresh
  </label>
  <button id="refresh">Refresh</button>
</header>
<div class="stats" id="stats"></div>
<main>
  <div id="list"></div>
  <button id="more" class="secondary" hidden>Load more</button>
</main>
<script nonce="__NONCE__">
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const KEY = "alert-archive-token";
  let cursor = null, loading = false, timer = null;

  try { $("token").value = localStorage.getItem(KEY) || ""; } catch {}

  function headers() {
    return { Authorization: "Bearer " + $("token").value.trim() };
  }
  function saveToken() {
    try { localStorage.setItem(KEY, $("token").value.trim()); } catch {}
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function fmt(ts) { return ts ? new Date(ts).toLocaleString() : ""; }

  function embedHtml(embeds) {
    if (!Array.isArray(embeds)) return "";
    return embeds.map((e) => {
      let h = '<div class="embed">';
      if (e.title) h += '<div class="etitle">' + esc(e.title) + "</div>";
      if (e.description) h += "<div>" + esc(e.description) + "</div>";
      if (Array.isArray(e.fields))
        for (const f of e.fields)
          h += '<div class="efield"><span class="en">' + esc(f.name) +
               "</span><br>" + esc(f.value) + "</div>";
      return h + "</div>";
    }).join("");
  }

  function msgHtml(m) {
    const del = m.deletedAt;
    const deliv = (m.deliveries || [])
      .map((d) => esc(d.route) + ": " + esc(d.status)).join(" · ");
    return '<div class="msg' + (del ? " deleted" : "") + '">' +
      '<div class="meta">' +
        '<span class="author">' + esc(m.authorName) + "</span>" +
        (m.channelName ? '<span class="chip">#' + esc(m.channelName) + "</span>" : "") +
        "<span>" + fmt(m.sentAt) + "</span>" +
        (m.editedAt ? "<span>(edited)</span>" : "") +
        (del ? '<span class="chip del">deleted ' + fmt(del) + "</span>" : "") +
      "</div>" +
      (m.content ? '<div class="content">' + esc(m.content) + "</div>" : "") +
      embedHtml(m.embeds) +
      (deliv ? '<div class="delivery">' + deliv + "</div>" : "") +
    "</div>";
  }

  async function loadStats() {
    try {
      const r = await fetch("stats", { headers: headers() });
      if (!r.ok) return;
      const s = await r.json();
      $("stats").innerHTML =
        "<span><b>" + s.totalMessages + "</b> messages</span>" +
        "<span><b>" + (s.deletedMessages || 0) + "</b> deleted</span>" +
        "<span>latest: <b>" + (fmt(s.latestMessageAt) || "—") + "</b></span>" +
        "<span>" + (s.channels || []).length + " channel(s)</span>";
    } catch {}
  }

  async function load(reset) {
    if (loading) return;
    loading = true;
    if (reset) { cursor = null; $("list").innerHTML = ""; }
    const p = new URLSearchParams({ limit: "50", deleted: $("deleted").value });
    if ($("q").value.trim()) p.set("q", $("q").value.trim());
    if ($("channelId").value.trim()) p.set("channelId", $("channelId").value.trim());
    if (cursor) p.set("cursor", cursor);
    try {
      const r = await fetch("alerts?" + p.toString(), { headers: headers() });
      if (!r.ok) {
        // On a fresh query, replace the list with the error. On "load more",
        // keep what is already shown and append a non-destructive notice.
        const msg = r.status === 401 ? "Invalid or missing API token." : "Error " + r.status;
        if (reset) $("list").innerHTML = '<div class="error">' + msg + "</div>";
        else $("list").insertAdjacentHTML("beforeend", '<div class="error">' + msg + "</div>");
        return;
      }
      const body = await r.json();
      if (reset && body.data.length === 0)
        $("list").innerHTML = '<div class="empty">No messages match.</div>';
      $("list").insertAdjacentHTML("beforeend", body.data.map(msgHtml).join(""));
      cursor = body.page.nextCursor;
      $("more").hidden = !body.page.hasMore;
    } catch (e) {
      const box = '<div class="error">' + esc(e.message) + "</div>";
      if (reset) $("list").innerHTML = box;
      else $("list").insertAdjacentHTML("beforeend", box);
    } finally { loading = false; }
  }

  function refresh() { saveToken(); loadStats(); load(true); }

  $("refresh").addEventListener("click", refresh);
  $("q").addEventListener("keydown", (e) => { if (e.key === "Enter") refresh(); });
  $("channelId").addEventListener("keydown", (e) => { if (e.key === "Enter") refresh(); });
  $("deleted").addEventListener("change", refresh);
  $("more").addEventListener("click", () => load(false));
  $("auto").addEventListener("change", (e) => {
    clearInterval(timer);
    if (e.target.checked) timer = setInterval(refresh, 15000);
  });

  if ($("token").value) refresh();
})();
</script>
</body>
</html>`;

/// Render the dashboard with a per-request nonce stamped onto its inline
/// <style> and <script>. The matching Content-Security-Policy header (set by the
/// route) then allows exactly those two inline blocks and nothing else, so a
/// future escaping slip cannot run injected script or exfiltrate the token.
export function renderDashboard(nonce: string): string {
  return DASHBOARD_TEMPLATE.replaceAll("__NONCE__", nonce);
}
