# Setup

## 1. Turn on Developer Mode

Discord Settings, then Advanced, then enable Developer Mode. This adds "Copy
Server ID" and "Copy Channel ID" to right-click menus, which is how you collect
the IDs the route file needs.

## 2. Collect the source IDs

For each alert channel you want to capture, right-click the server and copy its
ID, then right-click the channel and copy its ID.

While you are in each channel, look at the top of it for a **Follow** button. If
one is there, that channel is an Announcement channel and Discord will mirror it
into your own server natively, with no token and no Terms of Service exposure.
Use that instead of a route for that channel. The service logs a warning at
startup for any watched channel where this applies, but checking first saves you
running risk you did not need to take.

## 3. Create the destination webhooks

In the server you control, for each channel you want alerts delivered to: Edit
Channel, then Integrations, then Webhooks, then New Webhook, then Copy Webhook
URL.

That URL lets anyone who holds it post into that channel. Treat it as a
credential. It goes in `.env`, never in `config/routes.yaml`.

## 4. Get the account token

The token is the value Discord sends in the `Authorization` header on its API
requests. Read it from your own logged-in session in a web browser. The old
trick of reading it from the developer console is blocked by Discord's client,
so the Network tab is the reliable way.

1. Open <https://discord.com/app> in a web browser (not the desktop app) and log
   in to the account that is a member of the alert servers.
2. Open developer tools: `F12`, or `Cmd+Option+I` on macOS, or `Ctrl+Shift+I` on
   Windows and Linux. Select the **Network** tab.
3. In the Network filter box type `/api/v`, and set the filter to **Fetch/XHR**.
4. Make the client talk to the API so a request shows up: click between two
   channels, or press `Cmd/Ctrl+R` to reload.
5. Click any request to `discord.com/api/v*` (for example `messages` or
   `settings`). In its **Request Headers**, find **Authorization**.
6. Copy that value verbatim. It is the raw token: it does **not** begin with
   `Bearer` or `Bot`, and it is not your password.
7. Paste it into `.env` as `DISCORD_USER_TOKEN`.

Two things about this token that matter more than they look:

- It bypasses two-factor authentication entirely. Anyone holding it controls the
  account, without needing your password or a code. Treat it like the password,
  only more dangerous.
- Changing your Discord password invalidates it. That is also how you revoke it
  if it ever leaks.

Never commit it, and never paste it into a support channel, an issue, or a
screenshot. `.env` is gitignored for this reason.

Once the rest of `.env` is filled in (next step), confirm the token works with
`just check-token`, which reads it from `.env` and makes one read-only call to
Discord without ever printing it.

## 5. Fill in the configuration

```bash
cp .env.example .env
cp config/routes.example.yaml config/routes.yaml
```

In `.env` set the database password, `DISCORD_USER_TOKEN`, one variable per
webhook URL, and an `API_TOKEN` generated with `openssl rand -hex 32`.

In `config/routes.yaml` set the guild and channel IDs, and point each route's
`webhook_url_env` at the name of the variable holding its webhook URL. A route
with no target is archive-only: messages are stored but not forwarded.

Filters are optional and all of them are regular expressions evaluated against
the message text **and** the text inside its embeds. Start with no filters, let
real traffic accumulate for a day, then query `/alerts` to see what you actually
receive before deciding what to exclude.

## 6. Check the token before starting

Confirm the token you just pasted actually works, so a wrong paste fails in two
seconds instead of looking like a broken gateway connection later:

```bash
cd ingest && uv run resender-check-token
```

On success it prints the account the token belongs to. It never fetches or logs
the token; it only reads the one in your `.env` and makes a single read-only
call to Discord. Exit codes: `0` valid, `1` missing or rejected, `2` the check
could not reach Discord.

A `401` here means the token is wrong, truncated, or expired. Changing your
Discord password invalidates old tokens, so re-copy it from the Network tab.

## 7. Start it

```bash
docker compose up -d
docker compose logs -f ingest
```

At startup the log lists every watched channel it resolved. A channel that logs
`is not visible to this account` means the ID is wrong or the account has lost
read access there.

## 8. Verify

```bash
./scripts/verify-stack.sh
```

This applies migrations, exercises the ingest SQL against the live schema, and
checks that the API rejects unauthenticated requests.
