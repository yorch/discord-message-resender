# discord-message-resender

[![CI](https://github.com/yorch/discord-message-resender/actions/workflows/ci.yml/badge.svg)](https://github.com/yorch/discord-message-resender/actions/workflows/ci.yml)


Captures messages from Discord trading-alert channels in real time, archives them in
Postgres, and forwards them into a Discord server you control.

## What it does

```
watched channels  ──▶  ingest  ──▶  Postgres  ──▶  query API
(servers you are      (Python)      (archive)      (TypeScript)
 a member of)             │
                          └────────▶  webhook  ──▶  your own server
```

Three containers behind one Postgres:

| Service    | Language          | Responsibility                                        |
| ---------- | ----------------- | ----------------------------------------------------- |
| `ingest`   | Python 3.13       | Holds the Discord gateway connection, stores, forwards |
| `api`      | TypeScript / Node | Read-only HTTP query layer over the archive            |
| `postgres` | Postgres 18       | The archive                                            |

## Read this first

This project reads channels using **your own Discord user token**. Automating a user
account is prohibited by Discord's Terms of Service and the enforcement outcome is
account termination, which would cost you access to every server you are in.

`docs/risk.md` explains why this path was chosen, what the alternatives are, and the
specific measures this codebase takes to keep the account's behaviour close to a normal
idle client. Read it before you put a token in `.env`.

## Quick start

```bash
just setup            # copy .env + routes.yaml from examples, install deps
# edit .env (token, webhooks, API_TOKEN) and config/routes.yaml
just check-token      # confirm the Discord token works
just up               # start the stack
just logs             # follow the ingest logs
```

Without `just`, the same steps are `cp .env.example .env`,
`cp config/routes.example.yaml config/routes.yaml`, then `docker compose up -d`.
See `docs/setup.md` for how to obtain the token, guild, and channel IDs.

Confirm the stack is wired correctly with `just verify`.

Open the dashboard at `http://localhost:4000/`, paste your `API_TOKEN`, and browse
the archive. Deleted alerts are kept and shown struck through; filter to live-only or
deleted-only. Or query the API directly:

```bash
curl -H "Authorization: Bearer $API_TOKEN" \
  'http://localhost:4000/alerts?limit=20'
```

## Tasks

Common workflows are wrapped in a `Justfile`. Run `just` to list them:

- `just check` runs every quality gate (lint, typecheck, build, tests).
- `just up` / `just down` / `just logs` operate the Docker stack.
- `just verify` and `just check-integration` run the live-Postgres checks.
- `just db-migrate` / `just db-deploy` manage the schema.

## Documentation

- `docs/architecture.md` walks through the pipeline and the reasoning behind each boundary
- `docs/risk.md` covers the Terms of Service question and detection surface
- `docs/setup.md` covers getting IDs, tokens, and webhooks
- `docs/operations.md` covers running, backups, and failure recovery
