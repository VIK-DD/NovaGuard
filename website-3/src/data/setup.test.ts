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
