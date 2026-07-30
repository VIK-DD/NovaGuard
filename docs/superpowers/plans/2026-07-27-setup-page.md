# Setup Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `/setup`, a static reference page that explains NovaGuard's three-step setup and reports a signed-in visitor's own progress, per `docs/superpowers/specs/2026-07-27-setup-page-design.md`.

**Architecture:** A static Astro page (`website-3/src/pages/setup.astro`) built from the bot's own `cogs/setup.py` constants, plus one live element — a progress strip that authenticates against the existing dashboard API (`lib/api/client.ts`, `lib/api/schemas.ts`) exactly like the React dashboard already does, but from a plain `<script>` since this page is not part of the `#app` React island.

**Tech Stack:** Astro 5 (static page), TypeScript, Zod (existing schemas), Python/aiohttp (one additive API field), Vitest.

## Global Constraints

- No emoji anywhere on the page, including the channel table (spec decision 4).
- The page must render and read completely with JavaScript disabled; only the strip is lost (spec: Error handling).
- The strip's copy says "recommended channels", never "required" — matching `RECOMMENDED_KEYS` in `cogs/setup.py:27` and the Discord embed's own language.
- The strip does not persist the selected guild (spec: out of scope).
- This page does not edit configuration — it links to the dashboard for that (spec: out of scope).

**Deviation from the spec, decided during planning, not discovered mid-task:**

The spec promises the strip's denominator matches `setup_score` in `cogs/setup.py:44-50`, which adds a 5th recommended channel (`github_event_channel`) when the bot has GitHub repos configured (`github_config.watch_repos` or `github_config.primary_repo`). That flag is bot-instance config (`core/config.py:74-75`, built from env vars) and today is **not exposed through any API endpoint** — `core/webserver.py`'s `_config_payload` has no field for it. Task 1 adds one additive boolean field, `github_watch_configured`, to `GET /guilds/{id}/config` so the website can actually keep this promise instead of silently hard-coding 4 and drifting from what the bot's own `/setup` embed says.

**Refinement over the spec's literal wording:** spec state 2 ("no manageable guilds") is described against `GET /guilds` returning an empty list. In practice a visitor can manage guilds where NovaGuard isn't installed — same UI state applies (nothing to report on, same invite CTA), so the guild classification counts only `bot_present` guilds, matching the filter `GuildPicker.tsx` already uses (`active = all.filter(g => g.bot_present)`).

---

## File Structure

| File | Responsibility |
| --- | --- |
| `core/webserver.py` | Modify: add `github_watch_configured` to `_config_payload`. |
| `tests/test_webserver.py` | Modify: assert the new field. |
| `website-3/src/lib/api/schemas.ts` | Modify: add `github_watch_configured: z.boolean()` to `GuildConfigSchema`. |
| `website-3/src/data/setup.ts` | New, pure: channel/command reference data, `countRecommended`, `classifyGuilds`. |
| `website-3/src/data/setup.test.ts` | New: unit tests for the two pure functions above. |
| `website-3/src/components/Nav.astro` | Modify: add the `/setup` link. |
| `website-3/src/components/Footer.astro` | Modify: add the `/setup` link. |
| `website-3/src/pages/setup.astro` | New: page shell (steps, channel reference, commands) plus the live strip script. |

---

## Task 1: Expose whether the bot is watching GitHub repos

**Files:**
- Modify: `core/webserver.py:48` (import), `core/webserver.py:989-1018` (`_config_payload`)
- Test: `tests/test_webserver.py`

**Interfaces:**
- Produces: `GET /guilds/{id}/config` response gains `github_watch_configured: bool` at the top level, sibling to `guild`/`settings`/`channels`/`roles`.

- [ ] **Step 1: Write the failing test**

Add near the existing config-GET assertions in `tests/test_webserver.py` (after the `"config GET with session (v1)"` check):

```python
        async with http.get(f"{V1}/guilds/{TEST_GUILD_ID}/config", cookies=cookies) as r:
            data = await r.json()
            await check(
                "config payload exposes github_watch_configured",
                r.status == 200 and isinstance(data.get("github_watch_configured"), bool),
            )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_webserver.py`
Expected: FAIL on `"config payload exposes github_watch_configured"` (the key is missing, so `data.get(...)` is `None`, not a `bool`).

- [ ] **Step 3: Add the import**

In `core/webserver.py`, change:

```python
from .config import BOT_CODENAME, BOT_VERSION
```

to:

```python
from .config import BOT_CODENAME, BOT_VERSION, github_config
```

- [ ] **Step 4: Add the field to `_config_payload`**

In `core/webserver.py`, in `_config_payload` (around line 994), add `github_watch_configured` as a top-level key:

```python
        return {
            "guild": {
                "id": str(guild.id),
                "name": guild.name,
                "icon": str(guild.icon) if guild.icon else None,
                "member_count": guild.member_count,
            },
            # Instance-wide, not per-guild — same value for every guild this bot
            # serves. Exposed here (rather than a new endpoint) so the setup page
            # can read a guild's progress and this flag in one request. Lets the
            # website's recommended-channel count agree with cogs/setup.py's
            # setup_score, which adds a 5th recommended channel under the same
            # condition.
            "github_watch_configured": bool(
                github_config.watch_repos or github_config.primary_repo
            ),
            "settings": {
```

(The rest of the dict — `settings`, `channels`, `roles` — is unchanged.)

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 tests/test_webserver.py`
Expected: `46/46 passed` (one more than before), including `"config payload exposes github_watch_configured"`.

- [ ] **Step 6: Commit**

```bash
git add core/webserver.py tests/test_webserver.py
git commit -m "feat(web): expose whether the bot is watching GitHub repos"
```

---

## Task 2: Data module — channel/command reference and pure strip logic

**Files:**
- Create: `website-3/src/data/setup.ts`
- Test: `website-3/src/data/setup.test.ts`

**Interfaces:**
- Consumes: nothing (pure, standalone — mirrors `src/data/updates.ts`'s style).
- Produces:
  - `RECOMMENDED_CHANNEL_KEYS: readonly string[]` (4 keys)
  - `CHANNEL_REFERENCE: ChannelRefEntry[]` (7 entries, `group: "core" | "community"`)
  - `SETUP_COMMANDS: CommandRefEntry[]` (5 entries)
  - `countRecommended(settings, githubWatchConfigured): RecommendedCount`
  - `classifyGuilds(guilds): GuildSelection`

- [ ] **Step 1: Write the failing tests**

Create `website-3/src/data/setup.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import {
  CHANNEL_REFERENCE,
  RECOMMENDED_CHANNEL_KEYS,
  SETUP_COMMANDS,
  classifyGuilds,
  countRecommended,
} from "./setup";

describe("CHANNEL_REFERENCE", () => {
  it("has all seven channels with no emoji", () => {
    expect(CHANNEL_REFERENCE).toHaveLength(7);
    for (const entry of CHANNEL_REFERENCE) {
      expect(entry.label).not.toMatch(/\p{Extended_Pictographic}/u);
    }
  });

  it("marks exactly the four recommended keys", () => {
    const recommended = CHANNEL_REFERENCE.filter((e) => e.recommended).map((e) => e.key);
    expect(recommended.sort()).toEqual([...RECOMMENDED_CHANNEL_KEYS].sort());
  });

  it("groups core and community channels as cogs/setup.py does", () => {
    const core = CHANNEL_REFERENCE.filter((e) => e.group === "core").map((e) => e.key);
    const community = CHANNEL_REFERENCE.filter((e) => e.group === "community").map((e) => e.key);
    expect(core.sort()).toEqual(
      ["update_channel", "github_event_channel", "error_log_channel", "log_channel"].sort(),
    );
    expect(community.sort()).toEqual(
      ["welcome_channel", "goodbye_channel", "voice_report_channel"].sort(),
    );
  });
});

describe("SETUP_COMMANDS", () => {
  it("lists all five commands with a purpose each", () => {
    expect(SETUP_COMMANDS).toHaveLength(5);
    for (const cmd of SETUP_COMMANDS) {
      expect(cmd.name.length).toBeGreaterThan(0);
      expect(cmd.purpose.length).toBeGreaterThan(0);
    }
  });
});

const settings = (overrides: Record<string, string | null> = {}) => ({
  update_channel: "1",
  error_log_channel: "2",
  log_channel: "3",
  welcome_channel: "4",
  github_event_channel: null,
  ...overrides,
});

describe("countRecommended", () => {
  it("counts all four set, github off", () => {
    expect(countRecommended(settings(), false)).toEqual({
      done: 4,
      total: 4,
      missing: [],
    });
  });

  it("counts none set", () => {
    const empty = settings({
      update_channel: null,
      error_log_channel: null,
      log_channel: null,
      welcome_channel: null,
    });
    const result = countRecommended(empty, false);
    expect(result.done).toBe(0);
    expect(result.total).toBe(4);
    expect(result.missing.sort()).toEqual(
      ["update_channel", "error_log_channel", "log_channel", "welcome_channel"].sort(),
    );
  });

  it("counts some set and names what's missing", () => {
    const partial = settings({ welcome_channel: null });
    const result = countRecommended(partial, false);
    expect(result.done).toBe(3);
    expect(result.total).toBe(4);
    expect(result.missing).toEqual(["welcome_channel"]);
  });

  it("raises the total to five when GitHub watching is configured", () => {
    const withGithub = settings({ github_event_channel: "9" });
    expect(countRecommended(withGithub, true)).toEqual({
      done: 5,
      total: 5,
      missing: [],
    });
  });

  it("counts github_event_channel as missing when watching is on but unset", () => {
    const result = countRecommended(settings(), true);
    expect(result.done).toBe(4);
    expect(result.total).toBe(5);
    expect(result.missing).toEqual(["github_event_channel"]);
  });

  it("ignores github_event_channel when watching is off, even if it's set", () => {
    const result = countRecommended(settings({ github_event_channel: "9" }), false);
    expect(result.done).toBe(4);
    expect(result.total).toBe(4);
  });

  it("treats keys missing from the object the same as keys set to null", () => {
    // Distinct from "counts none set" above, which sets every key to null —
    // this is an object that never had the keys at all, the shape a caller
    // would get from destructuring only a few fields off a larger settings
    // object.
    const result = countRecommended({}, false);
    expect(result.done).toBe(0);
    expect(result.missing.sort()).toEqual(
      ["update_channel", "error_log_channel", "log_channel", "welcome_channel"].sort(),
    );
  });

  // No "malformed payload" case here, unlike the spec's testing section asks
  // for verbatim — deliberately. countRecommended only ever receives a
  // GuildSettings object that already passed GuildConfigSchema's Zod parse
  // (Task 6 calls it as `countRecommended(config.settings, ...)`, after
  // `apiFetch` succeeds). A malformed payload never reaches this function: it
  // makes `apiFetch` throw first, which Task 6's renderProgress catches and
  // treats as a failure — the same "never show a false 0 of n" guarantee the
  // spec asks for, just enforced by the existing schema validation instead of
  // a second, hand-rolled check duplicated in this function.
});

describe("classifyGuilds", () => {
  it("classifies zero bot-present guilds as none", () => {
    expect(classifyGuilds([])).toEqual({ kind: "none" });
    expect(
      classifyGuilds([{ id: "1", name: "Not set up", bot_present: false }]),
    ).toEqual({ kind: "none" });
  });

  it("classifies exactly one bot-present guild as single", () => {
    const guilds = [
      { id: "1", name: "Nova Community", bot_present: true },
      { id: "2", name: "Not set up", bot_present: false },
    ];
    expect(classifyGuilds(guilds)).toEqual({
      kind: "single",
      guild: { id: "1", name: "Nova Community" },
    });
  });

  it("classifies several bot-present guilds as multiple, in the given order", () => {
    const guilds = [
      { id: "1", name: "A", bot_present: true },
      { id: "2", name: "B", bot_present: true },
    ];
    expect(classifyGuilds(guilds)).toEqual({
      kind: "multiple",
      guilds: [
        { id: "1", name: "A" },
        { id: "2", name: "B" },
      ],
    });
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd website-3 && npx vitest run src/data/setup.test.ts`
Expected: FAIL — `Cannot find module './setup'` (the file doesn't exist yet).

- [ ] **Step 3: Write the implementation**

Create `website-3/src/data/setup.ts`:

```typescript
// Reference data for the /setup page, sourced from cogs/setup.py so the page
// and the bot cannot silently drift apart. Two things are duplicated across
// languages on purpose: CHANNEL_KEYS' labels/descriptions (Python can't be
// imported into Astro) and RECOMMENDED_KEYS (same reason). The emoji in the
// Python labels are dropped here — the page shows text labels only.

export interface ChannelRefEntry {
  key: string;
  label: string;
  description: string;
  group: "core" | "community";
  recommended: boolean;
}

// Mirrors cogs/setup.py's CHANNEL_KEYS, in the same order.
export const CHANNEL_REFERENCE: ChannelRefEntry[] = [
  {
    key: "update_channel",
    label: "Bot Updates",
    description: "Automatic code changelog and restart summaries",
    group: "core",
    recommended: true,
  },
  {
    key: "github_event_channel",
    label: "GitHub Feed",
    description: "Push, PR, issue and release activity",
    group: "core",
    recommended: false,
  },
  {
    key: "error_log_channel",
    label: "Admin Errors",
    description: "Serious bot error digest embeds",
    group: "core",
    recommended: true,
  },
  {
    key: "log_channel",
    label: "Server Logs",
    description: "Deleted/edited messages, joins/leaves, bans",
    group: "core",
    recommended: true,
  },
  {
    key: "voice_report_channel",
    label: "Voice Reports",
    description: "Completed voice session attendance and duration reports",
    group: "community",
    recommended: false,
  },
  {
    key: "welcome_channel",
    label: "Welcome",
    description: "New member welcome cards",
    group: "community",
    recommended: true,
  },
  {
    key: "goodbye_channel",
    label: "Goodbye",
    description: "Leave messages",
    group: "community",
    recommended: false,
  },
];

// Mirrors cogs/setup.py's RECOMMENDED_KEYS. github_event_channel is not here —
// it only joins the count when github_watch_configured is true (Task 1).
export const RECOMMENDED_CHANNEL_KEYS = [
  "update_channel",
  "error_log_channel",
  "log_channel",
  "welcome_channel",
] as const;

export interface CommandRefEntry {
  name: string;
  purpose: string;
}

// Descriptions copied verbatim from the app_commands.command() decorators in
// cogs/setup.py, so this list can't quietly say something the bot doesn't.
export const SETUP_COMMANDS: CommandRefEntry[] = [
  { name: "/setup", purpose: "Open the NovaGuard setup dashboard" },
  { name: "/config view", purpose: "View the saved NovaGuard configuration" },
  { name: "/config export", purpose: "Export this server's NovaGuard config as JSON" },
  { name: "/config backup", purpose: "Create a manual backup archive now" },
  { name: "/config reset", purpose: "Reset NovaGuard setup/config for this server" },
];

export interface RecommendedCount {
  done: number;
  total: number;
  missing: string[];
}

/**
 * Mirrors cogs/setup.py's setup_score: four recommended channels, plus a
 * fifth (github_event_channel) only when the bot is configured to watch
 * GitHub repos. `settings` only needs to carry the keys this function reads —
 * callers pass the validated GuildSettings object from the dashboard API.
 */
export function countRecommended(
  settings: Record<string, unknown>,
  githubWatchConfigured: boolean,
): RecommendedCount {
  const keys: string[] = [...RECOMMENDED_CHANNEL_KEYS];
  if (githubWatchConfigured) keys.push("github_event_channel");

  const missing = keys.filter((key) => !settings[key]);
  return { done: keys.length - missing.length, total: keys.length, missing };
}

export type GuildSelection =
  | { kind: "none" }
  | { kind: "single"; guild: { id: string; name: string } }
  | { kind: "multiple"; guilds: { id: string; name: string }[] };

/**
 * A guild the visitor manages but NovaGuard hasn't joined has no config to
 * report on — same as an empty list. Mirrors the bot_present filter
 * GuildPicker.tsx already applies for the same reason.
 */
export function classifyGuilds(
  guilds: { id: string; name: string; bot_present: boolean }[],
): GuildSelection {
  const present = guilds.filter((g) => g.bot_present).map((g) => ({ id: g.id, name: g.name }));
  if (present.length === 0) return { kind: "none" };
  if (present.length === 1) return { kind: "single", guild: present[0] };
  return { kind: "multiple", guilds: present };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd website-3 && npx vitest run src/data/setup.test.ts`
Expected: all tests pass (14 tests across the four `describe` blocks).

- [ ] **Step 5: Commit**

```bash
git add website-3/src/data/setup.ts website-3/src/data/setup.test.ts
git commit -m "feat(web): pure reference data and logic for the /setup page"
```

---

## Task 3: Add the new field to the website's Zod schema

**Files:**
- Modify: `website-3/src/lib/api/schemas.ts`

**Interfaces:**
- Consumes: nothing new.
- Produces: `GuildConfigSchema` (and its inferred `GuildConfig` type) gains `github_watch_configured: boolean`.

- [ ] **Step 1: Add the field**

In `website-3/src/lib/api/schemas.ts`, find:

```typescript
export const GuildConfigSchema = z.object({
  guild: z.object({
```

and change it to:

```typescript
export const GuildConfigSchema = z.object({
  // Instance-wide (same for every guild), not a per-guild setting — see
  // core/webserver.py's _config_payload. Used only to size the /setup page's
  // recommended-channel count the same way cogs/setup.py's setup_score does.
  github_watch_configured: z.boolean(),
  guild: z.object({
```

- [ ] **Step 2: Verify the existing test fixtures still satisfy the schema**

Run: `cd website-3 && npx vitest run`
Expected: any test that builds a mock `GuildConfig`-shaped object without `github_watch_configured` now fails Zod parsing. Check `src/app/screens/GuildConfig.tsx`'s consumer isn't asserting the full shape by hand (it isn't — it reads `config.data.settings` etc., not a hand-built fixture), and check `src/lib/api/mock.ts`'s `route()` handler for `/guilds/:id/config` — it likely spreads a stored `Settings` object into a response literal that needs the new key too.

Run: `grep -n "github_watch_configured\|settings," website-3/src/lib/api/mock.ts`

If `mock.ts`'s config-GET response builder doesn't include `github_watch_configured`, add it there so local dev (`PUBLIC_MOCK_API=1`) keeps working — find the object literal returned for `GET /guilds/:id/config` and add `github_watch_configured: false,` alongside `guild`/`settings`/`channels`/`roles`.

- [ ] **Step 3: Run the full test suite and typecheck**

Run: `cd website-3 && npm test && npx tsc --noEmit`
Expected: all tests pass, no type errors.

- [ ] **Step 4: Commit**

```bash
git add website-3/src/lib/api/schemas.ts website-3/src/lib/api/mock.ts
git commit -m "feat(web): add github_watch_configured to the config schema"
```

---

## Task 4: Link `/setup` from the nav and footer

**Files:**
- Modify: `website-3/src/components/Nav.astro:5-10` (`links` array)
- Modify: `website-3/src/components/Footer.astro:20-26` (footer nav)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing other components depend on — pure UI wiring.

- [ ] **Step 1: Add the link to Nav.astro**

In `website-3/src/components/Nav.astro`, change:

```astro
const links = [
  { href: "/commands", label: "Commands" },
  { href: "/updates", label: "Updates" },
  { href: "/status", label: "Status" },
  { href: "/dashboard", label: "Dashboard" },
];
```

to:

```astro
const links = [
  { href: "/commands", label: "Commands" },
  { href: "/setup", label: "Setup" },
  { href: "/updates", label: "Updates" },
  { href: "/status", label: "Status" },
  { href: "/dashboard", label: "Dashboard" },
];
```

- [ ] **Step 2: Add the link to Footer.astro**

In `website-3/src/components/Footer.astro`, change:

```astro
      <a href="/commands" class="transition-colors hover:text-ink">Commands</a>
      <a href="/updates" class="transition-colors hover:text-ink">Updates</a>
```

to:

```astro
      <a href="/commands" class="transition-colors hover:text-ink">Commands</a>
      <a href="/setup" class="transition-colors hover:text-ink">Setup</a>
      <a href="/updates" class="transition-colors hover:text-ink">Updates</a>
```

- [ ] **Step 3: Verify by eye**

Run: `cd website-3 && npm run dev` (if not already running), open `http://localhost:4321/commands` (any page using `<Nav />`/`<Footer />`), confirm "Setup" appears between "Commands" and "Updates" in both the header (desktop width) and the footer.

This step has no automated assertion — Task 7 verifies `/setup` itself renders; this step only confirms the link text/position, which is easier to eyeball than to script for two links.

- [ ] **Step 4: Commit**

```bash
git add website-3/src/components/Nav.astro website-3/src/components/Footer.astro
git commit -m "feat(web): link /setup from the nav and footer"
```

---

## Task 5: The `/setup` page shell — static content

**Files:**
- Create: `website-3/src/pages/setup.astro`

**Interfaces:**
- Consumes: `CHANNEL_REFERENCE`, `SETUP_COMMANDS` from `../data/setup` (Task 2).
- Produces: nothing later tasks import — Task 6 edits this same file to add the live script.

This task builds everything except the live strip: the three numbered steps, the channel reference, and the commands list. The strip's container renders empty (Task 6 fills it via script) so the page is complete with JavaScript disabled, per the spec's error-handling requirement.

- [ ] **Step 1: Create the page**

Create `website-3/src/pages/setup.astro`:

```astro
---
import Base from "../layouts/Base.astro";
import Nav from "../components/Nav.astro";
import Footer from "../components/Footer.astro";
import { CHANNEL_REFERENCE, SETUP_COMMANDS } from "../data/setup";

const coreChannels = CHANNEL_REFERENCE.filter((c) => c.group === "core");
const communityChannels = CHANNEL_REFERENCE.filter((c) => c.group === "community");

const steps = [
  {
    title: "Invite NovaGuard",
    body: "Add the bot to your server with the button below. No setup happens yet — this only gets it in the door.",
  },
  {
    title: "Open /setup in Discord",
    body: "Run the command, then pick a channel from the dropdown or press a quick button — Updates, GitHub, Admin Errors, Server Logs, Welcome, Goodbye. Every channel is optional.",
  },
  {
    title: "Press Mark Complete",
    body: "This only sets a status flag on the setup embed — NovaGuard already works with none, some, or all channels set.",
  },
];
---

<Base
  title="Setup — NovaGuard"
  description="How to configure NovaGuard: three steps, and a reference for every channel and command."
>
  <Nav />
  <main class="mx-auto max-w-5xl px-5 py-12 sm:px-6 sm:py-20">
    <p class="font-mono text-xs tracking-[0.14em] text-primary uppercase">Setup</p>
    <h1 class="font-display mt-4 max-w-2xl text-3xl leading-tight sm:text-5xl">
      Three steps. Nothing required.
    </h1>
    <p class="mt-4 max-w-md text-ink-muted">
      Every channel below is optional — NovaGuard runs with none, some, or all of them set.
    </p>

    <div data-setup-strip class="mt-8"></div>

    <section class="mt-16">
      <dl class="divide-y divide-line border-t border-line">
        {
          steps.map((step, i) => (
            <div class="grid gap-2 py-6 sm:grid-cols-[3rem_1fr] sm:items-baseline sm:gap-6">
              <dt class="font-mono text-xs text-ink-faint">{String(i + 1).padStart(2, "0")}</dt>
              <div>
                <p class="font-display text-lg font-semibold">{step.title}</p>
                <p class="mt-1.5 max-w-lg text-sm leading-relaxed text-ink-muted">{step.body}</p>
                {i === 0 && (
                  <a
                    href="/dashboard"
                    data-invite
                    class="ng-pressable mt-4 inline-flex h-11 items-center justify-center rounded-[6px] bg-primary px-4 text-sm font-medium text-primary-ink transition-colors hover:bg-primary/90"
                  >
                    Add to Discord
                  </a>
                )}
              </div>
            </div>
          ))
        }
      </dl>
    </section>

    <section class="mt-16">
      <p class="text-xs tracking-[0.25em] text-ink-muted uppercase">Channel reference</p>
      <h2 class="font-display mt-3 text-2xl">Every channel NovaGuard can use.</h2>

      <p class="mt-8 text-xs tracking-[0.2em] text-primary uppercase">Core</p>
      <div class="mt-3 divide-y divide-line border-t border-line">
        {
          coreChannels.map((c) => (
            <div class="grid gap-1 py-4 sm:grid-cols-[14rem_1fr] sm:gap-6">
              <p class="text-sm font-medium">
                {c.label}
                {c.recommended && <span class="ml-2 text-xs text-primary">Recommended</span>}
              </p>
              <p class="text-sm text-ink-muted">{c.description}</p>
            </div>
          ))
        }
      </div>

      <p class="mt-10 text-xs tracking-[0.2em] text-primary uppercase">Community</p>
      <div class="mt-3 divide-y divide-line border-t border-line">
        {
          communityChannels.map((c) => (
            <div class="grid gap-1 py-4 sm:grid-cols-[14rem_1fr] sm:gap-6">
              <p class="text-sm font-medium">
                {c.label}
                {c.recommended && <span class="ml-2 text-xs text-primary">Recommended</span>}
              </p>
              <p class="text-sm text-ink-muted">{c.description}</p>
            </div>
          ))
        }
      </div>
    </section>

    <section class="mt-16">
      <p class="text-xs tracking-[0.25em] text-ink-muted uppercase">Commands</p>
      <div class="mt-3 divide-y divide-line border-t border-line">
        {
          SETUP_COMMANDS.map((cmd) => (
            <div class="grid gap-1 py-4 sm:grid-cols-[14rem_1fr] sm:gap-6">
              <code class="font-mono text-sm">{cmd.name}</code>
              <p class="text-sm text-ink-muted">{cmd.purpose}</p>
            </div>
          ))
        }
      </div>
    </section>
  </main>
  <Footer />
</Base>
```

- [ ] **Step 2: Verify it builds**

Run: `cd website-3 && npm run build`
Expected: build succeeds, `dist/setup/index.html` exists.

- [ ] **Step 3: Verify the static content by hand**

Run: `grep -o "Recommended" website-3/dist/setup/index.html | wc -l`
(`grep -c` counts matching *lines*, not occurrences — Astro's build minifies the page to one line, so `-c` would report `1` regardless of how many badges are actually present. Discovered during Task 5's implementation.)
Expected: `4` (one badge per recommended channel — matches `RECOMMENDED_CHANNEL_KEYS.length`).

Run: `grep -o '/config view\|/config export\|/config backup\|/config reset\|>/setup<' website-3/dist/setup/index.html | sort -u | wc -l`
Expected: `5`.

- [ ] **Step 4: Commit**

```bash
git add website-3/src/pages/setup.astro
git commit -m "feat(web): add the /setup page shell (steps, channels, commands)"
```

---

## Task 6: The live progress strip

**Files:**
- Modify: `website-3/src/pages/setup.astro` (add a `<script>` block)

**Interfaces:**
- Consumes:
  - `apiFetch<T>(path, schema, init?)`, `ApiError`, `inviteUrl()` from `../lib/api/client`
  - `GuildsSchema`, `GuildConfigSchema` from `../lib/api/schemas`
  - `countRecommended`, `classifyGuilds` from `../data/setup` (Task 2)
- Produces: nothing later tasks import.

- [ ] **Step 1: Add the script**

At the end of `website-3/src/pages/setup.astro` (after `</Base>`), add:

```astro
<script>
  import { ApiError, apiFetch, inviteUrl } from "../lib/api/client";
  import { GuildConfigSchema, GuildsSchema, type Guild } from "../lib/api/schemas";
  import { classifyGuilds, countRecommended } from "../data/setup";

  const container = document.querySelector<HTMLElement>("[data-setup-strip]");
  if (container) void init(container);

  async function init(el: HTMLElement) {
    let guilds: Guild[];
    try {
      guilds = (await apiFetch("/guilds", GuildsSchema)).guilds;
    } catch (err) {
      if (err instanceof ApiError && (err.code === "unauthorized" || err.code === "session_expired")) {
        renderNotConnected(el);
      }
      // Any other failure (network, bot_starting, upstream_unavailable) leaves
      // the strip empty — the page is already complete without it.
      return;
    }

    const selection = classifyGuilds(guilds);
    if (selection.kind === "none") {
      renderNoGuilds(el);
      return;
    }

    renderLoading(el);

    if (selection.kind === "single") {
      await renderProgress(el, selection.guild);
      return;
    }

    renderSelector(el, selection.guilds, (guild) => renderProgress(el, guild));
  }

  function renderNotConnected(el: HTMLElement) {
    el.innerHTML = `<p class="text-sm text-ink-muted">Connect your Discord account to see your setup progress here. <a href="/dashboard" class="text-primary underline underline-offset-4">Open the dashboard</a></p>`;
  }

  function renderNoGuilds(el: HTMLElement) {
    el.innerHTML = `<p class="text-sm text-ink-muted">No server to report on yet. <a href="${escapeHtml(inviteUrl())}" class="text-primary underline underline-offset-4">Add NovaGuard to a server</a></p>`;
  }

  function renderLoading(el: HTMLElement) {
    el.innerHTML = `<div class="h-5 w-64 animate-pulse rounded bg-line/60" aria-busy="true"></div>`;
  }

  function renderSelector(
    el: HTMLElement,
    guilds: { id: string; name: string }[],
    onPick: (guild: { id: string; name: string }) => void,
  ) {
    const options = guilds
      .map((g) => `<option value="${escapeHtml(g.id)}">${escapeHtml(g.name)}</option>`)
      .join("");
    el.innerHTML = `
      <div class="flex flex-wrap items-center gap-3">
        <label class="text-sm text-ink-muted">
          Show progress for
          <select data-setup-guild-select class="ml-2 rounded-md border border-line bg-card px-2 py-1 text-sm text-ink outline-none focus:border-ink">
            ${options}
          </select>
        </label>
        <span data-setup-progress-slot></span>
      </div>`;

    const select = el.querySelector<HTMLSelectElement>("[data-setup-guild-select]")!;
    const slot = el.querySelector<HTMLElement>("[data-setup-progress-slot]")!;
    const pick = () => {
      const guild = guilds.find((g) => g.id === select.value);
      if (guild) {
        slot.innerHTML = `<span class="inline-block h-4 w-40 animate-pulse rounded bg-line/60" aria-busy="true"></span>`;
        onPick(guild);
      }
    };
    select.addEventListener("change", pick);
    pick();

    // renderProgress below targets `el` directly, which would blow away the
    // selector itself. Route single/repeat picks through the slot instead.
    (el as HTMLElement).dataset.setupHasSelector = "true";
  }

  async function renderProgress(el: HTMLElement, guild: { id: string; name: string }) {
    const target = el.querySelector<HTMLElement>("[data-setup-progress-slot]") ?? el;
    try {
      const config = await apiFetch(`/guilds/${guild.id}/config`, GuildConfigSchema);
      const { done, total, missing } = countRecommended(
        config.settings,
        config.github_watch_configured,
      );
      const missingLabel = missing.length
        ? ` — missing ${missing.map((key) => escapeHtml(labelFor(key))).join(", ")}`
        : "";
      target.innerHTML = `<span class="text-sm text-ink">${done} of ${total} recommended channels set${missingLabel}. <a href="/dashboard/g/${escapeHtml(guild.id)}" class="text-primary underline underline-offset-4">Open ${escapeHtml(guild.name)} in the dashboard</a></span>`;
    } catch {
      // A guild-config failure (deleted guild, bot removed mid-session, a
      // malformed payload Zod rejects) is indistinguishable from "nothing
      // configured" only if we let it be — treat it as a failure instead of
      // reporting a false "0 of n".
      if (el.dataset.setupHasSelector === "true") {
        target.innerHTML = "";
      } else {
        el.innerHTML = "";
      }
    }
  }

  function labelFor(key: string): string {
    const known: Record<string, string> = {
      update_channel: "Bot Updates",
      error_log_channel: "Admin Errors",
      log_channel: "Server Logs",
      welcome_channel: "Welcome",
      github_event_channel: "GitHub Feed",
    };
    return known[key] ?? key;
  }

  function escapeHtml(value: string): string {
    return value.replace(/[&<>"]/g, (char) =>
      char === "&" ? "&amp;" : char === "<" ? "&lt;" : char === ">" ? "&gt;" : "&quot;",
    );
  }
</script>
```

- [ ] **Step 2: Verify it typechecks**

Run: `cd website-3 && npx tsc --noEmit`
Expected: no errors. (Astro hoists all module `<script>`s and type-checks them as part of `astro check`, which `tsc --noEmit` alone does not run against `.astro` files — also run `npx astro check` to be sure this specific script block is covered.)

Run: `cd website-3 && npx astro check`
Expected: `0 errors`.

- [ ] **Step 3: Manual verification against the mock API**

This needs `PUBLIC_MOCK_API=1` (see `website-3/README.md` / the gitignored `.env` pattern already used elsewhere in this repo) and the dev server running.

Run: `cd website-3 && npm run dev`, open `http://localhost:4321/setup` in a browser with `sessionStorage.setItem("ng_mock_session", "on")` set (same trick used to preview the dashboard locally — see `AuthGate.tsx`'s dev-only "Preview with demo data" button, or click that button from `/dashboard` first, then navigate to `/setup`).

Expected: the strip shows "N of 4 recommended channels set" (or 5, for the mock guild with GitHub event channel data, once `mock.ts` is updated in Task 3 to include `github_watch_configured`) for whichever guild the mock session resolves to, with a working link into `/dashboard/g/<id>`.

- [ ] **Step 4: Commit**

```bash
git add website-3/src/pages/setup.astro
git commit -m "feat(web): add the live progress strip to /setup"
```

---

## Task 7: Full verification pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full website test suite**

Run: `cd website-3 && npm test`
Expected: all suites pass, including the 14 new tests from Task 2.

- [ ] **Step 2: Typecheck and build**

Run: `cd website-3 && npx astro check && npm run build`
Expected: no errors; build completes; `dist/setup/index.html` exists.

- [ ] **Step 3: Confirm the invite anchor carries `data-invite`**

Run: `grep -c 'data-invite' website-3/dist/setup/index.html`
Expected: `1` or more (the spec's testing section requires this be verifiable — `Base.astro`'s inline script rewrites every `[data-invite]` anchor's `href` to the live invite URL at runtime).

- [ ] **Step 4: Run the full Python test suite**

Run: `cd .. && for t in tests/test_*.py; do python3 "$t" > /tmp/out.txt 2>&1; [ $? -ne 0 ] && echo "FAIL: $t" && cat /tmp/out.txt; done; echo done`
Expected: only `done` printed — no `FAIL` lines.

- [ ] **Step 5: Report status**

At this point `/setup` is fully implemented and locally verified. It is **not yet deployed** — deploying the bot side (Task 1's `core/webserver.py` change) needs `git pull` + `pm2 restart pythonbot` on the Pi, and the website side needs `npm run deploy` from `website-3`. Deploy the bot change first: the website's Zod schema now requires `github_watch_configured` in the config response, so a newer website against an older bot would fail to parse `GET /guilds/{id}/config` entirely.
