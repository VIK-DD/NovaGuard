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

/** Give a runtime-built node the same CSS scope the server-rendered ones have.
 *
 * Astro scopes a component's styles with a `data-astro-cid-*` attribute
 * stamped onto the elements it renders, and the compiled rule wants it on
 * both sides of the selector:
 *
 *   details[data-astro-cid-rp3sgb2s][open] .chevron[data-astro-cid-rp3sgb2s]
 *
 * Nothing created here at runtime is given that attribute, so every scoped
 * rule quietly skipped the newest card: the chevron never turned, the panel
 * never animated open, the rows never rose. Only the chevron was visible
 * enough for anyone to report.
 *
 * The attribute is read off the accordion the page already rendered rather
 * than written down, because its hash changes whenever the component's styles
 * are edited — a copied constant would be correct exactly until someone
 * touched the CSS, then fail the same silent way.
 */
export function applyStyleScope(root: Element, node: Element): void {
  const scope = root.getAttributeNames().find((name) => name.startsWith("data-astro-cid-"));
  if (!scope) return;
  node.setAttribute(scope, "");
  for (const child of node.querySelectorAll("*")) child.setAttribute(scope, "");
}

function el(tag: string, className: string, text?: string): HTMLElement {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function releaseChevron(): SVGSVGElement {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute(
    "class",
    "chevron size-5 shrink-0 text-ink-faint transition-transform duration-300",
  );
  svg.setAttribute("viewBox", "0 0 20 20");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.6");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");

  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", "M5 7.5 10 12.5 15 7.5");
  svg.append(path);
  return svg;
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
export function versionCard(group: ReleaseGroup): HTMLDetailsElement {
  const card = document.createElement("details");
  card.className =
    "group release-item rounded-[var(--radius)] border border-line bg-card transition-colors duration-300 hover:border-line-strong";
  card.dataset.releaseVersion = group.version;
  if (group.current) {
    card.dataset.currentRelease = "";
    card.dataset.open = "";
    card.open = true;
  }

  const summary = document.createElement("summary");
  summary.className =
    "flex cursor-pointer list-none items-center gap-4 px-5 py-4 outline-none focus-visible:ring-2 focus-visible:ring-primary/60 sm:px-6";

  const left = el("span", "flex min-w-0 flex-1 items-center gap-3");
  const phaseBadge = el(
    "span",
    "shrink-0 rounded-full border border-line px-2.5 py-1 text-[11px] font-medium tracking-wider text-ink-faint uppercase",
  );
  phaseBadge.dataset.releasePhaseBadge = "";
  const phase = el("span", "", group.phaseLabel);
  phase.dataset.releasePhase = "";
  phaseBadge.append(phase);
  left.append(
    el(
      "span",
      "font-display text-2xl font-semibold tabular-nums text-ink sm:text-3xl",
      group.version,
    ),
    phaseBadge,
  );
  if (group.current) {
    const marker = el(
      "span",
      "hidden shrink-0 items-center gap-1.5 text-xs text-ink-muted sm:flex",
    );
    marker.dataset.currentReleaseMarker = "";
    marker.append(el("span", "live-dot size-1.5 rounded-full bg-good"), "Current");
    left.append(marker);
  }

  const meta = el("span", "hidden text-right text-xs leading-relaxed text-ink-faint md:block");
  const count = el(
    "span",
    "block text-ink-muted",
    `${group.updateCount} ${group.updateCount === 1 ? "update" : "updates"}`,
  );
  count.dataset.releaseCount = "";
  const span = el("span", "block", spanLabel(group));
  span.dataset.releaseSpan = "";
  meta.append(count, span);

  summary.append(left, meta, releaseChevron());

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

export function syncCurrentVersion(root: HTMLElement, version: string | undefined) {
  let foundCurrent = false;
  for (const card of root.querySelectorAll<HTMLElement>("[data-release-version]")) {
    const current = Boolean(version) && card.dataset.releaseVersion === version;
    if (current) {
      foundCurrent = true;
      card.dataset.currentRelease = "";
      if (card instanceof HTMLDetailsElement) card.open = true;
      card.dataset.open = "";
    } else {
      delete card.dataset.currentRelease;
      // The static page starts with exactly one card open. Preserve that same
      // state after a live version is prepended instead of leaving the baked
      // former-current release expanded underneath it.
      if (card instanceof HTMLDetailsElement) card.open = false;
      delete card.dataset.open;
    }

    const marker = card.querySelector<HTMLElement>("[data-current-release-marker]");
    if (marker) marker.hidden = !current;
  }

  if (foundCurrent) {
    const note = document.querySelector<HTMLElement>("[data-release-sync-note]");
    if (note) {
      note.hidden = true;
      note.textContent = "";
    }
  }
}

async function fetchLiveUpdates(): Promise<unknown> {
  const response = await fetch("/api/updates-feed", {
    headers: { Accept: "application/json" },
    // The one request on the site that must never be answered from the
    // browser's own cache: its entire job is to be newer than the page it is
    // patching. A Cloudflare Browser Cache TTL of four hours was rewriting
    // the worker's five-minute header on the way out, so a reader who had
    // opened /updates once kept seeing that first copy however often they
    // refreshed — the static list moved on at the next deploy while the live
    // tail did not. The edge cache still shields the bot from the traffic.
    cache: "no-store",
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
      const fresh_card = versionCard(group);
      applyStyleScope(root, fresh_card);
      root.prepend(fresh_card);
      added += group.updateCount;
      continue;
    }

    const list = card.querySelector("ol");
    if (!list) continue;
    for (const update of [...fresh].reverse()) {
      const row = updateRow(update);
      // Rows added to a card the server rendered need the scope just as much:
      // the stagger animation is scoped too, so an unstamped row would sit
      // still while the ones around it moved.
      applyStyleScope(root, row);
      list.prepend(row);
      added += 1;
    }
    updateCardMeta(card, group);
  }

  if (!added) return;

  setStat("[data-release-total-versions]", groups.length);
  setStat("[data-release-total-updates]", merged.length);
  const computedCurrent = groups.find((group) => group.current)?.version;
  syncCurrentVersion(root, document.documentElement.dataset.currentRelease || computedCurrent);
  (root as HTMLElement & { ngRemeasure?: () => void }).ngRemeasure?.();
}

// A stale page is the acceptable outcome here: the baked archive is already a
// complete and correct record, just not the newest one.
void run().catch(() => {});
