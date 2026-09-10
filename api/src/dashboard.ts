// The dashboard is a single self-contained page served by the API. It is
// embedded as a string rather than a static file so it compiles into dist and
// ships with the existing `COPY dist` step, adding no dependency and no
// asset-copy stage to the Docker build.
//
// The page itself is unauthenticated markup. The data calls it makes to /alerts
// and /stats carry the bearer token, which the viewer pastes once and which is
// kept in localStorage on their own machine only.
//
// System fonts and no external resources, so the strict per-request CSP in
// index.ts stays intact. Every field rendered from a captured message is
// attacker-controlled Discord text and goes through esc(); image URLs must be
// https and are backstopped by the CSP's img-src.

const TEMPLATE = /* html */ `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Alert Archive</title>
<style nonce="__NONCE__">
  :root {
    --ink:#10141c; --ink-2:#0c0f16; --surface:#171d28; --surface-2:#1d2432;
    --line:#232b3a; --line-2:#2e394c;
    --text:#e8ecf3; --muted:#8a94a6; --faint:#5c6678;
    --source:#f0b03e; --relay:#3fd6a6; --danger:#ff6b6b;
    --mono:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
    --sans:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--ink); color:var(--text); font-family:var(--sans);
    font-size:14px; line-height:1.55; -webkit-font-smoothing:antialiased; }
  a { color:var(--relay); text-decoration:none; } a:hover { text-decoration:underline; }

  header { position:sticky; top:0; z-index:5; background:rgba(16,20,28,.92);
    backdrop-filter:blur(10px); border-bottom:1px solid var(--line); }
  .bar { display:flex; gap:8px; align-items:center; flex-wrap:wrap;
    padding:11px 20px; max-width:1040px; margin:0 auto; }
  .logo { font-family:var(--mono); font-weight:700; font-size:14px; margin-right:4px; white-space:nowrap; }
  .logo .a { color:var(--source); } .logo .b { color:var(--relay); }
  input, select, button { font:inherit; color:var(--text); background:var(--ink-2);
    border:1px solid var(--line-2); border-radius:8px; padding:7px 10px; }
  input:focus, select:focus { outline:none; border-color:var(--relay); }
  input::placeholder { color:var(--faint); }
  #token { min-width:130px; } #q { min-width:150px; flex:1; }
  select { max-width:210px; }
  label.chk { display:flex; align-items:center; gap:6px; color:var(--muted); font-size:13px; white-space:nowrap; }
  button.go { background:var(--relay); color:#06231a; border-color:var(--relay); font-weight:600; cursor:pointer; }
  button.go:hover { background:#5ee2b8; }
  .row2 { display:flex; gap:8px; align-items:center; flex-wrap:wrap;
    max-width:1040px; margin:0 auto; padding:0 20px 11px; }

  .stats { max-width:1040px; margin:0 auto; padding:10px 20px; display:flex; gap:20px;
    flex-wrap:wrap; color:var(--muted); font-size:13px; border-bottom:1px solid var(--line); }
  .stats b { color:var(--text); font-family:var(--mono); font-weight:500; }
  .stats .sep { color:var(--relay); }

  main { max-width:1040px; margin:0 auto; padding:16px 20px 60px; }
  .newbar { text-align:center; margin-bottom:12px; }
  .newbar button { background:var(--surface-2); color:var(--relay); border:1px solid var(--relay);
    border-radius:20px; padding:5px 14px; font-size:12.5px; cursor:pointer; }

  .msg { background:var(--surface); border:1px solid var(--line); border-radius:12px;
    padding:14px 16px; margin-bottom:12px; display:flex; gap:12px; }
  .msg.deleted { opacity:.72; border-color:#3a2020; }
  .msg.fresh { animation:flash 1.4s ease; }
  @keyframes flash { from { border-color:var(--relay); } to { border-color:var(--line); } }
  .av { width:40px; height:40px; border-radius:11px; flex:none; display:flex; align-items:center;
    justify-content:center; font-family:var(--mono); font-weight:700; font-size:16px;
    background:var(--surface-2); color:var(--source); }
  .msg.deleted .av { color:var(--danger); }
  .col { min-width:0; flex:1; }
  .meta { display:flex; align-items:center; gap:9px; flex-wrap:wrap; margin-bottom:3px; }
  .who { font-weight:600; }
  .badge { font-size:11px; font-family:var(--mono); padding:1px 8px; border-radius:20px;
    border:1px solid var(--line-2); color:var(--muted); }
  .ts { font-family:var(--mono); font-size:11.5px; color:var(--faint); }
  .badge.del { color:var(--danger); border-color:#4a2626; background:rgba(255,107,107,.08); }
  .content { white-space:pre-wrap; word-break:break-word; }
  .jump { font-size:11.5px; margin-left:auto; }

  .embed { margin-top:9px; border-left:3px solid var(--source); background:var(--ink-2);
    border-radius:0 8px 8px 0; padding:9px 12px; max-width:540px; }
  .embed .etitle { font-weight:600; margin-bottom:2px; }
  .embed .edesc { font-size:13.5px; }
  .efields { display:flex; flex-wrap:wrap; gap:10px 20px; margin-top:7px; }
  .efield .en { color:var(--muted); font-size:11.5px; font-family:var(--mono); }
  .efield .ev { font-size:13px; }
  .efoot { color:var(--faint); font-size:11.5px; margin-top:7px; }

  .imgs { display:flex; flex-wrap:wrap; gap:8px; margin-top:9px; }
  .imgs a { line-height:0; }
  .imgs img { max-width:240px; max-height:200px; border-radius:8px; border:1px solid var(--line-2);
    display:block; object-fit:cover; background:var(--ink-2); }
  .embed .imgs { margin-top:8px; }
  .files { display:flex; flex-wrap:wrap; gap:8px; margin-top:9px; }
  .file { font-family:var(--mono); font-size:12px; color:var(--muted); border:1px solid var(--line-2);
    border-radius:8px; padding:5px 10px; }
  .file:hover { border-color:var(--relay); text-decoration:none; }

  .delivery { display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; align-items:center; }
  .dchip { font-family:var(--mono); font-size:11px; padding:2px 9px; border-radius:20px;
    border:1px solid var(--line); color:var(--muted); }
  .dchip.DELIVERED { color:var(--relay); border-color:var(--relay); background:rgba(63,214,166,.08); }
  .dchip.PENDING { color:var(--source); border-color:var(--source); background:rgba(240,176,62,.08); }
  .dchip.FAILED { color:var(--danger); border-color:#4a2626; background:rgba(255,107,107,.08); }
  .dchip.SKIPPED { color:var(--faint); }
  .derr { color:var(--danger); font-family:var(--mono); font-size:11.5px; margin-top:6px;
    white-space:pre-wrap; word-break:break-word; }

  .state { text-align:center; color:var(--muted); padding:56px 20px; }
  .state.err { color:var(--danger); }
  #more { display:block; margin:6px auto 40px; background:var(--surface); color:var(--text);
    border:1px solid var(--line-2); border-radius:8px; padding:9px 18px; cursor:pointer; }
  #more:hover { border-color:var(--relay); }
  .append-err { color:var(--danger); text-align:center; padding:12px; font-size:13px; }
  #sentinel { height:1px; }
</style>
</head>
<body>
<header>
  <div class="bar">
    <span class="logo"><span class="a">alert</span> <span class="b">archive</span></span>
    <input id="token" type="password" placeholder="API token" />
    <input id="q" placeholder="Search text and embeds" />
    <button class="go" id="refresh">Refresh</button>
  </div>
  <div class="row2">
    <select id="channel"><option value="">All channels</option></select>
    <select id="author"><option value="">All authors</option></select>
    <select id="since">
      <option value="">Any time</option>
      <option value="1">Last 24h</option>
      <option value="7">Last 7 days</option>
      <option value="30">Last 30 days</option>
    </select>
    <select id="deleted">
      <option value="any">Live &amp; deleted</option>
      <option value="exclude">Live only</option>
      <option value="only">Deleted only</option>
    </select>
    <label class="chk"><input type="checkbox" id="failed" /> Failed forwards only</label>
    <label class="chk"><input type="checkbox" id="infinite" /> Infinite scroll</label>
    <label class="chk"><input type="checkbox" id="auto" /> Live</label>
  </div>
  <div class="stats" id="stats"></div>
</header>
<main>
  <div class="newbar" id="newbar" hidden></div>
  <div id="list"><div class="state">Enter your API token and press Refresh.</div></div>
  <button id="more" hidden>Load older</button>
  <div id="sentinel"></div>
</main>
<script nonce="__NONCE__">
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const KEY = "alert-archive-token";
  let cursor = null, loading = false, timer = null;
  const shown = new Set();

  try { $("token").value = localStorage.getItem(KEY) || ""; } catch {}
  const headers = () => ({ Authorization: "Bearer " + $("token").value.trim() });
  const saveToken = () => { try { localStorage.setItem(KEY, $("token").value.trim()); } catch {} };

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  const fmt = (ts) => (ts ? new Date(ts).toLocaleString() : "");
  const httpsUrl = (u) => (typeof u === "string" && u.startsWith("https://") ? u : "");
  const IMG_EXT = [".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif"];
  const isImage = (a) => {
    if (typeof a.content_type === "string" && a.content_type.startsWith("image/")) return true;
    const path = (a.url || "").toLowerCase().split("?")[0];
    return IMG_EXT.some((ext) => path.endsWith(ext));
  };
  const pickImg = (o) => (o && (o.proxy_url || o.url)) || null;

  function imgTag(url) {
    const u = httpsUrl(url);
    if (!u) return "";
    const e = esc(u);
    return '<a href="' + e + '" target="_blank" rel="noopener noreferrer">' +
      '<img loading="lazy" src="' + e + '" alt="" /></a>';
  }

  function embedHtml(embeds) {
    if (!Array.isArray(embeds)) return "";
    return embeds.map((e) => {
      const color = Number.isInteger(e.color)
        ? "#" + (e.color & 0xffffff).toString(16).padStart(6, "0") : null;
      let h = '<div class="embed"' + (color ? ' style="border-left-color:' + esc(color) + '"' : "") + ">";
      if (e.author && e.author.name) h += '<div class="efoot">' + esc(e.author.name) + "</div>";
      if (e.title) h += '<div class="etitle">' + esc(e.title) + "</div>";
      if (e.description) h += '<div class="edesc">' + esc(e.description) + "</div>";
      if (Array.isArray(e.fields) && e.fields.length) {
        h += '<div class="efields">' + e.fields.map((f) =>
          '<div class="efield"><div class="en">' + esc(f.name) + '</div><div class="ev">' +
          esc(f.value) + "</div></div>").join("") + "</div>";
      }
      const imgs = [pickImg(e.image), pickImg(e.thumbnail)].map(imgTag).filter(Boolean).join("");
      if (imgs) h += '<div class="imgs">' + imgs + "</div>";
      if (e.footer && e.footer.text) h += '<div class="efoot">' + esc(e.footer.text) + "</div>";
      return h + "</div>";
    }).join("");
  }

  function attachmentsHtml(atts) {
    if (!Array.isArray(atts) || !atts.length) return "";
    const images = atts.filter(isImage).map((a) => imgTag(pickImg(a))).filter(Boolean).join("");
    const files = atts.filter((a) => !isImage(a) && httpsUrl(a.url)).map((a) =>
      '<a class="file" href="' + esc(a.url) + '" target="_blank" rel="noopener noreferrer">' +
      esc(a.filename || "attachment") + "</a>").join("");
    return (images ? '<div class="imgs">' + images + "</div>" : "") +
           (files ? '<div class="files">' + files + "</div>" : "");
  }

  const initial = (name) => { const n = (name || "?").trim(); return esc(n ? n[0].toUpperCase() : "?"); };

  function deliveryHtml(deliveries) {
    if (!Array.isArray(deliveries) || !deliveries.length) return "";
    const chips = deliveries.map((d) =>
      '<span class="dchip ' + esc(d.status) + '">' + esc(d.route) + " · " + esc(d.status) + "</span>"
    ).join("");
    const errs = deliveries.filter((d) => d.status === "FAILED" && d.lastError).map((d) =>
      '<div class="derr">' + esc(d.route) + ": " + esc(d.lastError) + "</div>").join("");
    return '<div class="delivery">' + chips + "</div>" + errs;
  }

  function msgHtml(m) {
    const del = m.deletedAt;
    return '<div class="msg' + (del ? " deleted" : "") + '" data-id="' + esc(m.id) + '">' +
      '<div class="av">' + initial(m.authorName) + "</div>" +
      '<div class="col">' +
        '<div class="meta">' +
          '<span class="who">' + esc(m.authorName) + "</span>" +
          (m.channelName ? '<span class="badge">#' + esc(m.channelName) + "</span>" : "") +
          '<span class="ts">' + fmt(m.sentAt) + "</span>" +
          (m.editedAt ? '<span class="ts">(edited)</span>' : "") +
          (del ? '<span class="badge del">deleted ' + fmt(del) + "</span>" : "") +
        "</div>" +
        (m.content ? '<div class="content">' + esc(m.content) + "</div>" : "") +
        embedHtml(m.embeds) +
        attachmentsHtml(m.attachments) +
        deliveryHtml(m.deliveries) +
      "</div></div>";
  }

  function fillSelect(sel, keep, items) {
    const cur = sel.value;
    sel.innerHTML = keep + items;
    sel.value = cur; // preserve selection across refreshes
  }

  async function loadStats() {
    try {
      const r = await fetch("stats", { headers: headers() });
      if (!r.ok) { $("stats").innerHTML = ""; return; }
      const s = await r.json();
      $("stats").innerHTML =
        "<span><b>" + s.totalMessages + "</b> captured</span>" +
        '<span class="sep">·</span><span><b>' + (s.deletedMessages || 0) + "</b> deleted</span>" +
        '<span class="sep">·</span><span>' + (s.channels || []).length + " channels</span>" +
        '<span class="sep">·</span><span>latest <b>' + (fmt(s.latestMessageAt) || "—") + "</b></span>";
      fillSelect($("channel"), '<option value="">All channels</option>',
        (s.channels || []).map((c) =>
          '<option value="' + esc(c.channelId) + '">#' + esc(c.channelName || c.channelId) +
          (c.guildName ? " (" + esc(c.guildName) + ")" : "") + "</option>").join(""));
      fillSelect($("author"), '<option value="">All authors</option>',
        (s.authors || []).map((a) =>
          '<option value="' + esc(a.authorId) + '">' + esc(a.authorName) +
          " (" + a.messages + ")</option>").join(""));
    } catch { $("stats").innerHTML = ""; }
  }

  function queryParams() {
    const p = new URLSearchParams({ limit: "50", deleted: $("deleted").value });
    if ($("q").value.trim()) p.set("q", $("q").value.trim());
    if ($("channel").value) p.set("channelId", $("channel").value);
    if ($("author").value) p.set("authorId", $("author").value);
    if ($("failed").checked) p.set("failed", "true");
    const days = $("since").value;
    if (days) p.set("since", new Date(Date.now() - days * 86400000).toISOString());
    return p;
  }

  async function load(reset) {
    if (loading) return;
    loading = true;
    if (reset) { cursor = null; shown.clear(); }
    const p = queryParams();
    if (cursor) p.set("cursor", cursor);
    try {
      const r = await fetch("alerts?" + p.toString(), { headers: headers() });
      if (!r.ok) {
        const msg = r.status === 401 ? "Invalid or missing API token." : "Request failed (" + r.status + ").";
        if (reset) $("list").innerHTML = '<div class="state err">' + msg + "</div>";
        else $("list").insertAdjacentHTML("beforeend", '<div class="append-err">' + msg + "</div>");
        return;
      }
      const body = await r.json();
      // Append only messages not already shown, so a boundary row can never be
      // rendered twice no matter what the server returns.
      const incoming = reset ? body.data : body.data.filter((m) => !shown.has(m.id));
      for (const m of incoming) shown.add(m.id);
      if (reset) {
        $("list").innerHTML = incoming.length
          ? incoming.map(msgHtml).join("")
          : '<div class="state">No messages match these filters.</div>';
      } else if (incoming.length) {
        $("list").insertAdjacentHTML("beforeend", incoming.map(msgHtml).join(""));
      }
      cursor = body.page.nextCursor;
      // In infinite mode the sentinel drives loading, so keep the button hidden.
      $("more").hidden = !body.page.hasMore || $("infinite").checked;
    } catch (e) {
      const box = '<div class="' + (reset ? "state err" : "append-err") + '">' + esc(e.message) + "</div>";
      if (reset) $("list").innerHTML = box; else $("list").insertAdjacentHTML("beforeend", box);
    } finally { loading = false; }
  }

  // Live tail: fetch the newest page and prepend only messages not already shown,
  // preserving scroll instead of reloading the whole list.
  async function tail() {
    if (loading || !$("token").value.trim()) return;
    try {
      const r = await fetch("alerts?" + queryParams().toString(), { headers: headers() });
      if (!r.ok) return;
      const body = await r.json();
      const fresh = body.data.filter((m) => !shown.has(m.id));
      if (!fresh.length) return;
      for (const m of fresh) shown.add(m.id);
      // response is newest-first; prepend as a block so order is preserved
      $("list").insertAdjacentHTML("afterbegin", fresh.map(msgHtml).join(""));
      for (const m of fresh) {
        const el = $("list").querySelector('[data-id="' + CSS.escape(m.id) + '"]');
        if (el) el.classList.add("fresh");
      }
      loadStats();
    } catch {}
  }

  function refresh() {
    if (!$("token").value.trim()) {
      $("list").innerHTML = '<div class="state">Enter your API token and press Refresh.</div>';
      return;
    }
    saveToken(); loadStats(); load(true);
  }

  $("refresh").addEventListener("click", refresh);
  $("q").addEventListener("keydown", (e) => { if (e.key === "Enter") refresh(); });
  for (const id of ["channel", "author", "since", "deleted", "failed"])
    $(id).addEventListener("change", refresh);
  $("more").addEventListener("click", () => load(false));

  // Infinite scroll. The IntersectionObserver is the scroll trigger, but the
  // decision to load lives in maybeInfinite(), which also runs after each load
  // so it chains when a page is too short to scroll and does not depend on the
  // observer firing on every transition.
  const sentinelNear = () =>
    $("sentinel").getBoundingClientRect().top <= window.innerHeight + 400;
  function maybeInfinite() {
    if ($("infinite").checked && cursor && !loading && sentinelNear()) {
      load(false).then(() => {
        if ($("infinite").checked && cursor) setTimeout(maybeInfinite, 0);
      });
    }
  }
  const io = new IntersectionObserver(() => maybeInfinite(), { rootMargin: "400px" });
  io.observe($("sentinel"));
  $("infinite").addEventListener("change", (e) => {
    $("more").hidden = e.target.checked || !cursor;
    if (e.target.checked) maybeInfinite();
  });

  $("auto").addEventListener("change", (e) => {
    clearInterval(timer);
    if (e.target.checked) timer = setInterval(tail, 12000);
  });

  if ($("token").value) refresh();
})();
</script>
</body>
</html>`;

/// Render the dashboard with a per-request nonce stamped onto its inline
/// <style> and <script>. The matching Content-Security-Policy header (set by the
/// route) then allows exactly those two inline blocks and nothing else.
export function renderDashboard(nonce: string): string {
  return TEMPLATE.replaceAll("__NONCE__", nonce);
}
