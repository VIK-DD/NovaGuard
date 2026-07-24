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

/** Mirrors the server's badwords rules: lowercase, trim, dedupe, ≤40 chars, ≤100 words. */
export function normalizeBadwords(raw: string[]): string[] {
  const out: string[] = [];
  for (const word of raw) {
    const w = word.trim().toLowerCase();
    if (!w || w.length > 40 || out.includes(w)) continue;
    out.push(w);
    if (out.length === 100) break;
  }
  return out;
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

  return patch;
}

export function isDirty(server: GuildSettings, draft: GuildSettings): boolean {
  return Object.keys(diffSettings(server, draft)).length > 0;
}

/** Pairs each validation_failed detail with the field it mentions. */
export function mapValidationDetails(details: string[] | undefined): Record<string, string> {
  const map: Record<string, string> = {};
  if (!details) return map;
  const known: string[] = [...ID_KEYS, "badwords", "automod"];
  for (const message of details) {
    const key = known.find((k) => message.includes(k));
    map[key ?? "_global"] = message;
  }
  return map;
}
