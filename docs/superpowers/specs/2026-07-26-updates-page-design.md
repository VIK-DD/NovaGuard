# Updates page — design

**Date:** 2026-07-26
**Status:** approved, ready for implementation planning

## Goal

A public `/updates` page on novaguard.fun that shows the bot's release history,
seeded with everything already announced in Discord and kept current
automatically: when the bot restarts and its changelog engine detects changed
code, the new entry appears on the site without a rebuild or a manual step.

## What exists today

- `core/updates.py` is the changelog engine. On startup `announce_startup_updates`
  fingerprints tracked files, and when they differ it builds a "Bot Update
  Deployed" embed and posts it to the configured `update_channel`.
- Engine state lives in `.update_state.json`: `fingerprint`, `files`, `latest`,
  `history`, `pending_announcement`, `last_announced_fingerprint`. The `history`
  array holds 6 entries (builds from 2026-06-28 to 2026-07-20).
- A history entry looks like:
  `{summary: string[], added_lines: int, removed_lines: int, changed_files: int,
  created_at: ISO-8601, build: int, fingerprint: str}`.
- The `#updates` channel in the configured guild holds 75 bot posts spanning
  2026-06-28 → 2026-07-24: **29** "Bot Update Deployed", 26 restart notices, and
  20 timeline recaps. Only the 29 are real content; the rest are excluded.
- The bot serves a public API under `/api/v1` (`/health`, `/stats`, `/invite`)
  from `core/webserver.py`, documented in `docs/API.md`.
- The website is static Astro on a Cloudflare Worker. `website-3/worker/index.js`
  already proxies and edge-caches the bot API in `handleStatusSnapshot`.
- The bot runs on a Raspberry Pi under pm2. There is no self-update from git, so
  bot changes reach production only when the operator pulls and restarts.

## Decisions

1. Only the 29 "Bot Update Deployed" posts become page content.
2. Updates reach the site through the bot's own API, proxied by the Worker — not
   by giving the Worker a Discord token, and not by a manual rebuild.
3. The historical archive is a **new, separate file**. `.update_state.json` is the
   live state of the changelog engine; rewriting it and shipping it to the Pi
   could fire a false announcement or clobber the fingerprint. The engine stays
   untouched.

## Components

### 1. Archive builder (one-time, `scripts/backfill_updates.py`)

Reads `#updates` over the Discord REST API, keeps messages whose embed title
matches "Bot Update Deployed", and parses each into the history entry shape.
Writes `data/updates_archive.json`, sorted oldest-first.

- Requests must send a `User-Agent` header; Discord's edge answers 403 to the
  default urllib agent before the API ever sees the token.
- Parsing is best-effort per message: fields that cannot be read (for example a
  missing diff stat) are omitted rather than guessed, and the entry still ships
  with its summary and timestamp.
- The script is idempotent — rerunning it regenerates the same file.
- Build numbers are assigned by chronological position when the embed does not
  carry one, so the sequence stays gapless.

The archive is **frozen history**, written once and then left alone: everything
newer arrives through the live engine, never through the script. That is why the
same file can exist in two places — `data/updates_archive.json` for the bot to
serve and `src/data/updates-archive.json` for the site to render at build time —
without a sync problem. Regenerating it is a deliberate act, not a routine one.

### 2. Bot endpoint — `GET /api/v1/updates`

Public, unauthenticated, same tier as `/stats`.

```json
{ "updates": [ { "build": 29, "created_at": "2026-07-24T01:28:56Z",
                 "summary": ["..."], "added_lines": 55, "removed_lines": 10,
                 "changed_files": 3 } ],
  "count": 29 }
```

- Source: `data/updates_archive.json` merged with the engine's live `history`
  and `latest`, deduplicated by `created_at`, sorted newest-first.
- `?limit=` caps the response; default 50, maximum 200.
- Documented in `docs/API.md` alongside the other public routes.

### 3. Worker proxy — `/api/updates-feed`

Mirrors `handleStatusSnapshot`: fetch the bot endpoint, return JSON, store in the
edge cache, and serve a cached copy on upstream failure. Added to `isPublicPath`
so the auth gate does not redirect it, with a `Cache-Control` of
`public, max-age=300, stale-while-revalidate=1800` — updates are not
minute-sensitive, and a longer window keeps the Pi quiet.

### 4. The page — `/updates`

The archive is committed to the site as `src/data/updates-archive.json` and
rendered **at build time**, so the page is complete HTML before any script runs —
the same rule the rest of the public site follows. A small inline script then
fetches `/api/updates-feed` and prepends any entry newer than the newest baked-in
timestamp. If the fetch fails, the page is already correct and simply lacks the
newest entries.

Layout, in the existing editorial language rather than a card grid:

- Mono eyebrow and display heading, matching the other sections.
- One row per release, separated by hairline rules — a rule inside a list carries
  meaning, which is why these stay while the decorative page rules were removed.
- Build number as a mono marker on the left. Unlike the arbitrary `01 / 02` of a
  feature list, this is a real sequence.
- Date, then the summary bullets (they already carry their own emoji).
- Signature element: each release's real diff figures (`+55 / −10`, 3 files) with
  a thin bar split green/red in proportion. Real data, not ornament.
- Linked from the nav and the footer.

## Error handling

- Bot offline: the Worker serves its cached copy; failing that, the page still
  renders the baked-in archive. The page never shows an error state for this.
- Malformed upstream payload: the merge step validates that each entry has a
  parsable `created_at` and a non-empty `summary`, and ignores the rest.
- Empty archive: the page renders its heading and a single line explaining that
  releases will appear here, rather than an empty timeline.

## Testing

- Archive builder: unit tests over recorded embed fixtures covering a full embed,
  one without diff stats, and a restart notice that must be rejected.
- Bot endpoint: tests for merge order, dedup by `created_at`, `limit` clamping,
  and the shape of the envelope.
- Worker: extend `worker/index.test.js` for the new route — cache hit, upstream
  failure, and that the path is public.
- Website: verify the page renders every archived entry with JavaScript disabled.

## Out of scope

- Restart notices and timeline recaps.
- Per-release permalinks, filtering, search, pagination, RSS.
- Any change to how the changelog engine detects or announces updates.

## Deployment

1. Website changes: build and `npm run deploy` from `website-3`.
2. Bot changes (`scripts/`, `data/updates_archive.json`, `core/webserver.py`,
   `docs/API.md`): the operator pulls on the Pi and restarts pm2. That restart is
   itself a code change, so the engine will announce it — and that announcement
   will be the first entry to reach the site through the new path.
