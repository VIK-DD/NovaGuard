// Pure form logic for the guild config editor — no React in here.
import type { GuildSettings, SettingsPatch } from "../../lib/api/schemas";

const ID_KEYS = [
  "welcome_channel",
  "goodbye_channel",
  "log_channel",
  "voice_report_channel",
  "update_channel",
  "github_event_channel",
  "error_log_channel",
  "ticket_panel_channel",
  "role_panel_channel",
  "giveaway_channel",
  "autorole",
  "ticket_staff_role",
] as const;

const LEVELS_SCALAR_KEYS = [
  "enabled",
  "announce",
  "announce_channel",
  "xp_min",
  "xp_max",
  "cooldown",
] as const;

const LEVELS_LIST_KEYS = ["ignored_channels", "ignored_roles"] as const;

const AUTOMOD_SCALAR_KEYS = [
  "invites",
  "spam",
  "spam_messages",
  "spam_window_seconds",
  "spam_timeout_seconds",
] as const;

const AUTOMOD_LIST_KEYS = ["badwords", "ignored_channels", "ignored_roles"] as const;
const AI_KEYS = ["enabled", "answer_mode", "channel_id", "max_question_chars"] as const;
const ECONOMY_KEYS = [
  "enabled",
  "daily_base",
  "daily_streak_bonus",
  "work_min",
  "work_max",
  "work_cooldown_minutes",
  "transfers_enabled",
  "games_enabled",
  "shop_enabled",
  "gamble_max_bet",
  "slots_max_bet",
] as const;
const MUSIC_KEYS = [
  "enabled",
  "default_volume",
  "max_volume",
  "max_queue_tracks",
  "allow_playlists",
  "allow_filters",
] as const;

/** Mirrors the server's badwords rules: lowercase, trim, dedupe, truncate to 40 chars, ≤100 words. */
export function normalizeBadwords(raw: string[]): string[] {
  const out: string[] = [];
  for (const word of raw) {
    const w = word.trim().toLowerCase().slice(0, 40);
    if (!w || out.includes(w)) continue;
    out.push(w);
    if (out.length === 100) break;
  }
  return out;
}

/** Client-side mirror of the cross-field Levels rules enforced by the API. */
export function validateSettings(draft: GuildSettings): Record<string, string> {
  const errors: Record<string, string> = {};
  const { ai, automod, economy, levels, music } = draft;

  const wholeNumber = (value: number, min: number, max: number) =>
    Number.isInteger(value) && value >= min && value <= max;

  if (!wholeNumber(levels.xp_min, 1, 100)) {
    errors["levels.xp_min"] = "Enter a whole number between 1 and 100.";
  }
  if (!wholeNumber(levels.xp_max, 1, 100)) {
    errors["levels.xp_max"] = "Enter a whole number between 1 and 100.";
  }
  if (
    !errors["levels.xp_min"] &&
    !errors["levels.xp_max"] &&
    levels.xp_min > levels.xp_max
  ) {
    errors["levels.xp_min"] = "XP minimum cannot be greater than XP maximum.";
  }
  if (!wholeNumber(levels.cooldown, 0, 3600)) {
    errors["levels.cooldown"] = "Enter a whole number between 0 and 3600.";
  }
  if (levels.announce === "channel" && !levels.announce_channel) {
    errors["levels.announce_channel"] = "Choose a channel for level-up announcements.";
  }
  if (levels.ignored_channels.length > 50) {
    errors["levels.ignored_channels"] = "You can ignore at most 50 channels.";
  }
  if (levels.ignored_roles.length > 50) {
    errors["levels.ignored_roles"] = "You can ignore at most 50 roles.";
  }
  if (!wholeNumber(automod.spam_messages, 3, 20)) {
    errors["automod.spam_messages"] = "Enter a whole number between 3 and 20.";
  }
  if (!wholeNumber(automod.spam_window_seconds, 2, 60)) {
    errors["automod.spam_window_seconds"] = "Enter a whole number between 2 and 60.";
  }
  if (!wholeNumber(automod.spam_timeout_seconds, 10, 86400)) {
    errors["automod.spam_timeout_seconds"] = "Enter a whole number between 10 and 86400.";
  }
  if (automod.ignored_channels.length > 50) {
    errors["automod.ignored_channels"] = "You can exempt at most 50 channels.";
  }
  if (automod.ignored_roles.length > 50) {
    errors["automod.ignored_roles"] = "You can exempt at most 50 roles.";
  }
  if (!wholeNumber(ai.max_question_chars, 100, 2000)) {
    errors["ai.max_question_chars"] = "Enter a whole number between 100 and 2000.";
  }
  const economyRanges = {
    daily_base: [0, 100_000],
    daily_streak_bonus: [0, 10_000],
    work_min: [0, 100_000],
    work_max: [0, 100_000],
    work_cooldown_minutes: [1, 1440],
    gamble_max_bet: [10, 1_000_000],
    slots_max_bet: [10, 100_000],
  } as const;
  for (const [key, [minimum, maximum]] of Object.entries(economyRanges)) {
    const value = economy[key as keyof typeof economyRanges];
    if (!wholeNumber(value, minimum, maximum)) {
      errors[`economy.${key}`] = `Enter a whole number between ${minimum} and ${maximum}.`;
    }
  }
  if (!errors["economy.work_min"] && !errors["economy.work_max"] && economy.work_min > economy.work_max) {
    errors["economy.work_min"] = "Work minimum cannot be greater than work maximum.";
  }
  if (!wholeNumber(music.default_volume, 0, 100)) {
    errors["music.default_volume"] = "Enter a whole number between 0 and 100.";
  }
  if (!wholeNumber(music.max_volume, 10, 100)) {
    errors["music.max_volume"] = "Enter a whole number between 10 and 100.";
  }
  if (
    !errors["music.default_volume"] &&
    !errors["music.max_volume"] &&
    music.default_volume > music.max_volume
  ) {
    errors["music.default_volume"] = "Default volume cannot be greater than the maximum.";
  }
  if (!wholeNumber(music.max_queue_tracks, 1, 500)) {
    errors["music.max_queue_tracks"] = "Enter a whole number between 1 and 500.";
  }

  return errors;
}

function sameSet(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  const sorted = [...b].sort();
  return [...a].sort().every((v, i) => v === sorted[i]);
}

/** Partial PUT body per docs/API.md — only keys that actually changed. */
export function diffSettings(server: GuildSettings, draft: GuildSettings): SettingsPatch {
  const patch: SettingsPatch = {};
  for (const key of ID_KEYS) {
    if (server[key] !== draft[key]) patch[key] = draft[key];
  }

  const automod: NonNullable<SettingsPatch["automod"]> = {};
  for (const key of AUTOMOD_SCALAR_KEYS) {
    if (server.automod[key] !== draft.automod[key]) {
      (automod as Record<string, unknown>)[key] = draft.automod[key];
    }
  }
  for (const key of AUTOMOD_LIST_KEYS) {
    if (!sameSet(server.automod[key], draft.automod[key])) {
      automod[key] = draft.automod[key];
    }
  }
  if (Object.keys(automod).length > 0) patch.automod = automod;

  const levels: NonNullable<SettingsPatch["levels"]> = {};
  for (const key of LEVELS_SCALAR_KEYS) {
    // Each key carries its own type; this loop is the only place they mix.
    if (server.levels[key] !== draft.levels[key]) {
      (levels as Record<string, unknown>)[key] = draft.levels[key];
    }
  }
  for (const key of LEVELS_LIST_KEYS) {
    // Order is not meaningful in an ignore list, so compare them as sets.
    if (!sameSet(server.levels[key], draft.levels[key])) levels[key] = draft.levels[key];
  }
  if (Object.keys(levels).length > 0) {
    // The server checks xp_min against xp_max on the merged result, so a patch
    // that moves one side must carry the other. Sending xp_min alone would have
    // it judged against the stored xp_max and rejected mid-edit.
    if ("xp_min" in levels || "xp_max" in levels) {
      levels.xp_min = draft.levels.xp_min;
      levels.xp_max = draft.levels.xp_max;
    }
    patch.levels = levels;
  }

  const ai: NonNullable<SettingsPatch["ai"]> = {};
  for (const key of AI_KEYS) {
    if (server.ai[key] !== draft.ai[key]) {
      (ai as Record<string, unknown>)[key] = draft.ai[key];
    }
  }
  if (Object.keys(ai).length > 0) patch.ai = ai;

  const economy: NonNullable<SettingsPatch["economy"]> = {};
  for (const key of ECONOMY_KEYS) {
    if (server.economy[key] !== draft.economy[key]) {
      (economy as Record<string, unknown>)[key] = draft.economy[key];
    }
  }
  if (Object.keys(economy).length > 0) {
    if ("work_min" in economy || "work_max" in economy) {
      economy.work_min = draft.economy.work_min;
      economy.work_max = draft.economy.work_max;
    }
    patch.economy = economy;
  }

  const music: NonNullable<SettingsPatch["music"]> = {};
  for (const key of MUSIC_KEYS) {
    if (server.music[key] !== draft.music[key]) {
      (music as Record<string, unknown>)[key] = draft.music[key];
    }
  }
  if (Object.keys(music).length > 0) {
    if ("default_volume" in music || "max_volume" in music) {
      music.default_volume = draft.music.default_volume;
      music.max_volume = draft.music.max_volume;
    }
    patch.music = music;
  }

  return patch;
}

export function isDirty(server: GuildSettings, draft: GuildSettings): boolean {
  return Object.keys(diffSettings(server, draft)).length > 0;
}

/** Pairs each validation_failed detail with the field it mentions. */
export function mapValidationDetails(details: string[] | undefined): Record<string, string> {
  const map: Record<string, string> = {};
  if (!details) return map;
  // Longest first, and the `levels.` prefixes ahead of the bare keys: a plain
  // `includes` would otherwise pair "levels.announce_channel: …" with the
  // shorter "levels.announce" and light up the wrong field.
  const known: string[] = [
    ...[...AUTOMOD_SCALAR_KEYS, ...AUTOMOD_LIST_KEYS]
      .map((k) => `automod.${k}`)
      .sort((a, b) => b.length - a.length),
    ...[...LEVELS_SCALAR_KEYS, ...LEVELS_LIST_KEYS]
      .map((k) => `levels.${k}`)
      .sort((a, b) => b.length - a.length),
    ...AI_KEYS.map((k) => `ai.${k}`).sort((a, b) => b.length - a.length),
    ...ECONOMY_KEYS.map((k) => `economy.${k}`).sort((a, b) => b.length - a.length),
    ...MUSIC_KEYS.map((k) => `music.${k}`).sort((a, b) => b.length - a.length),
    ...ID_KEYS,
    "badwords",
    "automod",
    "levels",
    "ai",
    "economy",
    "music",
  ];
  for (const message of details) {
    const key = known.find((k) => message.includes(k));
    map[key ?? "_global"] = message;
  }
  return map;
}
