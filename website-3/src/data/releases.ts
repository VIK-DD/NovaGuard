// Public release numbering, mirrored from core/release_versions.py.
//
// The site is static, so it groups the baked-in archive itself rather than
// asking the API for versions it would then have to trust. Keeping the rules
// in one small module means the two implementations can be compared line by
// line; the Python docstring carries the full reasoning.
//
// Two phases: alpha is closed and spans exactly 1.0-1.9, open beta runs from
// 2.0 and advances every five significant updates. Small changes still appear
// in their version's list but never push the number, or the version churns on
// noise and stops meaning anything.

import type { Release } from "./updates";

export const ALPHA_PHASE = "alpha";
export const BETA_PHASE = "open-beta";

export const PHASE_LABELS: Record<string, string> = {
  [ALPHA_PHASE]: "Alpha",
  [BETA_PHASE]: "Open Beta",
};

const ALPHA_MAJOR = 1;
const ALPHA_SLOTS = 10;
const BETA_MAJOR = 2;

/** How many published updates fill one open-beta version. */
export const UPDATES_PER_VERSION = 6;

// Frozen boundary. A date rather than a build number: build numbers repeat
// across changelog engine resets, and the bot's archive and this one have
// drifted apart, so the same number names different updates depending on
// which file you read. Never derive this from the data - published version
// numbers must not move under a visitor who already read them.
export const ALPHA_CUTOFF_ISO = "2026-08-09T00:00:00+00:00";

// The changelog engine prefixes feature-level highlights with these. Matched,
// never rendered: `cleanText` strips them for display.
const RELEASE_HIGHLIGHT_PREFIXES = [
  "\u{1F680}",
  "\u{1F5C4}",
  "\u{1F9F3}",
  "\u{1FA7A}",
  "\u{1F3C6}",
  "\u{1F4DC}",
  "\u{1F419}",
];
// A shipped command is the clearest sign a release did something people can
// see. The engine has phrased this at least two ways over its life - "Added
// commands:" in the archive, "New commands ready to try:" in newer builds - so
// both are matched. Missing one would quietly freeze the version number.
const NEW_COMMAND_MARKERS = ["added commands", "new commands"];

const EMOJI_PATTERN =
  /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE00}-\u{FE0F}\u{2190}-\u{21FF}\u{2B00}-\u{2BFF}]+/gu;

export interface StampedRelease extends Release {
  release: string;
  phase: string;
  significant: boolean;
}

export interface ReleaseGroup {
  version: string;
  phase: string;
  phaseLabel: string;
  updates: StampedRelease[];
  updateCount: number;
  significantCount: number;
  startedAt: string | null;
  releasedAt: string | null;
  current: boolean;
}

/** Strip emoji and tidy spacing for anything the site shows. */
export function cleanText(value: string): string {
  return value
    .normalize("NFKC")
    .replace(EMOJI_PATTERN, "")
    .replace(/\s+/g, " ")
    .replace(/^[\s\-–—•]+|[\s\-–—•]+$/g, "")
    .trim();
}

function highlightsOf(release: Release): string[] {
  return [...(release.highlights ?? []), ...(release.changes ?? [])];
}

/** Whether this update should push the version number forward. */
export function isSignificant(release: Release): boolean {
  if (typeof release.significant === "boolean") return release.significant;
  return highlightsOf(release).some((item) => {
    const text = (item ?? "").trim();
    if (!text) return false;
    if (RELEASE_HIGHLIGHT_PREFIXES.some((prefix) => text.startsWith(prefix))) return true;
    const lowered = text.toLowerCase();
    return NEW_COMMAND_MARKERS.some((marker) => lowered.includes(marker));
  });
}

export function isAlpha(release: Release): boolean {
  return (release.created_at ?? "") < ALPHA_CUTOFF_ISO;
}

/**
 * Split historical updates across the ten alpha versions. Remainders go to the
 * earliest versions, where development churned most.
 */
export function alphaSlotSizes(total: number, slots = ALPHA_SLOTS): number[] {
  if (total <= 0) return Array<number>(slots).fill(0);
  const base = Math.floor(total / slots);
  const remainder = total % slots;
  return Array.from({ length: slots }, (_, index) => base + (index < remainder ? 1 : 0));
}

function alphaReleaseFor(position: number, sizes: number[]): string {
  let seen = 0;
  for (let index = 0; index < sizes.length; index += 1) {
    seen += sizes[index];
    if (position < seen) return `${ALPHA_MAJOR}.${index}`;
  }
  return `${ALPHA_MAJOR}.${ALPHA_SLOTS - 1}`;
}

/**
 * Stamp every update with its release and phase, oldest first, so a version
 * fills in the order things actually happened. Dates order the feed; the build
 * number only breaks ties for the same instant.
 */
export function assignReleases(releases: Release[]): StampedRelease[] {
  const ordered = [...releases].sort((a, b) => {
    const byDate = (a.created_at ?? "").localeCompare(b.created_at ?? "");
    return byDate !== 0 ? byDate : (a.build ?? 0) - (b.build ?? 0);
  });

  const sizes = alphaSlotSizes(ordered.filter(isAlpha).length);
  let alphaSeen = 0;
  let betaMinor = 0;
  let updatesInVersion = 0;

  return ordered.map((release) => {
    const significant = isSignificant(release);
    let version: string;
    let phase: string;

    if (isAlpha(release)) {
      version = alphaReleaseFor(alphaSeen, sizes);
      phase = ALPHA_PHASE;
      alphaSeen += 1;
    } else {
      // A version opens, collects updates, and closes once it is full, so the
      // update that fills it is the last of its version rather than the first
      // of the next.
      version = `${BETA_MAJOR}.${betaMinor}`;
      phase = BETA_PHASE;
      updatesInVersion += 1;
      if (updatesInVersion >= UPDATES_PER_VERSION) {
        betaMinor += 1;
        updatesInVersion = 0;
      }
    }

    return {
      ...release,
      release: version,
      phase,
      significant,
      highlights: highlightsOf(release).map(cleanText).filter(Boolean),
    };
  });
}

/** Group updates into releases, newest version first. This is what renders. */
export function releaseGroups(releases: Release[]): ReleaseGroup[] {
  const groups = new Map<string, ReleaseGroup>();
  const order: string[] = [];

  for (const update of assignReleases(releases)) {
    let group = groups.get(update.release);
    if (!group) {
      group = {
        version: update.release,
        phase: update.phase,
        phaseLabel: PHASE_LABELS[update.phase] ?? update.phase,
        updates: [],
        updateCount: 0,
        significantCount: 0,
        startedAt: null,
        releasedAt: null,
        current: false,
      };
      groups.set(update.release, group);
      order.push(update.release);
    }

    group.updates.push(update);
    if (update.significant) group.significantCount += 1;

    const created = update.created_at;
    if (created) {
      if (!group.startedAt || created < group.startedAt) group.startedAt = created;
      if (!group.releasedAt || created > group.releasedAt) group.releasedAt = created;
    }
  }

  const ordered = order.map((version) => groups.get(version) as ReleaseGroup).reverse();
  for (const [index, group] of ordered.entries()) {
    group.updateCount = group.updates.length;
    // Newest update first inside a version: people read the latest change
    // before the one that opened the version weeks earlier.
    group.updates.sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
    // Alpha is closed. If the baked archive has not yet received its first
    // beta update, 1.9 is history rather than the current release.
    group.current = index === 0 && group.phase === BETA_PHASE;
  }
  return ordered;
}

/** The version the project is on right now. */
export function currentRelease(releases: Release[]): { version: string; phaseLabel: string } {
  const groups = releaseGroups(releases);
  if (!groups.length || groups[0].phase !== BETA_PHASE) {
    return { version: `${BETA_MAJOR}.0`, phaseLabel: PHASE_LABELS[BETA_PHASE] };
  }
  return { version: groups[0].version, phaseLabel: groups[0].phaseLabel };
}
