# Risk

## The rule

Discord's Terms of Service prohibit automating a normal user account. This project does
exactly that. The enforcement outcome is account termination, and the loss is not the
account itself but access to every server that account is a member of, including the
alert channels this project exists to read.

That trade was made deliberately and with the alternatives on the table. This document
records what they were, so the decision can be revisited rather than rediscovered.

## The alternatives that were rejected

**Follow an Announcement channel.** Discord has a native Follow feature that cross-posts
an Announcement channel into a channel in your own server through a webhook. Zero code,
zero risk, fully supported. It only works if the source channel is an Announcement
channel, and it is worth rechecking each source channel for a Follow option before
relying on this project for that channel.

**Get a bot invited.** A bot in the source server is the supported path, but inviting one
requires Manage Server permission, which a member does not have. This depends on the
server owner agreeing.

**Use an upstream feed.** Some alert providers publish to Telegram, email, or an API.
Where one exists it sidesteps Discord entirely and should be preferred.

## What this codebase does to reduce exposure

None of this makes the approach compliant. It reduces the chance of tripping automated
detection, which keys on behaviour that no human client produces.

- **Read-only on the user account.** The account never sends a message, joins a server,
  leaves one, adds a reaction, or edits anything. It connects and listens.
- **Fan-out uses webhooks, not the account.** Posting into your own server goes through
  a Discord webhook URL, which is a separate mechanism with no link to the user session.
  The user token is never used to write anything anywhere.
- **No REST polling.** The gateway pushes events. The service makes no periodic API calls.
- **Exponential backoff on reconnect.** A reconnect loop hammering the gateway is a
  strong automation signal. Backoff is capped and jittered.
- **One connection.** Run a single instance. Two processes holding sessions for the same
  account is not a pattern a real client produces.
- **The token is never logged.** It is read from the environment and redacted from every
  log path, including tracebacks.

## Operational advice

Treat the token as a credential of the same weight as the account password, because it
is stronger than one: it bypasses two-factor authentication. Rotating it means logging
out everywhere. Never commit it, never paste it into a support channel, and be aware that
anyone who reads the `.env` file or the container environment controls the account.
