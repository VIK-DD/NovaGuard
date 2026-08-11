import { describe, expect, it } from "vitest";
import type { GuildSettings } from "../../lib/api/schemas";
import {
  diffSettings,
  isDirty,
  mapValidationDetails,
  normalizeBadwords,
  validateSettings,
} from "./configForm";

const base: GuildSettings = {
  welcome_channel: "100",
  goodbye_channel: null,
  log_channel: "200",
  voice_report_channel: null,
  update_channel: null,
  github_event_channel: null,
  error_log_channel: null,
  ticket_panel_channel: null,
  autorole: "300",
  ticket_staff_role: null,
  automod: {
    invites: true,
    spam: false,
    badwords: ["alpha", "beta"],
    ignored_channels: ["401"],
    ignored_roles: [],
    spam_messages: 6,
    spam_window_seconds: 6,
    spam_timeout_seconds: 60,
  },
  levels: {
    enabled: true,
    announce: "dm",
    announce_channel: null,
    xp_min: 5,
    xp_max: 10,
    cooldown: 120,
    ignored_channels: ["400"],
    ignored_roles: [],
  },
};

const clone = (): GuildSettings => structuredClone(base);

describe("mapValidationDetails for levels", () => {
  it("pairs each levels error with its own field", () => {
    expect(
      mapValidationDetails([
        "levels.xp_min: cannot be greater than xp_max",
        "levels.cooldown: must be a whole number between 0 and 3600",
      ]),
    ).toEqual({
      "levels.xp_min": "levels.xp_min: cannot be greater than xp_max",
      "levels.cooldown": "levels.cooldown: must be a whole number between 0 and 3600",
    });
  });

  it("does not mistake announce_channel for announce", () => {
    // Both keys share a prefix, so a plain substring match would light up the
    // mode select instead of the channel picker.
    const map = mapValidationDetails([
      "levels.announce_channel: required when announcing in a channel",
    ]);
    expect(Object.keys(map)).toEqual(["levels.announce_channel"]);
  });

  it("keeps levels errors away from the channel fields above", () => {
    const map = mapValidationDetails(["levels.ignored_channels: at most 50 entries"]);
    expect(map).toHaveProperty("levels.ignored_channels");
    expect(map).not.toHaveProperty("log_channel");
  });
});

describe("diffSettings", () => {
  it("returns only the changed keys", () => {
    const draft = clone();
    draft.welcome_channel = "999";
    expect(diffSettings(base, draft)).toEqual({ welcome_channel: "999" });
  });

  it("clears channels with null, never empty string", () => {
    const draft = clone();
    draft.welcome_channel = null;
    expect(diffSettings(base, draft)).toEqual({ welcome_channel: null });
  });

  it("sends only the toggled levels field", () => {
    const draft = clone();
    draft.levels.enabled = false;
    expect(diffSettings(base, draft)).toEqual({ levels: { enabled: false } });
  });

  it("carries both sides of the XP range whenever either moves", () => {
    // The server checks xp_min against xp_max on the merged result. Sending
    // xp_min alone would have it judged against the stored xp_max.
    const draft = clone();
    draft.levels.xp_min = 8;
    expect(diffSettings(base, draft)).toEqual({ levels: { xp_min: 8, xp_max: 10 } });
  });

  it("leaves the XP range alone when only the cooldown moves", () => {
    const draft = clone();
    draft.levels.cooldown = 30;
    expect(diffSettings(base, draft)).toEqual({ levels: { cooldown: 30 } });
  });

  it("ignores reordering of an ignore list", () => {
    const draft = clone();
    draft.levels.ignored_channels = ["400"];
    draft.levels.ignored_roles = [];
    expect(diffSettings(base, draft)).toEqual({});
  });

  it("sends an emptied ignore list", () => {
    const draft = clone();
    draft.levels.ignored_channels = [];
    expect(diffSettings(base, draft)).toEqual({ levels: { ignored_channels: [] } });
  });

  it("sends only the toggled automod field", () => {
    const draft = clone();
    draft.automod.invites = false;
    expect(diffSettings(base, draft)).toEqual({ automod: { invites: false } });
  });

  it("treats reordered badwords as unchanged (set equality)", () => {
    const draft = clone();
    draft.automod.badwords = ["beta", "alpha"];
    expect(diffSettings(base, draft)).toEqual({});
    expect(isDirty(base, draft)).toBe(false);
  });

  it("includes badwords when membership actually changes", () => {
    const draft = clone();
    draft.automod.badwords = ["alpha", "gamma"];
    expect(diffSettings(base, draft)).toEqual({
      automod: { badwords: ["alpha", "gamma"] },
    });
  });

  it("sends advanced AutoMod fields without unrelated settings", () => {
    const draft = clone();
    draft.automod.spam_messages = 8;
    draft.automod.ignored_roles = ["900"];
    expect(diffSettings(base, draft)).toEqual({
      automod: { spam_messages: 8, ignored_roles: ["900"] },
    });
  });
});

describe("isDirty", () => {
  it("is false for an identical draft and true after an edit", () => {
    const draft = clone();
    expect(isDirty(base, draft)).toBe(false);
    draft.autorole = null;
    expect(isDirty(base, draft)).toBe(true);
  });
});

describe("normalizeBadwords", () => {
  it("lowercases, trims, dedupes, drops empty entries and truncates long ones", () => {
    const long = "x".repeat(41);
    expect(normalizeBadwords([" Spoiler ", "spoiler", long, ""])).toEqual([
      "spoiler",
      "x".repeat(40),
    ]);
  });

  it("caps the list at 100 entries", () => {
    const raw = Array.from({ length: 150 }, (_, i) => `word${i}`);
    expect(normalizeBadwords(raw)).toHaveLength(100);
  });
});

describe("validateSettings", () => {
  it("accepts a valid settings draft", () => {
    expect(validateSettings(clone())).toEqual({});
  });

  it("catches an inverted XP range before the request is sent", () => {
    const draft = clone();
    draft.levels.xp_min = 20;
    draft.levels.xp_max = 10;
    expect(validateSettings(draft)).toHaveProperty(
      "levels.xp_min",
      "XP minimum cannot be greater than XP maximum.",
    );
  });

  it("requires a channel when channel announcements are selected", () => {
    const draft = clone();
    draft.levels.announce = "channel";
    draft.levels.announce_channel = null;
    expect(validateSettings(draft)).toHaveProperty("levels.announce_channel");
  });

  it("validates numeric bounds and ignore-list limits", () => {
    const draft = clone();
    draft.levels.xp_max = 101;
    draft.levels.cooldown = -1;
    draft.levels.ignored_channels = Array.from({ length: 51 }, (_, i) => String(i));
    const errors = validateSettings(draft);
    expect(errors).toHaveProperty("levels.xp_max");
    expect(errors).toHaveProperty("levels.cooldown");
    expect(errors).toHaveProperty("levels.ignored_channels");
  });

  it("validates AutoMod thresholds and exemption limits", () => {
    const draft = clone();
    draft.automod.spam_messages = 2;
    draft.automod.spam_window_seconds = 61;
    draft.automod.spam_timeout_seconds = 0;
    draft.automod.ignored_roles = Array.from({ length: 51 }, (_, i) => String(i));
    const errors = validateSettings(draft);
    expect(errors).toHaveProperty("automod.spam_messages");
    expect(errors).toHaveProperty("automod.spam_window_seconds");
    expect(errors).toHaveProperty("automod.spam_timeout_seconds");
    expect(errors).toHaveProperty("automod.ignored_roles");
  });
});

describe("mapValidationDetails", () => {
  it("keys messages by the settings field they mention", () => {
    expect(mapValidationDetails(["welcome_channel: not a text channel"])).toEqual({
      welcome_channel: "welcome_channel: not a text channel",
    });
  });

  it("collects unmatched messages under _global and handles undefined", () => {
    expect(mapValidationDetails(["something odd happened"])).toEqual({
      _global: "something odd happened",
    });
    expect(mapValidationDetails(undefined)).toEqual({});
  });
});
