// Fills in releases that shipped after this page was built.
//
// The /updates page is static: `updates-archive.json` is baked at build time,
// so a release the bot published an hour ago stays invisible until the site is
// deployed again. That surprised people - reasonably, since the release exists
// in Discord and in the API the moment it happens.
//
// This adds the tail on top of the baked page rather than replacing it. The
// server-rendered HTML stays the source of truth for everything it already
// contains, and remains the whole page for crawlers and anyone without JS;
// this only appends what is missing.
//
// Re-grouping the merged set is safe because the phase boundary is a frozen
// date: new entries always land in open beta, never shuffling the alpha
// numbering a visitor may have bookmarked, and beta versions fill in
// chronological order so existing assignments cannot move either.
import { releaseGroups, type ReleaseGroup, type StampedRelease } from "../data/releases";
import archive from "../data/updates-archive.json";
import { formatReleaseDate, type Release } from "../data/updates";

const FETCH_TIMEOUT_MS = 6000;

function isEntry(value: unknown): value is Release {
  if (!value || typeof value !== "object") return false;
  const entry = value as Partial<Release>;
  return typeof entry.created_at === "string" && !Number.isNaN(Date.parse(entry.created_at));
}

/** Everything the API knows, minus what the page already has. */
function mergeFeed(baked: Release[], live: unknown): Release[] {
  if (!Array.isArray(live)) return baked;
  const seen = new Set(baked.map((entry) => entry.created_at));
  const extra = live.filter((entry) => isEntry(entry) && !seen.has(entry.created_at));
  return extra.length ? [...baked, ...(extra as Release[])] : baked;
}

function el(tag: string, className: string, text?: string): HTMLElement {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** One update, matching the markup ReleaseAccordion renders on the server. */
function updateRow(update: StampedRelease): HTMLLIElement {
  const row = document.createElement("li");
  row.className = "release-update relative flex gap-4 pt-5";
  row.dataset.createdAt = update.created_at;

  const rail = el("span", "relative flex w-3 shrink-0 justify-center");
  rail.setAttribute("aria-hidden", "true");
  rail.append(
    el("span", "thread absolute top-2 bottom-[-1.25rem] w-px bg-line"),
    el(
      "span",
      `relative mt-1.5 size-2 rounded-full ring-4 ring-card ${
        update.significant ? "bg-primary" : "bg-line-strong"
      }`,
    ),
  );

  const body = el("div", "min-w-0 flex-1 pb-1");
  const date = el("p", "text-xs text-ink-faint", formatReleaseDate(update.created_at));
  if (update.significant) date.append(el("span", "ml-2 text-primary", "New"));
  body.append(date);

  const lines = update.highlights ?? [];
  if (lines.length) {
    const list = el("ul", "mt-1.5 flex flex-col gap-1.5");
    for (const line of lines) {
      list.append(el("li", "text-sm leading-relaxed text-ink-muted", line));
    }
    body.append(list);
  } else {
    body.append(el("p", "mt-1.5 text-sm text-ink-faint", "Internal improvements."));
  }

  row.append(rail, body);
  return row;
}

/** A whole version card, for a version that did not exist at build time. */
function versionCard(group: ReleaseGroup): HTMLDetailsElement {
  const card = document.createElement("details");
  card.className =
    "group release-item rounded-[var(--radius)] border border-line bg-card transition-colors duration-300 hover:border-line-strong";
  card.dataset.releaseVersion = group.version;

  const summary = document.createElement("summary");
  summary.className =
    "flex cursor-pointer list-none items-center gap-4 px-5 py-4 outline-none focus-visible:ring-2 focus-visible:ring-primary/60 sm:px-6";

  const left = el("span", "flex min-w-0 flex-1 items-center gap-3");
  left.append(
    el(
      "span",
      "font-display text-2xl font-semibold tabular-nums text-ink sm:text-3xl",
      group.version,
    ),
    el(
      "span",
      "shrink-0 rounded-full px-2.5 py-1 text-[11px] font-medium tracking-wider uppercase bg-primary-soft text-primary",
      group.phaseLabel,
    ),
  );

  const meta = el("span", "hidden text-right text-xs leading-relaxed text-ink-faint md:block");
  meta.append(
    el(
      "span",
      "block text-ink-muted",
      `${group.updateCount} ${group.updateCount === 1 ? "update" : "updates"}`,
    ),
  );

  summary.append(left, meta);

  const panel = el("div", "release-panel");
  const inner = el("div", "release-panel-inner border-t border-line px-5 pt-1 pb-5 sm:px-6");
  const list = el("ol", "flex flex-col");
  for (const update of group.updates) list.append(updateRow(update));
  inner.append(list);
  panel.append(inner);

  card.append(summary, panel);
  return card;
}

/** The date range a version covers, as the server writes it. */
function spanLabel(group: ReleaseGroup): string {
  if (!group.startedAt || !group.releasedAt) return "";
  const from = formatReleaseDate(group.startedAt);
  const to = formatReleaseDate(group.releasedAt);
  return from === to ? from : `${from} — ${to}`;
}

/** Keep a card's summary honest after rows are appended to it. */
function updateCardMeta(card: HTMLElement, group: ReleaseGroup) {
  const count = card.querySelector("[data-release-count]");
  if (count) {
    count.textContent = `${group.updateCount} ${group.updateCount === 1 ? "update" : "updates"}`;
  }
  const span = card.querySelector("[data-release-span]");
  if (span) span.textContent = spanLabel(group);
}

function setStat(selector: string, value: number) {
  const node = document.querySelector(selector);
  if (node) node.textContent = String(value);
}

async function fetchLiveUpdates(): Promise<unknown> {
  const response = await fetch("/api/updates-feed", {
    headers: { Accept: "application/json" },
    signal:
      typeof AbortSignal.timeout === "function"
        ? AbortSignal.timeout(FETCH_TIMEOUT_MS)
        : undefined,
  });
  if (!response.ok) throw new Error(`updates feed answered ${response.status}`);
  return (await response.json())?.updates;
}

async function run() {
  const root = document.querySelector<HTMLElement>(".release-accordion");
  // Only page one carries the newest versions; appending anywhere else would
  // insert releases into the middle of someone's pagination.
  if (!root || !document.querySelector("[data-release-live]")) return;

  const baked = archive as Release[];
  const merged = mergeFeed(baked, await fetchLiveUpdates());
  if (merged.length === baked.length) return;

  const groups = releaseGroups(merged);
  // Everything published after the newest baked entry is what this page is
  // missing. Anchoring on that timestamp - rather than on "which versions are
  // absent from the DOM" - is what keeps pagination intact: page one is
  // missing the older versions too, and they belong on page two, not prepended
  // above the newest release.
  const newestBaked = baked.reduce(
    (newest, entry) => (entry.created_at > newest ? entry.created_at : newest),
    "",
  );

  let added = 0;
  // Each addition is prepended, so walking oldest-first leaves everything in
  // the order the server would have rendered it.
  for (const group of [...groups].reverse()) {
    const fresh = group.updates.filter((update) => update.created_at > newestBaked);
    if (!fresh.length) continue;

    const card = root.querySelector<HTMLElement>(
      `details[data-release-version="${CSS.escape(group.version)}"]`,
    );
    if (!card) {
      // A version that did not exist at build time at all.
      root.prepend(versionCard(group));
      added += group.updateCount;
      continue;
    }

    const list = card.querySelector("ol");
    if (!list) continue;
    for (const update of [...fresh].reverse()) {
      list.prepend(updateRow(update));
      added += 1;
    }
    updateCardMeta(card, group);
  }

  if (!added) return;

  setStat("[data-release-total-versions]", groups.length);
  setStat("[data-release-total-updates]", merged.length);
  (root as HTMLElement & { ngRemeasure?: () => void }).ngRemeasure?.();
}

// A stale page is the acceptable outcome here: the baked archive is already a
// complete and correct record, just not the newest one.
void run().catch(() => {});
