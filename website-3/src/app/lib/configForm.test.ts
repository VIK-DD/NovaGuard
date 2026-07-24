import { describe, expect, it } from "vitest";
import type { GuildSettings } from "../../lib/api/schemas";
import {
  diffSettings,
  isDirty,
  mapValidationDetails,
  normalizeBadwords,
} from "./configForm";

const base: GuildSettings = {
  welcome_channel: "100",
  goodbye_channel: null,
  log_channel: "200",
  voice_report_channel: null,
  update_channel: null,
  github_event_channel: null,
  error_log_channel: null,
  autorole: "300",
  ticket_staff_role: null,
  automod: { invites: true, spam: false, badwords: ["alpha", "beta"] },
};

const clone = (): GuildSettings => structuredClone(base);

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
  it("lowercases, trims, dedupes, drops empty and overlong entries", () => {
    const long = "x".repeat(41);
    expect(normalizeBadwords([" Spoiler ", "spoiler", long, ""])).toEqual(["spoiler"]);
  });

  it("caps the list at 100 entries", () => {
    const raw = Array.from({ length: 150 }, (_, i) => `word${i}`);
    expect(normalizeBadwords(raw)).toHaveLength(100);
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
