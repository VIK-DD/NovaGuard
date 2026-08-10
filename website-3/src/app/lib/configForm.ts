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
  const { levels } = draft;

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
  if (server.automod.invites !== draft.automod.invites) automod.invites = draft.automod.invites;
  if (server.automod.spam !== draft.automod.spam) automod.spam = draft.automod.spam;
  if (!sameSet(server.automod.badwords, draft.automod.badwords)) {
    automod.badwords = draft.automod.badwords;
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
    ...[...LEVELS_SCALAR_KEYS, ...LEVELS_LIST_KEYS]
      .map((k) => `levels.${k}`)
      .sort((a, b) => b.length - a.length),
    ...ID_KEYS,
    "badwords",
    "automod",
    "levels",
  ];
  for (const message of details) {
    const key = known.find((k) => message.includes(k));
    map[key ?? "_global"] = message;
  }
  return map;
}
