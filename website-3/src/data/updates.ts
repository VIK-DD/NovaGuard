// Shape and ordering rules for the release feed. Rendering lives in the
// components; this module only sorts, dedupes and measures.
//
// Note on identity: `build` is the number the bot printed in Discord, and it is
// NOT unique — the changelog engine's state was reset several times, so #5
// appears five times across the archive. The page numbers releases by their
// position in date order instead, which is unique and stays stable as new ones
// arrive at the top.

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

const RELEASE_TIME_ZONE = "Europe/Bucharest";

// Both formatters are pinned to Romania time. The static pages are rendered on
// whatever machine ran the build while the live tail is rendered in the visitor's
// browser, so an unpinned zone would let one release show two different dates
// depending on who rendered it.
export function formatReleaseDate(iso: string): string {
  const parsed = Date.parse(iso);
  if (Number.isNaN(parsed)) return iso;
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: RELEASE_TIME_ZONE,
  }).format(new Date(parsed));
}

// Still resolved in Romania time — see the note above. Use 24-hour time because
// the audience reads this as operational history, not casual prose.
export function formatReleaseTime(iso: string): string {
  const parsed = Date.parse(iso);
  if (Number.isNaN(parsed)) return "";
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: RELEASE_TIME_ZONE,
  }).format(new Date(parsed));
}
