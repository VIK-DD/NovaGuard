import { describe, expect, it } from "vitest";
import type { GuildSettings } from "../lib/api/schemas";
import {
  CONFIG_MODULES,
  configModulePath,
  getConfigModule,
  isModuleActive,
} from "./moduleCatalog";

const emptySettings: GuildSettings = {
  welcome_channel: null,
  goodbye_channel: null,
  log_channel: null,
  voice_report_channel: null,
  update_channel: null,
  github_event_channel: null,
  error_log_channel: null,
  ticket_panel_channel: null,
  role_panel_channel: null,
  giveaway_channel: null,
  autorole: null,
  ticket_staff_role: null,
  automod: {
    invites: false,
    spam: false,
    badwords: [],
    ignored_channels: [],
    ignored_roles: [],
    spam_messages: 6,
    spam_window_seconds: 6,
    spam_timeout_seconds: 60,
  },
  levels: {
    enabled: false,
    announce: "dm",
    announce_channel: null,
    xp_min: 5,
    xp_max: 10,
    cooldown: 120,
    ignored_channels: [],
    ignored_roles: [],
  },
  ai: {
    enabled: false,
    answer_mode: "public",
    channel_id: null,
    max_question_chars: 2000,
  },
  economy: {
    enabled: false,
    daily_base: 200,
    daily_streak_bonus: 50,
    work_min: 50,
    work_max: 150,
    work_cooldown_minutes: 60,
    transfers_enabled: true,
    games_enabled: true,
    shop_enabled: true,
    gamble_max_bet: 1_000_000,
    slots_max_bet: 100_000,
  },
  music: {
    enabled: false,
    default_volume: 80,
    max_volume: 100,
    max_queue_tracks: 100,
    allow_playlists: true,
    allow_filters: true,
  },
};

describe("configuration module catalog", () => {
  it("places every configurable setting in exactly one module", () => {
    const fields = CONFIG_MODULES.flatMap((module) => [...module.fields]).sort();
    expect(fields).toEqual(
      [
        "automod",
        "autorole",
        "ai",
        "economy",
        "error_log_channel",
        "github_event_channel",
        "giveaway_channel",
        "goodbye_channel",
        "levels",
        "log_channel",
        "music",
        "role_panel_channel",
        "ticket_staff_role",
        "ticket_panel_channel",
        "update_channel",
        "voice_report_channel",
        "welcome_channel",
      ].sort(),
    );
    expect(new Set(fields).size).toBe(fields.length);
  });

  it("uses unique, stable keys for direct module links", () => {
    const keys = CONFIG_MODULES.map((module) => module.key);
    expect(new Set(keys).size).toBe(keys.length);
    expect(keys).toEqual([
      "welcome",
      "moderation",
      "levels",
      "voice",
      "tickets",
      "roles",
      "giveaways",
      "ai",
      "economy",
      "music",
      "updates",
    ]);
  });

  it("resolves direct module routes without accepting unknown keys", () => {
    expect(getConfigModule("levels")?.label).toBe("Levels");
    expect(getConfigModule("unknown")).toBeUndefined();
    expect(configModulePath("123/unsafe", "levels")).toBe(
      "/dashboard/g/123%2Funsafe/settings/levels",
    );
  });

  it("derives module state from the settings that actually power it", () => {
    expect(CONFIG_MODULES.every((module) => !isModuleActive(emptySettings, module.key))).toBe(true);

    const configured = structuredClone(emptySettings);
    configured.autorole = "123";
    configured.automod.badwords = ["spoiler"];
    configured.levels.enabled = true;
    configured.voice_report_channel = "456";
    configured.ticket_staff_role = "789";
    configured.role_panel_channel = "456";
    configured.giveaway_channel = "456";
    configured.ai.enabled = true;
    configured.economy.enabled = true;
    configured.music.enabled = true;
    configured.github_event_channel = "101";

    expect(CONFIG_MODULES.map((module) => isModuleActive(configured, module.key))).toEqual([
      true,
      true,
      true,
      true,
      true,
      true,
      true,
      true,
      true,
      true,
      true,
    ]);
  });
});
