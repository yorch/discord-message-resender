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

Open Discord in a browser, open developer tools, go to the Network tab, and look
at the `Authorization` header on any request to `discord.com/api`. That value is
the token.

Two things about it that matter more than they look:

- It bypasses two-factor authentication entirely. Anyone holding it has your
  account, without needing your password or a code.
- Changing your password invalidates it, which is also how you revoke it if it
  leaks.

Never paste it into a support channel, an issue, or a screenshot.

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

## 6. Start it

```bash
docker compose up -d
docker compose logs -f ingest
```

At startup the log lists every watched channel it resolved. A channel that logs
`is not visible to this account` means the ID is wrong or the account has lost
read access there.

## 7. Verify

```bash
./scripts/verify-stack.sh
```

This applies migrations, exercises the ingest SQL against the live schema, and
checks that the API rejects unauthenticated requests.
