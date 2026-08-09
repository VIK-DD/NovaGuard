"""Public release numbering for the website.

The bot keeps its own version for Discord; this is a separate, derived
numbering that groups builds into releases people can browse. Deriving it
rather than storing it means the numbers can never drift out of sync with the
updates they describe - there is one source of truth, the build history, and
the version is a view over it.

Two phases:

* **Alpha, 1.0 - 1.9.** Everything built before the public launch, spread
  evenly across ten versions. Closed and frozen: ``ALPHA_LAST_BUILD`` is a
  constant precisely so that adding new builds can never reshuffle history a
  visitor already read.
* **Open beta, 2.0 onward.** Live development. A version collects updates
  until ``UPDATES_PER_VERSION`` *significant* ones have landed, then the next
  update opens a new version.

"Significant" is deliberately narrow. A typo fix, a CI bump or a docs pass
still appears in its version's list, because people want to see everything
that changed, but it does not push the number - otherwise the version churns
on noise and stops meaning anything.
"""

import re
import unicodedata

ALPHA_PHASE = "alpha"
BETA_PHASE = "open-beta"

PHASE_LABELS = {
    ALPHA_PHASE: "Alpha",
    BETA_PHASE: "Open Beta",
}

# The alpha phase spans exactly these ten versions.
ALPHA_MAJOR = 1
ALPHA_SLOTS = 10

# Frozen boundary between the two phases: everything created before this
# instant is alpha history, everything from it on is open beta.
#
# A date, not a build number, for two reasons. Build numbers repeat - the
# changelog engine's state has been reset before, so the same number can
# appear twice - and the bot's archive and the website's have drifted apart,
# so "build 31" means different updates depending on which one you read. A
# timestamp means the same thing everywhere.
#
# Never compute this from the data. It is frozen so that published version
# numbers cannot move under a visitor who already read them.
ALPHA_CUTOFF_ISO = "2026-08-09T00:00:00+00:00"

BETA_MAJOR = 2
UPDATES_PER_VERSION = 5

# The changelog engine prefixes feature-level highlights with these. They are
# matched, never displayed: see `clean_text`, which strips them for the site.
# Reused rather than reinvented so one definition of "notable" serves both
# Discord and the website.
RELEASE_HIGHLIGHT_PREFIXES = ("\U0001F680", "\U0001F5C4", "\U0001F9F3", "\U0001FA7A", "\U0001F3C6", "\U0001F4DC", "\U0001F419")
# A shipped command is the clearest sign a release did something people can
# see. The engine has phrased this at least two ways over its life - "Added
# commands:" in the archive, "New commands ready to try:" in newer builds - so
# both are matched. Missing one would quietly freeze the version number.
NEW_COMMAND_MARKERS = ("added commands", "new commands")

_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0000FE00-\U0000FE0F"
    "\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF"
    "]+",
    flags=re.UNICODE,
)


def clean_text(value):
    """Strip emoji and tidy spacing for anything shown on the website.

    The changelog engine writes emoji into its highlights for Discord. The
    site renders the same sentences without them, so the wording stays but
    the decoration does not.
    """
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = _EMOJI_PATTERN.sub("", text)
    return " ".join(text.split()).strip(" -–—•")


def format_version(major, minor):
    return f"{major}.{minor}"


def _highlights_of(entry):
    highlights = (entry or {}).get("highlights") or (entry or {}).get("summary") or []
    if isinstance(highlights, str):
        return [highlights]
    return list(highlights)


def is_significant(entry):
    """Whether this update should push the version number forward.

    A new command or a feature-level highlight counts. Everything else is
    still published, just not as a reason to renumber.
    """
    for item in _highlights_of(entry):
        text = str(item or "").strip()
        if not text:
            continue
        if text.startswith(RELEASE_HIGHLIGHT_PREFIXES):
            return True
        lowered = text.lower()
        if any(marker in lowered for marker in NEW_COMMAND_MARKERS):
            return True
    return False


def alpha_slot_sizes(total, slots=ALPHA_SLOTS):
    """Split ``total`` historical builds across the alpha versions.

    Remainders go to the earliest versions: early development churned most,
    so the fuller buckets belong at the start.
    """
    if total <= 0:
        return [0] * slots
    base, remainder = divmod(total, slots)
    return [base + (1 if index < remainder else 0) for index in range(slots)]


def _alpha_release_for(position, sizes):
    """Which alpha version the nth historical build (0-based) falls into."""
    seen = 0
    for index, size in enumerate(sizes):
        seen += size
        if position < seen:
            return format_version(ALPHA_MAJOR, index)
    return format_version(ALPHA_MAJOR, ALPHA_SLOTS - 1)


def _sort_key(entry):
    """Oldest first, by when it happened.

    Dates order the feed because build numbers are not dependable: they
    repeat across engine resets and differ between the bot's archive and the
    website's. The build number is only a tiebreaker for the same instant.
    """
    return (str(entry.get("created_at") or ""), int(entry.get("build") or 0))


def is_alpha(entry):
    """Whether this update belongs to the closed alpha phase."""
    return str((entry or {}).get("created_at") or "") < ALPHA_CUTOFF_ISO


def assign_releases(entries):
    """Stamp every update with the release and phase it belongs to.

    Entries are processed oldest first so a version fills up in the order
    things actually happened. The input is never modified.
    """
    ordered = sorted((dict(entry) for entry in entries or [] if entry), key=_sort_key)
    sizes = alpha_slot_sizes(sum(1 for entry in ordered if is_alpha(entry)))

    stamped = []
    alpha_seen = 0
    beta_minor = 0
    significant_in_version = 0

    for entry in ordered:
        significant = is_significant(entry)

        if is_alpha(entry):
            entry["release"] = _alpha_release_for(alpha_seen, sizes)
            entry["phase"] = ALPHA_PHASE
            alpha_seen += 1
        else:
            # A version opens, collects updates, and closes only once enough
            # significant ones have landed - so the update that tips the
            # count is the last of its version, not the first of the next.
            entry["release"] = format_version(BETA_MAJOR, beta_minor)
            entry["phase"] = BETA_PHASE
            if significant:
                significant_in_version += 1
                if significant_in_version >= UPDATES_PER_VERSION:
                    beta_minor += 1
                    significant_in_version = 0

        entry["significant"] = significant
        entry["highlights"] = [
            cleaned for cleaned in (clean_text(item) for item in _highlights_of(entry)) if cleaned
        ]
        stamped.append(entry)

    return stamped


def release_groups(entries):
    """Group stamped updates into releases, newest release first.

    This is what the website renders: one card per version, expanding into
    the updates it contains.
    """
    stamped = assign_releases(entries)
    groups = {}
    order = []

    for entry in stamped:
        version = entry["release"]
        if version not in groups:
            groups[version] = {
                "version": version,
                "phase": entry["phase"],
                "phase_label": PHASE_LABELS.get(entry["phase"], entry["phase"]),
                "updates": [],
                "build_first": None,
                "build_last": None,
                "significant_count": 0,
                "started_at": None,
                "released_at": None,
            }
            order.append(version)

        group = groups[version]
        build = int(entry.get("build") or 0)
        group["updates"].append(entry)
        group["build_first"] = (
            build if group["build_first"] is None else min(group["build_first"], build)
        )
        group["build_last"] = (
            build if group["build_last"] is None else max(group["build_last"], build)
        )
        if entry.get("significant"):
            group["significant_count"] += 1

        created = entry.get("created_at")
        if created:
            if not group["started_at"] or created < group["started_at"]:
                group["started_at"] = created
            if not group["released_at"] or created > group["released_at"]:
                group["released_at"] = created

    for group in groups.values():
        group["update_count"] = len(group["updates"])
        # Newest update first inside a version: people read the latest change
        # before the one that opened the version weeks earlier.
        group["updates"].sort(key=lambda item: int(item.get("build") or 0), reverse=True)

    ordered = [groups[version] for version in order]
    ordered.reverse()
    for index, group in enumerate(ordered):
        group["current"] = index == 0
    return ordered


def current_release(entries):
    """The version the project is on right now."""
    groups = release_groups(entries)
    if not groups:
        return {
            "version": format_version(BETA_MAJOR, 0),
            "phase": BETA_PHASE,
            "phase_label": PHASE_LABELS[BETA_PHASE],
        }
    newest = groups[0]
    return {
        "version": newest["version"],
        "phase": newest["phase"],
        "phase_label": newest["phase_label"],
    }
