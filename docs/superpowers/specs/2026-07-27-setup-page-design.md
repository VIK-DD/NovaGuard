# Setup page — design

**Date:** 2026-07-27
**Status:** approved, ready for implementation planning

## Goal

A `/setup` page that does two jobs at once: convinces a visitor that configuring
NovaGuard is three steps, and serves as the reference someone returns to when they
ask "how do I set this up". It also carries the site's first honest loading state —
a strip that reads the visitor's own setup progress.

## What exists today

From `cogs/setup.py`:

- `/setup` opens a dashboard embed with buttons that assign channels, plus
  "Clear selected" and "Mark Complete". It tracks a "Setup Health" summary.
- `CHANNEL_KEYS` defines seven channels, each with a label and a description:

  | key | label | description |
  | --- | --- | --- |
  | `update_channel` | Bot Updates | Automatic code changelog and restart summaries |
  | `github_event_channel` | GitHub Feed | Push, PR, issue and release activity |
  | `error_log_channel` | Admin Errors | Serious bot error digest embeds |
  | `log_channel` | Server Logs | Deleted/edited messages, joins/leaves, bans |
  | `voice_report_channel` | Voice Reports | Completed voice session attendance and duration reports |
  | `welcome_channel` | Welcome | New member welcome cards |
  | `goodbye_channel` | Goodbye | Leave messages |

- The embed groups them as **Core** (`update_channel`, `github_event_channel`,
  `error_log_channel`, `log_channel`) and **Community** (`welcome_channel`,
  `goodbye_channel`, `voice_report_channel`).
- Four channels are **recommended**, not required — `RECOMMENDED_KEYS` in
  `cogs/setup.py:27`: `update_channel`, `error_log_channel`, `log_channel`,
  `welcome_channel`. `github_event_channel` joins them, raising the total from
  four to five, only when the bot has GitHub repos configured.
- Nothing is strictly required. `setup_completed` is a manual flag set by the
  "Mark Complete" button, independent of the score; the embed says every channel
  is optional and that a server can be marked complete with none set.
- Other commands: `/config view`, `/config export`, `/config backup`,
  `/config reset`.

From the site and API:

- `GET /guilds` (authed) returns the guilds the visitor can manage;
  `GET /guilds/{guild_id}/config` returns that guild's saved config. Both are
  documented in `docs/API.md` and already consumed by the React dashboard through
  `src/lib/api/client.ts` against `PUBLIC_API_BASE`.
- Public pages are static Astro and must render complete without JavaScript.
- Every real page currently sits behind the site password; only `/` (Coming Soon)
  and `/login` are open. The page must therefore work for a visitor who has the
  site password but has **not** connected Discord.

## Decisions

1. One page serves both audiences: the three steps first, the full reference below.
2. Content is static; a single strip is live.
3. The strip picks the guild automatically when the visitor manages exactly one,
   and offers a small selector when there are several.
4. **No emoji anywhere on the page**, including the channel table — the labels use
   their text names only, consistent with `/updates`. The Discord embed shows
   emoji; the page does not need to mirror that to be recognisable.
5. The counted channels and the total come from the same rule the bot scores with
   (`setup_score`), so the page and the bot can never disagree about progress.

## Components

### 1. Page shell — `src/pages/setup.astro`

Mono eyebrow, display heading, one-line promise, then the sections below. Linked
from the nav and the footer. Static: everything except the strip is rendered at
build time.

### 2. Progress strip — the page's only live element

Sits directly under the heading. Four states, in the order a visitor meets them:

- **Not connected** (no session, or `GET /guilds` answers 401): one quiet line
  inviting them to connect, with a link to the dashboard. The rest of the page is
  unaffected — this is the default a first-time visitor sees.
- **Connected with no manageable guilds** (`GET /guilds` returns an empty list):
  its own short line saying there is no server to report on yet, with the invite
  link. Reusing the "connect" copy here would tell a connected visitor to connect.
- **Loading**: a skeleton the width of the finished strip. This is the site's
  first honest loading state: there is a real round trip to wait for, unlike the
  static pages where a spinner would invent a delay.
- **Ready**: "3 of 4 recommended channels set", naming the ones still missing,
  with a link to the dashboard for that guild. The denominator is whatever
  `setup_score` reports, so it reads 5 on a bot with GitHub repos configured
  rather than being hard-coded to 4.

Copy says "recommended channels", matching both the Discord embed and
`RECOMMENDED_KEYS`. The page never calls a channel required, because none is:
the bot lets a server be marked complete with nothing set.
- **Unavailable** (bot offline, network error, malformed payload): the strip
  removes itself. The page is already complete without it, so there is no error
  state to show.

With more than one manageable guild, a small selector appears; choosing a guild
re-runs only the config request. The choice is not persisted — this is a reference
page, not a tool, and remembering state here would compete with the dashboard.

### 3. The three steps

Numbered `01 / 02 / 03`, vertical, in the same editorial language as the feature
list — where a number is a real position rather than decoration. Step one reuses
the existing `data-invite` anchor so `Base.astro` rewrites it to the live invite
URL. Step two names the buttons the visitor will actually see. Step three explains
what Mark Complete changes.

Chosen over three horizontal cards because the page already has the numbered-list
vocabulary; cards would introduce a second system for no gain.

### 4. Channel reference

All seven channels in the bot's own two groups, each with the description from
`CHANNEL_KEYS` and a marker on the ones `RECOMMENDED_KEYS` covers. Text labels,
no emoji.

### 5. Commands

`/setup`, `/config view`, `/config export`, `/config backup`, `/config reset`,
each with one line of purpose, in mono type like the rest of the site's command
references.

## Data flow

```
strip mounts
  → GET {PUBLIC_API_BASE}/guilds   (credentials: include)
      401 / network error → not-connected state
      []                  → no-manageable-guilds state (its own copy)
      one guild           → use it
      several             → render selector, use the first
  → GET {PUBLIC_API_BASE}/guilds/{id}/config
      → count how many recommended keys hold a channel
      → render "n of total", naming what is missing
      failure → remove the strip
```

The recommended keys, and the rule that adds `github_event_channel` to the
total, are declared once in the page's data module so the count cannot drift
from `setup_score`.

## Error handling

- Any failure in the strip is silent: it removes itself rather than showing an
  error, because the page's purpose survives without it.
- A malformed config payload is treated as a failure, not as "nothing configured" —
  reporting "0 of n" for a parse error would be a lie.
- The page renders and reads completely with JavaScript disabled; the strip is the
  only thing lost.

## Testing

- Unit tests for the recommended-channel counter: all set, none set, some set,
  the GitHub case that raises the total to five,
  a payload missing the keys entirely, and a malformed payload (which must be
  distinguishable from "none set").
- Unit test for guild selection: none, one, several.
- Verify the built page contains all seven channels and all five commands with
  JavaScript disabled.
- Verify the invite anchor carries `data-invite` so the layout rewrites it.

## Out of scope

- Editing configuration from this page. That is the dashboard's job; this page
  reports and explains.
- Persisting the selected guild.
- Per-guild deep links beyond a link into the dashboard.
- Any change to `cogs/setup.py` or the bot API. The page consumes what exists.

## Deployment

Not website-only: implementation added `github_watch_configured` to
`core/webserver.py`'s config payload, and the website's Zod schema now
requires that field. Deploy the bot first — `git pull` + `pm2 restart
pythonbot` on the Pi — then `npm run deploy` from `website-3`. In the wrong
order, a newer website would fail to parse the config response from an older
bot entirely.
