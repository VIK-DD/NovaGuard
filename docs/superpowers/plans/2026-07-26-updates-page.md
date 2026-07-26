# Updates Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a paginated public `/updates` page seeded from the 29 "Bot Update Deployed" posts in Discord, which then stays current on its own through a new public bot endpoint proxied by the Worker.

**Architecture:** A one-time script parses the Discord archive into `core/updates_archive.json`. A new `core/update_feed.py` merges that frozen archive with the changelog engine's live history and serves it from `GET /api/v1/updates` — `core/updates.py` is never touched. The Worker proxies and edge-caches that at `/api/updates-feed`. The site commits its own copy of the archive and renders paginated static routes, then a small script on page one prepends anything newer.

**Tech Stack:** Python 3.11 + aiohttp (bot), Astro 5 + Tailwind 4 (site), Cloudflare Workers (edge), vitest (JS tests), plain-script asserts (Python tests).

## Global Constraints

- Only embeds whose title contains "Bot Update Deployed" become content. Restart notices and timeline recaps are excluded.
- No emoji anywhere on the page. Emoji exist only in Discord *field names*, which are never rendered.
- `core/updates.py` and `.update_state.json` must not be modified. The archive is a separate, frozen file.
- The Worker never receives a Discord token. It talks only to the bot API.
- Discord REST requests must send `User-Agent: DiscordBot (https://novaguard.fun, 3.0.0)`; the default urllib agent gets a 403 from Discord's edge before the API sees the token.
- `RELEASES_PER_PAGE = 6`.
- Pages must render complete HTML with JavaScript disabled.
- Bot tests are plain scripts run with `python tests/<file>.py`; there is no pytest in this repo.
- Bot API base for the Worker comes from `env.STATUS_API_BASE`, falling back to `DEFAULT_STATUS_API_BASE`.
- **All work happens in the worktree** `/Users/breabinvictor/Desktop/pythonbot/.claude/worktrees/mhc-movie-discovery-ui-797715` on branch `claude/website-audit-optimization-03e65e`. The main checkout is on `main` and must not be implemented against. Where a step shows the repo root, read it as the worktree root.
- The archive builder needs `TOKEN` and `UPDATE_CHANNEL_ID`. `.env` exists only in the main checkout, so export the two values into the environment before running the script; never echo them.

## File Structure

**Bot repo (root)**
- Create `scripts/backfill_updates.py` — Discord archive parser + writer. Pure parse functions, network only in `main()`.
- Create `core/update_feed.py` — loads the frozen archive, normalises engine history, merges/dedupes/sorts. Sole owner of feed shape.
- Create `tests/test_backfill_updates.py` — parser tests over inline embed fixtures.
- Create `tests/test_update_feed.py` — merge, dedupe, limit tests.
- Modify `core/webserver.py` — one handler + one route row.
- Modify `docs/API.md` — document the endpoint.
- Generated: `core/updates_archive.json`.

**Website (`website-3/`)**
- Create `src/data/updates.ts` — `Release` type, `RELEASES_PER_PAGE`, sort/dedupe/merge/diff helpers. No rendering.
- Create `src/data/updates-archive.json` — committed copy of the archive.
- Create `src/data/updates.test.ts` — helper tests.
- Create `src/components/ReleaseEntry.astro` — one release row.
- Create `src/components/Pager.astro` — numbered pagination control.
- Create `src/pages/updates/[...page].astro` — paginated route.
- Modify `worker/index.js` — `/api/updates-feed` handler, public path, cache header.
- Modify `worker/index.test.js` — route tests.
- Modify `src/components/Nav.astro`, `src/components/Footer.astro` — links.

---

### Task 1: Archive parser and builder

**Files:**
- Create: `scripts/backfill_updates.py`
- Test: `tests/test_backfill_updates.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `parse_deploy_embed(embed: dict, created_at: str, fallback_build: int) -> dict | None`, `normalize_field_name(name: str) -> str`, `parse_bullets(value: str) -> list[str]`. Entry dict keys: `build: int`, `created_at: str`, optional `version: str`, `codename: str`, `highlights: list[str]`, `changes: list[str]`, `added_lines: int`, `removed_lines: int`, `changed_files: int`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_backfill_updates.py`:

```python
"""Parser tests for the Discord update archive builder."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.backfill_updates import (
    normalize_field_name,
    parse_bullets,
    parse_deploy_embed,
)

results = []


def check(name, ok):
    results.append((name, ok))
    print(f"{'ok  ' if ok else 'FAIL'} {name}")


FULL_EMBED = {
    "title": "\U0001f680 Bot Update Deployed",
    "description": "A fresh NovaGuard build is live.",
    "fields": [
        {
            "name": "✨ Release Highlights",
            "value": "• Setup wizard upgraded\n• Automatic backups added",
        },
        {
            "name": "\U0001f9ed Command & Project Changes",
            "value": "• Internal engine improvements: `cogs/voice.py`",
        },
        {
            "name": "\U0001f4ca Code Stats",
            "value": "```diff\n+ 48 lines added\n- 8 lines removed\n~ 1 tracked files changed\n```",
        },
        {"name": "\U0001f3d7️ Build", "value": '`#16` • v3.0.0 "Nova"'},
    ],
}

PLAIN_NAMES_EMBED = {
    "title": "Bot Update Deployed",
    "fields": [
        {"name": "What Changed", "value": "• Tickets reworked"},
        {"name": "Code Stats", "value": "```diff\n+ 5 lines added\n- 0 lines removed\n```"},
    ],
}

STATS_ONLY_EMBED = {
    "title": "\U0001f680 Bot Update Deployed",
    "fields": [
        {
            "name": "\U0001f4ca Code Stats",
            "value": "```diff\n+ 12 lines added\n- 3 lines removed\n~ 2 tracked files changed\n```",
        }
    ],
}

RESTART_EMBED = {
    "title": "\U0001f504 Bot Restarted • Current Live Build",
    "fields": [{"name": "\U0001f3d7️ Build", "value": "`#17`"}],
}

check("emoji field name normalises", normalize_field_name("\U0001f4ca Code Stats") == "code stats")
check(
    "ampersand kept",
    normalize_field_name("\U0001f9ed Command & Project Changes") == "command & project changes",
)
check("plain name unchanged", normalize_field_name("What Changed") == "what changed")

check("bullet markers stripped", parse_bullets("• One\n• Two") == ["One", "Two"])
check("code fences dropped", parse_bullets("```diff\n+ 1 lines added\n```") == ["+ 1 lines added"])
check("blank lines dropped", parse_bullets("• One\n\n• Two") == ["One", "Two"])

entry = parse_deploy_embed(FULL_EMBED, "2026-07-24T01:28:56+00:00", 99)
check("full embed parsed", entry is not None)
check("build read from embed not fallback", entry["build"] == 16)
check("version read", entry["version"] == "3.0.0")
check("codename read", entry["codename"] == "Nova")
check(
    "highlights grouped",
    entry["highlights"] == ["Setup wizard upgraded", "Automatic backups added"],
)
check("changes grouped", entry["changes"] == ["Internal engine improvements: `cogs/voice.py`"])
check("added lines", entry["added_lines"] == 48)
check("removed lines", entry["removed_lines"] == 8)
check("changed files", entry["changed_files"] == 1)
check("created_at carried", entry["created_at"] == "2026-07-24T01:28:56+00:00")
check("no emoji leaks into content", "\U0001f680" not in repr(entry))

plain = parse_deploy_embed(PLAIN_NAMES_EMBED, "2026-07-01T00:00:00+00:00", 7)
check("plain field names accepted", plain["highlights"] == ["Tickets reworked"])
check("fallback build used when embed has none", plain["build"] == 7)
check("missing changed_files omitted", "changed_files" not in plain)

stats_only = parse_deploy_embed(STATS_ONLY_EMBED, "2026-07-02T00:00:00+00:00", 8)
check("release with stats but no bullets is kept", stats_only is not None)
check(
    "stats-only entry has no bullet keys",
    "highlights" not in stats_only and "changes" not in stats_only,
)

check(
    "restart notice rejected",
    parse_deploy_embed(RESTART_EMBED, "2026-07-03T00:00:00+00:00", 9) is None,
)
check("empty embed rejected", parse_deploy_embed({"title": "Bot Update Deployed"}, "x", 1) is None)

failed = [name for name, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
if failed:
    raise SystemExit(1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/breabinvictor/Desktop/pythonbot && python tests/test_backfill_updates.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.backfill_updates'`

- [ ] **Step 3: Write minimal implementation**

Create an empty `scripts/__init__.py`, then create `scripts/backfill_updates.py`:

```python
"""Build the frozen updates archive from the Discord #updates channel.

Run once. Reads every "Bot Update Deployed" embed, parses it into the feed entry
shape, and writes core/updates_archive.json oldest-first. Restart notices and
timeline recaps are ignored. Read-only against Discord; never prints the token.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
# `data/` is gitignored — it holds the live SQLite database — so the archive lives
# beside the module that reads it and ships with an ordinary pull.
ARCHIVE_PATH = BASE_DIR / "core" / "updates_archive.json"
DISCORD_API = "https://discord.com/api/v10"
# Discord's edge answers 403 to the default urllib agent before the API sees the
# token, so identify the client the way its docs require.
USER_AGENT = "DiscordBot (https://novaguard.fun, 3.0.0)"

DEPLOY_TITLE = re.compile(r"bot update deployed", re.I)
FIELD_ALIASES = {
    "release highlights": "highlights",
    "what changed": "highlights",
    "command & project changes": "changes",
    "code stats": "stats",
    "build": "build",
}
STAT_PATTERNS = {
    "added_lines": re.compile(r"\+\s*(\d+)\s*lines?\s+added", re.I),
    "removed_lines": re.compile(r"-\s*(\d+)\s*lines?\s+removed", re.I),
    "changed_files": re.compile(r"~\s*(\d+)\s*tracked\s+files?\s+changed", re.I),
}
BUILD_PATTERN = re.compile(r"#(\d+)")
VERSION_PATTERN = re.compile(r"v(\d+\.\d+\.\d+)")
CODENAME_PATTERN = re.compile(r'"([^"]+)"')


def normalize_field_name(name):
    """Fold a field name to a comparable key, dropping the decorative emoji."""
    lowered = (name or "").lower()
    stripped = re.sub(r"[^a-z0-9&\s]", "", lowered)
    return re.sub(r"\s+", " ", stripped).strip()


def parse_bullets(value):
    """Split a field value into bullet lines, without markers or code fences."""
    bullets = []
    for raw in (value or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("```"):
            continue
        line = line.lstrip("•-* \t").strip()
        if line:
            bullets.append(line)
    return bullets


def parse_deploy_embed(embed, created_at, fallback_build):
    """Turn one deploy embed into a feed entry, or None if it is not one."""
    if not DEPLOY_TITLE.search(embed.get("title") or ""):
        return None

    entry = {"build": fallback_build, "created_at": created_at}
    highlights = []
    changes = []

    for field in embed.get("fields") or []:
        key = FIELD_ALIASES.get(normalize_field_name(field.get("name")))
        value = field.get("value") or ""
        if key == "highlights":
            highlights.extend(parse_bullets(value))
        elif key == "changes":
            changes.extend(parse_bullets(value))
        elif key == "stats":
            for stat_key, pattern in STAT_PATTERNS.items():
                match = pattern.search(value)
                if match:
                    entry[stat_key] = int(match.group(1))
        elif key == "build":
            build_match = BUILD_PATTERN.search(value)
            if build_match:
                entry["build"] = int(build_match.group(1))
            version_match = VERSION_PATTERN.search(value)
            if version_match:
                entry["version"] = version_match.group(1)
            codename_match = CODENAME_PATTERN.search(value)
            if codename_match:
                entry["codename"] = codename_match.group(1)

    if highlights:
        entry["highlights"] = highlights
    if changes:
        entry["changes"] = changes

    has_stats = any(stat_key in entry for stat_key in STAT_PATTERNS)
    if not highlights and not changes and not has_stats:
        return None
    return entry


def load_env(path):
    values = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def discord_get(url, token):
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bot {token}", "User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_channel_messages(channel_id, token):
    messages = []
    before = None
    while True:
        url = f"{DISCORD_API}/channels/{channel_id}/messages?limit=100"
        if before:
            url += f"&before={before}"
        batch = discord_get(url, token)
        if not batch:
            break
        messages.extend(batch)
        before = batch[-1]["id"]
        if len(batch) < 100:
            break
    return messages


def build_archive(messages):
    """Parse newest-first Discord messages into an oldest-first archive."""
    entries = []
    for message in reversed(messages):
        for embed in message.get("embeds") or []:
            entry = parse_deploy_embed(embed, message.get("timestamp"), len(entries) + 1)
            if entry:
                entries.append(entry)
    return entries


def main():
    env = load_env(BASE_DIR / ".env")
    token = os.environ.get("TOKEN") or env.get("TOKEN")
    channel_id = os.environ.get("UPDATE_CHANNEL_ID") or env.get("UPDATE_CHANNEL_ID")
    if not token or not channel_id:
        print("TOKEN and UPDATE_CHANNEL_ID must be set in the environment or .env")
        return 1

    try:
        messages = fetch_channel_messages(channel_id, token)
    except urllib.error.HTTPError as error:
        print(f"Discord request failed: HTTP {error.code} - {error.reason}")
        return 1

    entries = build_archive(messages)
    ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVE_PATH.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(entries)} releases to {ARCHIVE_PATH.relative_to(BASE_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/breabinvictor/Desktop/pythonbot && python tests/test_backfill_updates.py`
Expected: PASS — final line `24/24 passed`

- [ ] **Step 5: Generate the archive**

Run: `cd /Users/breabinvictor/Desktop/pythonbot && python scripts/backfill_updates.py`
Expected: `wrote 29 releases to core/updates_archive.json`

If the count is not 29, stop and report it rather than adjusting the parser to force the number.

- [ ] **Step 6: Verify the archive shape**

Run:
```bash
cd /Users/breabinvictor/Desktop/pythonbot && python -c "
import json
entries = json.load(open('core/updates_archive.json'))
print('entries:', len(entries))
print('builds ascending:', [e['build'] for e in entries] == sorted(e['build'] for e in entries))
print('all have created_at:', all(e.get('created_at') for e in entries))
print('emoji-free:', all('\U0001f680' not in json.dumps(e) for e in entries))
"
```
Expected: `entries: 29`, then `True` on the other three lines.

- [ ] **Step 7: Commit**

```bash
cd /Users/breabinvictor/Desktop/pythonbot
git add scripts/__init__.py scripts/backfill_updates.py tests/test_backfill_updates.py core/updates_archive.json
git commit -m "feat(updates): build the frozen release archive from Discord"
```

---

### Task 2: Website feed helpers

**Files:**
- Create: `website-3/src/data/updates.ts`
- Create: `website-3/src/data/updates-archive.json`
- Test: `website-3/src/data/updates.test.ts`

**Interfaces:**
- Consumes: the archive entry shape from Task 1.
- Produces: `interface Release`, `RELEASES_PER_PAGE = 6`, `sortNewestFirst(releases: Release[]): Release[]`, `dedupeByCreatedAt(releases: Release[]): Release[]`, `newerThan(releases: Release[], cutoffIso: string): Release[]`, `diffSplit(release: Release): { added: number; removed: number; addedPercent: number }`, `formatReleaseDate(iso: string): string`. Task 6's browser script imports `newerThan` — the cutoff rule is written and tested once, here.

- [ ] **Step 1: Copy the archive into the site**

```bash
cd /Users/breabinvictor/Desktop/pythonbot
cp core/updates_archive.json .claude/worktrees/mhc-movie-discovery-ui-797715/website-3/src/data/updates-archive.json
```

- [ ] **Step 2: Write the failing test**

Create `website-3/src/data/updates.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  RELEASES_PER_PAGE,
  dedupeByCreatedAt,
  diffSplit,
  formatReleaseDate,
  newerThan,
  sortNewestFirst,
  type Release,
} from "./updates";

const older: Release = { build: 1, created_at: "2026-06-28T10:00:00+00:00", changes: ["First"] };
const newer: Release = { build: 2, created_at: "2026-07-01T10:00:00+00:00", changes: ["Second"] };
const newest: Release = { build: 3, created_at: "2026-07-20T10:00:00+00:00", changes: ["Third"] };

describe("sortNewestFirst", () => {
  it("puts the most recent release first", () => {
    expect(sortNewestFirst([older, newest, newer]).map((r) => r.build)).toEqual([3, 2, 1]);
  });

  it("does not mutate its input", () => {
    const input = [older, newest];
    sortNewestFirst(input);
    expect(input.map((r) => r.build)).toEqual([1, 3]);
  });
});

describe("dedupeByCreatedAt", () => {
  it("keeps the first entry for a repeated timestamp", () => {
    const duplicate: Release = { build: 99, created_at: older.created_at, changes: ["Dup"] };
    const result = dedupeByCreatedAt([older, duplicate, newer]);
    expect(result.map((r) => r.build)).toEqual([1, 2]);
  });
});

describe("newerThan", () => {
  it("keeps only entries newer than the cutoff", () => {
    expect(newerThan([newest, newer, older], newer.created_at).map((r) => r.build)).toEqual([3]);
  });

  it("returns nothing when every entry is at or below the cutoff", () => {
    expect(newerThan([older, newer], newest.created_at)).toEqual([]);
  });

  it("returns nothing for an unparsable cutoff", () => {
    expect(newerThan([newest], "not-a-date")).toEqual([]);
  });

  it("returns its results newest first", () => {
    expect(newerThan([newer, newest], older.created_at).map((r) => r.build)).toEqual([3, 2]);
  });
});

describe("diffSplit", () => {
  it("splits the bar proportionally", () => {
    expect(diffSplit({ build: 1, created_at: "x", added_lines: 75, removed_lines: 25 })).toEqual({
      added: 75,
      removed: 25,
      addedPercent: 75,
    });
  });

  it("reports zero width when a release has no diff stats", () => {
    expect(diffSplit({ build: 1, created_at: "x" })).toEqual({
      added: 0,
      removed: 0,
      addedPercent: 0,
    });
  });
});

describe("formatReleaseDate", () => {
  it("renders a readable date", () => {
    expect(formatReleaseDate("2026-07-24T01:28:56+00:00")).toBe("24 July 2026");
  });

  it("passes through an unparsable value", () => {
    expect(formatReleaseDate("not-a-date")).toBe("not-a-date");
  });
});

describe("page size", () => {
  it("is six", () => {
    expect(RELEASES_PER_PAGE).toBe(6);
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /Users/breabinvictor/Desktop/pythonbot/.claude/worktrees/mhc-movie-discovery-ui-797715/website-3 && ./node_modules/.bin/vitest run src/data/updates.test.ts`
Expected: FAIL — cannot resolve `./updates`

- [ ] **Step 4: Write minimal implementation**

Create `website-3/src/data/updates.ts`:

```ts
// Shape and ordering rules for the release feed. Rendering lives in the
// components; this module only sorts, dedupes and measures.

export interface Release {
  build: number;
  version?: string;
  codename?: string;
  created_at: string;
  highlights?: string[];
  changes?: string[];
  added_lines?: number;
  removed_lines?: number;
  changed_files?: number;
}

export const RELEASES_PER_PAGE = 6;

function timestamp(release: Release): number {
  const parsed = Date.parse(release.created_at);
  return Number.isNaN(parsed) ? 0 : parsed;
}

export function sortNewestFirst(releases: Release[]): Release[] {
  return [...releases].sort((a, b) => timestamp(b) - timestamp(a));
}

export function dedupeByCreatedAt(releases: Release[]): Release[] {
  const seen = new Set<string>();
  return releases.filter((release) => {
    if (seen.has(release.created_at)) return false;
    seen.add(release.created_at);
    return true;
  });
}

// The live feed may only ever add releases on top of what the build baked in.
// Anything at or below the newest baked-in timestamp already has a static page,
// so admitting it would render the same release twice. An unreadable cutoff
// admits nothing — a duplicate is worse than a missing newest entry.
export function newerThan(releases: Release[], cutoffIso: string): Release[] {
  const cutoff = Date.parse(cutoffIso);
  if (Number.isNaN(cutoff)) return [];
  return sortNewestFirst(releases.filter((release) => timestamp(release) > cutoff));
}

export function diffSplit(release: Release): {
  added: number;
  removed: number;
  addedPercent: number;
} {
  const added = release.added_lines ?? 0;
  const removed = release.removed_lines ?? 0;
  const total = added + removed;
  return {
    added,
    removed,
    addedPercent: total ? Math.round((added / total) * 100) : 0,
  };
}

export function formatReleaseDate(iso: string): string {
  const parsed = Date.parse(iso);
  if (Number.isNaN(parsed)) return iso;
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(new Date(parsed));
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/breabinvictor/Desktop/pythonbot/.claude/worktrees/mhc-movie-discovery-ui-797715/website-3 && ./node_modules/.bin/vitest run src/data/updates.test.ts`
Expected: PASS — 12 tests

- [ ] **Step 6: Commit**

```bash
cd /Users/breabinvictor/Desktop/pythonbot/.claude/worktrees/mhc-movie-discovery-ui-797715
git add website-3/src/data/updates.ts website-3/src/data/updates.test.ts website-3/src/data/updates-archive.json
git commit -m "feat(website): release feed helpers and committed archive"
```

---

### Task 3: The paginated page

**Files:**
- Create: `website-3/src/components/ReleaseEntry.astro`
- Create: `website-3/src/components/Pager.astro`
- Create: `website-3/src/pages/updates/[...page].astro`

**Interfaces:**
- Consumes: `Release`, `RELEASES_PER_PAGE`, `sortNewestFirst`, `diffSplit`, `formatReleaseDate` from Task 2.
- Produces: routes `/updates`, `/updates/2` … each rendering every release for that page as static HTML. Page one carries `data-newest-baked` on `[data-release-list]`, which Task 6 reads.

- [ ] **Step 1: Create the release row component**

Create `website-3/src/components/ReleaseEntry.astro`:

```astro
---
import { diffSplit, formatReleaseDate, type Release } from "../data/updates";

interface Props {
  release: Release;
}

const { release } = Astro.props;
const { added, removed, addedPercent } = diffSplit(release);
const hasDiff = added > 0 || removed > 0;
const highlights = release.highlights ?? [];
const changes = release.changes ?? [];
---

<article class="grid gap-4 py-8 sm:grid-cols-[7rem_1fr] sm:gap-8 sm:py-10">
  <div class="sm:text-right">
    <p class="font-mono text-sm text-primary">#{release.build}</p>
    {
      release.version && (
        <p class="mt-1 font-mono text-xs text-ink-faint">
          v{release.version}
          {release.codename ? ` · ${release.codename}` : ""}
        </p>
      )
    }
    <p class="mt-1 text-xs text-ink-faint sm:mt-2">{formatReleaseDate(release.created_at)}</p>
  </div>

  <div class="min-w-0">
    {
      highlights.length > 0 && (
        <>
          <p class="font-mono text-[11px] tracking-[0.14em] text-ink-faint uppercase">Highlights</p>
          <ul class="mt-2 space-y-1.5">
            {highlights.map((item) => <li class="text-sm leading-relaxed text-ink">{item}</li>)}
          </ul>
        </>
      )
    }
    {
      changes.length > 0 && (
        <>
          <p
            class:list={[
              "font-mono text-[11px] tracking-[0.14em] text-ink-faint uppercase",
              highlights.length > 0 && "mt-5",
            ]}
          >
            Changes
          </p>
          <ul class="mt-2 space-y-1.5">
            {changes.map((item) => <li class="text-sm leading-relaxed text-ink-muted">{item}</li>)}
          </ul>
        </>
      )
    }
    {
      hasDiff && (
        <div class="mt-5 flex items-center gap-3">
          <span class="font-mono text-xs text-good">+{added}</span>
          <span class="font-mono text-xs text-primary">−{removed}</span>
          {
            release.changed_files !== undefined && (
              <span class="font-mono text-xs text-ink-faint">
                {release.changed_files} {release.changed_files === 1 ? "file" : "files"}
              </span>
            )
          }
          <span
            class="ml-auto flex h-1 w-28 overflow-hidden rounded-full bg-line"
            role="img"
            aria-label={`${added} lines added, ${removed} lines removed`}
          >
            <span class="h-full bg-good" style={`width:${addedPercent}%`}></span>
            <span class="h-full flex-1 bg-primary"></span>
          </span>
        </div>
      )
    }
  </div>
</article>
```

- [ ] **Step 2: Create the pager component**

Create `website-3/src/components/Pager.astro`:

```astro
---
interface Props {
  current: number;
  total: number;
  prevUrl?: string;
  nextUrl?: string;
}

const { current, total, prevUrl, nextUrl } = Astro.props;
const pageUrl = (page: number) => (page === 1 ? "/updates" : `/updates/${page}`);
const pages = Array.from({ length: total }, (_, index) => index + 1);
const linkBase =
  "grid h-11 min-w-11 place-items-center rounded-[6px] px-3 font-mono text-sm transition-colors";
---

{
  total > 1 && (
    <nav class="flex flex-wrap items-center justify-center gap-1.5 pt-10" aria-label="Releases">
      {
        prevUrl ? (
          <a
            href={prevUrl}
            rel="prev"
            class:list={[linkBase, "text-ink-muted hover:bg-card hover:text-ink"]}
          >
            Prev
          </a>
        ) : (
          <span class:list={[linkBase, "text-ink-faint"]} aria-hidden="true">
            Prev
          </span>
        )
      }
      {
        pages.map((page) =>
          page === current ? (
            <span class:list={[linkBase, "bg-primary text-primary-ink"]} aria-current="page">
              {page}
            </span>
          ) : (
            <a
              href={pageUrl(page)}
              class:list={[linkBase, "text-ink-muted hover:bg-card hover:text-ink"]}
            >
              {page}
            </a>
          ),
        )
      }
      {
        nextUrl ? (
          <a
            href={nextUrl}
            rel="next"
            class:list={[linkBase, "text-ink-muted hover:bg-card hover:text-ink"]}
          >
            Next
          </a>
        ) : (
          <span class:list={[linkBase, "text-ink-faint"]} aria-hidden="true">
            Next
          </span>
        )
      }
    </nav>
  )
}
```

- [ ] **Step 3: Create the paginated route**

Create `website-3/src/pages/updates/[...page].astro`:

```astro
---
import type { GetStaticPaths, Page } from "astro";
import Base from "../../layouts/Base.astro";
import Nav from "../../components/Nav.astro";
import Footer from "../../components/Footer.astro";
import Pager from "../../components/Pager.astro";
import ReleaseEntry from "../../components/ReleaseEntry.astro";
import archive from "../../data/updates-archive.json";
import { RELEASES_PER_PAGE, sortNewestFirst, type Release } from "../../data/updates";

export const getStaticPaths: GetStaticPaths = ({ paginate }) =>
  paginate(sortNewestFirst(archive as Release[]), { pageSize: RELEASES_PER_PAGE });

const { page } = Astro.props as { page: Page<Release> };
const newestBaked = page.currentPage === 1 ? (page.data[0]?.created_at ?? "") : "";
---

<Base
  title="Updates — NovaGuard"
  description="Every NovaGuard release, generated automatically from the deployed code."
>
  <Nav />
  <main>
    <section data-perf-section class="mx-auto max-w-6xl px-5 py-14 sm:px-6 sm:py-20">
      <p class="font-mono text-xs tracking-[0.14em] text-primary uppercase">Updates</p>
      <h1
        class="mt-4 max-w-2xl font-display text-[2.1rem] leading-[1.08] font-semibold tracking-[-0.02em] text-balance sm:text-5xl"
      >
        Every release, written by the code itself.
      </h1>
      <p class="mt-5 max-w-md text-base leading-relaxed text-ink-muted">
        NovaGuard fingerprints its own source on every start. When something changed, it writes the
        release note below — no one edits this page by hand.
      </p>

      <div
        class="mt-12 divide-y divide-line border-t border-line"
        data-release-list
        data-newest-baked={newestBaked}
      >
        {page.data.map((release) => <ReleaseEntry release={release} />)}
        {
          page.data.length === 0 && (
            <p data-empty-note class="py-8 text-sm text-ink-muted">
              No releases have been recorded yet. The next time NovaGuard starts with changed code,
              its release note will appear here.
            </p>
          )
        }
      </div>

      <Pager
        current={page.currentPage}
        total={page.lastPage}
        prevUrl={page.url.prev}
        nextUrl={page.url.next}
      />
    </section>
  </main>
  <Footer />
</Base>
```

- [ ] **Step 4: Build and verify the routes exist**

Run:
```bash
cd /Users/breabinvictor/Desktop/pythonbot/.claude/worktrees/mhc-movie-discovery-ui-797715/website-3
./node_modules/.bin/astro check && ./node_modules/.bin/astro build
ls dist/updates/index.html dist/updates/2/index.html dist/updates/5/index.html
```
Expected: `astro check` reports 0 errors; all three files listed.

- [ ] **Step 5: Verify every release renders without JavaScript**

Run:
```bash
cd /Users/breabinvictor/Desktop/pythonbot/.claude/worktrees/mhc-movie-discovery-ui-797715/website-3
python3 -c "
import glob, re
total = 0
for path in sorted(glob.glob('dist/updates/**/index.html', recursive=True)):
    count = len(re.findall(r'<article', open(path, encoding='utf-8').read()))
    total += count
    print(path, count)
print('total releases rendered:', total)
"
```
Expected: five pages of 6/6/6/6/5 and `total releases rendered: 29`.

- [ ] **Step 6: Commit**

```bash
cd /Users/breabinvictor/Desktop/pythonbot/.claude/worktrees/mhc-movie-discovery-ui-797715
git add website-3/src/components/ReleaseEntry.astro website-3/src/components/Pager.astro website-3/src/pages/updates/
git commit -m "feat(website): paginated updates timeline"
```

---

### Task 4: Bot endpoint

**Files:**
- Create: `core/update_feed.py`
- Test: `tests/test_update_feed.py`
- Modify: `core/webserver.py` — routes list at ~line 416, new handler after `handle_stats` at ~line 866
- Modify: `docs/API.md`

**Interfaces:**
- Consumes: the archive file written in Task 1.
- Produces: `merged_update_feed(limit=50, archive=None, history=None, latest=None) -> list[dict]` and `normalize_engine_entry(entry: dict) -> dict | None`. Endpoint `GET /api/v1/updates?limit=` returning `{"updates": [...], "count": int}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_update_feed.py`:

```python
"""Merge rules for the public update feed."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.update_feed import merged_update_feed, normalize_engine_entry

results = []


def check(name, ok):
    results.append((name, ok))
    print(f"{'ok  ' if ok else 'FAIL'} {name}")


ARCHIVE = [
    {"build": 1, "created_at": "2026-06-28T10:00:00+00:00", "changes": ["First"]},
    {"build": 2, "created_at": "2026-07-01T10:00:00+00:00", "highlights": ["Second"]},
]
HISTORY = [
    {
        "build": 3,
        "created_at": "2026-07-20T10:00:00+00:00",
        "summary": ["Third", "Also third"],
        "added_lines": 55,
        "removed_lines": 10,
        "changed_files": 3,
    }
]

feed = merged_update_feed(limit=50, archive=ARCHIVE, history=HISTORY, latest=None)
check("all entries merged", len(feed) == 3)
check("newest first", [entry["build"] for entry in feed] == [3, 2, 1])
check("engine summary becomes changes", feed[0]["changes"] == ["Third", "Also third"])
check("engine entry keeps no summary key", "summary" not in feed[0])
check("stats carried through", feed[0]["added_lines"] == 55)
check("archive highlights preserved", feed[1]["highlights"] == ["Second"])

duplicate = dict(ARCHIVE[1], build=99, summary=["Dup"])
deduped = merged_update_feed(limit=50, archive=ARCHIVE, history=[duplicate], latest=None)
check("duplicate created_at dropped", len(deduped) == 2)
check("archive entry wins over engine duplicate", deduped[0]["build"] == 2)

limited = merged_update_feed(limit=1, archive=ARCHIVE, history=HISTORY, latest=None)
check("limit applied", len(limited) == 1)
check("limit keeps the newest", limited[0]["build"] == 3)

with_latest = merged_update_feed(
    limit=50,
    archive=[],
    history=[],
    latest={"build": 9, "created_at": "2026-07-25T10:00:00+00:00", "summary": ["Latest"]},
)
check("latest included when history is empty", [entry["build"] for entry in with_latest] == [9])

check("entry without created_at rejected", normalize_engine_entry({"summary": ["x"]}) is None)
check(
    "entry without bullets or stats rejected",
    normalize_engine_entry({"created_at": "2026-07-01T00:00:00+00:00"}) is None,
)
check(
    "entry with only stats accepted",
    normalize_engine_entry({"created_at": "2026-07-01T00:00:00+00:00", "added_lines": 4})
    is not None,
)
check(
    "unparsable created_at rejected",
    normalize_engine_entry({"created_at": "nope", "summary": ["x"]}) is None,
)

check("empty inputs give an empty feed", merged_update_feed(limit=50, archive=[], history=[], latest=None) == [])

failed = [name for name, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
if failed:
    raise SystemExit(1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/breabinvictor/Desktop/pythonbot && python tests/test_update_feed.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.update_feed'`

- [ ] **Step 3: Write minimal implementation**

Create `core/update_feed.py`:

```python
"""Public update feed: the frozen Discord archive plus the live engine history.

Read-only with respect to the changelog engine — this module never writes
.update_state.json.
"""

from datetime import datetime

from .config import BASE_DIR
from .storage import load_json_file

ARCHIVE_FILE = BASE_DIR / "core" / "updates_archive.json"
STAT_KEYS = ("added_lines", "removed_lines", "changed_files")
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def load_archive():
    entries = load_json_file(ARCHIVE_FILE, [])
    return entries if isinstance(entries, list) else []


def _timestamp(value):
    """Sortable epoch seconds, or None when the value is not a usable date."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _bullets(value):
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def normalize_engine_entry(entry):
    """Reshape one engine history entry into a feed entry, or None if unusable.

    The engine records a single `summary` list; the feed exposes `changes`, so the
    page only ever handles the archive's shape.
    """
    if not isinstance(entry, dict):
        return None
    if _timestamp(entry.get("created_at")) is None:
        return None

    normalized = {"created_at": entry["created_at"]}
    if isinstance(entry.get("build"), int):
        normalized["build"] = entry["build"]
    for key in STAT_KEYS:
        if isinstance(entry.get(key), int):
            normalized[key] = entry[key]

    changes = _bullets(entry.get("summary")) or _bullets(entry.get("changes"))
    highlights = _bullets(entry.get("highlights"))
    if changes:
        normalized["changes"] = changes
    if highlights:
        normalized["highlights"] = highlights

    if not changes and not highlights and not any(key in normalized for key in STAT_KEYS):
        return None
    return normalized


def merged_update_feed(limit=DEFAULT_LIMIT, archive=None, history=None, latest=None):
    """Newest-first feed, deduplicated by `created_at`, capped at `limit`.

    The archive wins a collision: it is verified history, while the engine may
    re-record the same release after a state reset.
    """
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    limit = max(1, min(limit, MAX_LIMIT))

    archive_entries = load_archive() if archive is None else archive
    engine_entries = list(history or [])
    if latest:
        engine_entries.append(latest)

    feed = []
    seen = set()
    for entry in archive_entries:
        if not isinstance(entry, dict):
            continue
        created_at = entry.get("created_at")
        if _timestamp(created_at) is None or created_at in seen:
            continue
        seen.add(created_at)
        feed.append(entry)

    for raw in engine_entries:
        normalized = normalize_engine_entry(raw)
        if not normalized or normalized["created_at"] in seen:
            continue
        seen.add(normalized["created_at"])
        feed.append(normalized)

    feed.sort(key=lambda entry: _timestamp(entry.get("created_at")) or 0, reverse=True)
    return feed[:limit]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/breabinvictor/Desktop/pythonbot && python tests/test_update_feed.py`
Expected: PASS — `18/18 passed`

- [ ] **Step 5: Add the endpoint**

In `core/webserver.py`, add these imports beside the other relative imports near the top:

```python
from .update_feed import merged_update_feed
from .updates import load_update_state
```

If a `from .updates import ...` line already exists, add `load_update_state` to it instead of adding a second line.

Add one row to the `routes` list, directly after the `/stats` row:

```python
            ("GET", "/updates", self.handle_updates),
```

Add the handler immediately after `handle_stats`:

```python
    async def handle_updates(self, request):
        self._rate_limit(request, "read")
        state = load_update_state()
        updates = merged_update_feed(
            limit=request.query.get("limit", 50),
            history=state.get("history"),
            latest=state.get("latest"),
        )
        return web.json_response({"updates": updates, "count": len(updates)})
```

- [ ] **Step 6: Verify the feed assembles and nothing regressed**

Run:
```bash
cd /Users/breabinvictor/Desktop/pythonbot
python -c "
from core.update_feed import merged_update_feed
from core.updates import load_update_state
state = load_update_state()
feed = merged_update_feed(limit=200, history=state.get('history'), latest=state.get('latest'))
print('feed entries:', len(feed))
print('newest build:', feed[0]['build'])
print('keys:', sorted(feed[0].keys()))
"
python tests/test_webserver.py
```
Expected: at least 29 feed entries, and `test_webserver.py` ends with every check passing.

- [ ] **Step 7: Document the endpoint**

In `docs/API.md`, add this section immediately after the `GET /stats` section:

````markdown
### `GET /updates?limit=50`

Public. Newest-first release feed: the frozen Discord archive merged with the
changelog engine's live history, deduplicated by `created_at`. `limit` defaults
to 50 and is clamped to 200.

```json
{ "updates": [ { "build": 16, "version": "3.0.0", "codename": "Nova",
                 "created_at": "2026-07-24T01:28:56+00:00",
                 "highlights": ["..."], "changes": ["..."],
                 "added_lines": 48, "removed_lines": 8, "changed_files": 1 } ],
  "count": 29 }
```

`version`, `codename`, `highlights`, `changes` and the line counts are all
optional; every entry has `build` and `created_at`.
````

- [ ] **Step 8: Commit**

```bash
cd /Users/breabinvictor/Desktop/pythonbot
git add core/update_feed.py core/webserver.py tests/test_update_feed.py docs/API.md
git commit -m "feat(api): serve the public update feed"
```

---

### Task 5: Worker proxy

**Files:**
- Modify: `website-3/worker/index.js` — `isPublicPath` ~line 92, `assetCacheControl` ~line 114, new handler after `handleStatusSnapshot` ~line 182, router ~line 244
- Test: `website-3/worker/index.test.js`

**Interfaces:**
- Consumes: `GET /updates` from Task 4.
- Produces: `GET /api/updates-feed` returning the upstream payload with `Cache-Control: public, max-age=300, stale-while-revalidate=1800`, and public access to `/updates` routes.

- [ ] **Step 1: Write the failing test**

Append to `website-3/worker/index.test.js`:

```js
describe("updates feed", () => {
  it("serves the updates page without a session", async () => {
    const response = await worker.fetch(new Request("https://novaguard.fun/updates"), env);
    expect(response.status).toBe(200);
  });

  it("serves a deeper updates page without a session", async () => {
    const response = await worker.fetch(new Request("https://novaguard.fun/updates/3"), env);
    expect(response.status).toBe(200);
  });

  it("proxies the bot feed and marks it cacheable", async () => {
    const payload = { updates: [{ build: 16, created_at: "2026-07-24T01:28:56+00:00" }], count: 1 };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json(payload)),
    );
    const response = await worker.fetch(
      new Request("https://novaguard.fun/api/updates-feed"),
      env,
      { waitUntil() {} },
    );
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(payload);
    expect(response.headers.get("Cache-Control")).toBe(
      "public, max-age=300, stale-while-revalidate=1800",
    );
  });

  it("answers 502 when the bot is unreachable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("offline");
      }),
    );
    const response = await worker.fetch(
      new Request("https://novaguard.fun/api/updates-feed"),
      env,
      { waitUntil() {} },
    );
    expect(response.status).toBe(502);
    expect((await response.json()).code).toBe("updates_unavailable");
  });

  it("rejects a non-GET request", async () => {
    const response = await worker.fetch(
      new Request("https://novaguard.fun/api/updates-feed", { method: "POST" }),
      env,
      { waitUntil() {} },
    );
    expect(response.status).toBe(405);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/breabinvictor/Desktop/pythonbot/.claude/worktrees/mhc-movie-discovery-ui-797715/website-3 && ./node_modules/.bin/vitest run worker/index.test.js`
Expected: FAIL — the feed request is not routed, and the page redirects instead of returning 200.

- [ ] **Step 3: Write minimal implementation**

In `website-3/worker/index.js`, inside `isPublicPath`, add these two clauses after the `/home` clauses:

```js
    pathname === "/updates" ||
    pathname.startsWith("/updates/") ||
```

Extend the first condition in `assetCacheControl` so the updates pages get the same short revalidating window as the landing page:

```js
  if (
    pathname === "/home" ||
    pathname.startsWith("/home/") ||
    pathname === "/updates" ||
    pathname.startsWith("/updates/")
  ) {
    return "public, max-age=60, stale-while-revalidate=300";
  }
```

Add the handler immediately after `handleStatusSnapshot`:

```js
async function handleUpdatesFeed(request, env, ctx) {
  if (request.method !== "GET") {
    return Response.json(
      { error: "Method not allowed", code: "method_not_allowed" },
      { status: 405, headers: { Allow: "GET" } },
    );
  }

  const url = new URL(request.url);
  const cacheKey = new Request(`${url.origin}/api/updates-feed`);
  const edgeCache = globalThis.caches?.default;
  const cached = edgeCache ? await edgeCache.match(cacheKey) : null;
  if (cached) return cached;

  const apiBase = String(env.STATUS_API_BASE || DEFAULT_STATUS_API_BASE).replace(/\/+$/, "");

  try {
    const upstream = await fetch(`${apiBase}/updates?limit=200`, {
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(3000),
    });
    if (!upstream.ok) throw new Error(`Updates upstream failed: ${upstream.status}`);

    const payload = await upstream.json();
    // Releases land minutes apart at best, so a long window keeps the Pi quiet
    // without the page ever looking stale.
    const response = Response.json(payload, {
      headers: {
        "Cache-Control": "public, max-age=300, stale-while-revalidate=1800",
        "X-Content-Type-Options": "nosniff",
      },
    });

    if (edgeCache && ctx?.waitUntil) {
      ctx.waitUntil(edgeCache.put(cacheKey, response.clone()));
    }
    return response;
  } catch {
    return Response.json(
      { error: "Updates unavailable", code: "updates_unavailable" },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }
}
```

In the `fetch` handler, add the route directly after the status-snapshot line:

```js
    if (url.pathname === "/api/updates-feed") return handleUpdatesFeed(request, env, ctx);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/breabinvictor/Desktop/pythonbot/.claude/worktrees/mhc-movie-discovery-ui-797715/website-3 && ./node_modules/.bin/vitest run worker/index.test.js`
Expected: PASS — the whole worker suite, including the five new tests.

- [ ] **Step 5: Commit**

```bash
cd /Users/breabinvictor/Desktop/pythonbot/.claude/worktrees/mhc-movie-discovery-ui-797715
git add website-3/worker/index.js website-3/worker/index.test.js
git commit -m "feat(worker): proxy and cache the update feed"
```

---

### Task 6: Live merge and navigation

**Files:**
- Modify: `website-3/src/pages/updates/[...page].astro`
- Modify: `website-3/src/components/Nav.astro` — `links` array, line 5
- Modify: `website-3/src/components/Footer.astro` — footer nav, line 20

**Interfaces:**
- Consumes: `/api/updates-feed` from Task 5, `data-newest-baked` from Task 3.
- Produces: page one gains releases newer than the newest baked-in entry; nav and footer link to `/updates`.

- [ ] **Step 1: Add the link to the nav**

In `website-3/src/components/Nav.astro`, replace the `links` array:

```ts
const links = [
  { href: "/commands", label: "Commands" },
  { href: "/updates", label: "Updates" },
  { href: "/status", label: "Status" },
  { href: "/dashboard", label: "Dashboard" },
];
```

- [ ] **Step 2: Add the link to the footer**

In `website-3/src/components/Footer.astro`, add this anchor immediately after the Commands link:

```astro
      <a href="/updates" class="transition-colors hover:text-ink">Updates</a>
```

- [ ] **Step 3: Add the live merge script**

Append this block to `website-3/src/pages/updates/[...page].astro`, after the closing `</Base>` tag:

```astro
<script>
  import { formatReleaseDate, newerThan, type Release } from "../../data/updates";

  // Page one only: page two and beyond render an empty `data-newest-baked`, so
  // the guard below skips them. The cutoff rule itself lives in the data module
  // and is unit-tested there rather than restated here.
  const list = document.querySelector<HTMLElement>("[data-release-list]");
  const newestBaked = list?.dataset.newestBaked ?? "";

  if (list && newestBaked) {
    const escapeHtml = (value: string) =>
      value.replace(/[&<>"]/g, (char) =>
        char === "&" ? "&amp;" : char === "<" ? "&lt;" : char === ">" ? "&gt;" : "&quot;",
      );
    const bullets = (items: string[], tone: string) =>
      items
        .map((item) => `<li class="text-sm leading-relaxed ${tone}">${escapeHtml(item)}</li>`)
        .join("");

    fetch("/api/updates-feed", { headers: { Accept: "application/json" } })
      .then((response) => (response.ok ? response.json() : Promise.reject(response.status)))
      .then((payload: { updates?: Release[] }) => {
        const fresh = newerThan(payload?.updates ?? [], newestBaked);
        if (!fresh.length) return;

        const markup = fresh
          .map((release) => {
            const highlights = release.highlights ?? [];
            const changes = release.changes ?? [];
            const highlightBlock = highlights.length
              ? `<p class="font-mono text-[11px] tracking-[0.14em] text-ink-faint uppercase">Highlights</p><ul class="mt-2 space-y-1.5">${bullets(highlights, "text-ink")}</ul>`
              : "";
            const changeBlock = changes.length
              ? `<p class="font-mono text-[11px] tracking-[0.14em] text-ink-faint uppercase${highlights.length ? " mt-5" : ""}">Changes</p><ul class="mt-2 space-y-1.5">${bullets(changes, "text-ink-muted")}</ul>`
              : "";
            return `<article class="grid gap-4 py-8 sm:grid-cols-[7rem_1fr] sm:gap-8 sm:py-10">
  <div class="sm:text-right">
    <p class="font-mono text-sm text-primary">#${escapeHtml(String(release.build ?? ""))}</p>
    <p class="mt-1 text-xs text-ink-faint sm:mt-2">${escapeHtml(formatReleaseDate(release.created_at))}</p>
  </div>
  <div class="min-w-0">${highlightBlock}${changeBlock}</div>
</article>`;
          })
          .join("");
        list.insertAdjacentHTML("afterbegin", markup);
        // Only reachable when the archive shipped empty and the bot has since
        // recorded a release.
        list.querySelector("[data-empty-note]")?.remove();
      })
      .catch(() => {
        // The page is already correct without the newest entries.
      });
  }
</script>
```

- [ ] **Step 4: Verify the build, the links, and the page-one guard**

Run:
```bash
cd /Users/breabinvictor/Desktop/pythonbot/.claude/worktrees/mhc-movie-discovery-ui-797715/website-3
./node_modules/.bin/astro check && ./node_modules/.bin/astro build
grep -c 'href="/updates"' dist/home/index.html
grep -o 'data-newest-baked="[^"]*"' dist/updates/index.html
grep -c 'data-newest-baked=""' dist/updates/2/index.html
```
Expected: `astro check` 0 errors; at least `2` matches on the landing page (nav + footer); a real timestamp on page one; `1` for the empty attribute on page two, proving the merge is confined to page one.

- [ ] **Step 5: Run the full suite**

Run:
```bash
cd /Users/breabinvictor/Desktop/pythonbot/.claude/worktrees/mhc-movie-discovery-ui-797715/website-3
./node_modules/.bin/vitest run
cd /Users/breabinvictor/Desktop/pythonbot
python tests/test_update_feed.py && python tests/test_backfill_updates.py && python tests/test_webserver.py
```
Expected: every suite passes.

- [ ] **Step 6: Commit**

```bash
cd /Users/breabinvictor/Desktop/pythonbot/.claude/worktrees/mhc-movie-discovery-ui-797715
git add website-3/src/pages/updates/ website-3/src/components/Nav.astro website-3/src/components/Footer.astro
git commit -m "feat(website): link updates and merge live releases on page one"
```

---

## Deployment

The website and the bot ship separately.

- [ ] **Website:** from `website-3`, run `npm run deploy`, then confirm the live page:

```bash
curl -s https://novaguard.fun/updates | grep -c '<article'
```
Expected: `6`.

- [ ] **Bot:** the operator pulls on the Raspberry Pi and restarts pm2. That restart is itself a code change, so the changelog engine will announce it — and that announcement is the first release to reach the site through the new path. Confirm with:

```bash
curl -s https://novaguard.fun/api/updates-feed | head -c 200
```
Expected: JSON beginning `{"updates":[`.

Until the bot is deployed, `/api/updates-feed` answers 502 and the page renders the baked-in archive alone — which is the designed fallback, not a failure.
