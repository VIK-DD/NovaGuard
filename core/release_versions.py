"""Canonical public release numbering for NovaGuard.

The public version shown by Discord, the API, dashboard and website is derived
from the update history. Deriving it rather than storing it means those
surfaces cannot drift apart: there is one source of truth, the build history,
and the version is a view over it.

Three phases:

* **Alpha, 1.0 - 1.9.** Everything built before the public launch, spread
  evenly across ten versions. Closed and frozen: ``ALPHA_LAST_BUILD`` is a
  constant precisely so that adding new builds can never reshuffle history a
  visitor already read.
* **Beta, 2.0 - 2.9.** The public testing cycle.
* **Stable, 3.0 onward.** The official release cycle. A version collects
  ``UPDATES_PER_VERSION`` updates, then the next one opens a new version.

Public versions use one decimal digit. The slot after 2.9 is 3.0, after 3.9
is 4.0, and so on; values such as 2.10 are never emitted.

Every published update counts towards that, not only feature work. The
threshold was once limited to "significant" updates, which sounded right and
read wrong: a stretch of fixes and docs left the number parked for weeks, and
a version that never moves tells a visitor nothing about whether the project
is alive. A steady cadence is the more honest signal.

Significance is still detected, but only to mark an update as notable in the
list. It no longer decides when the number moves.
"""

import re
import unicodedata

ALPHA_PHASE = "alpha"
BETA_PHASE = "open-beta"
STABLE_PHASE = "stable"

PHASE_LABELS = {
    ALPHA_PHASE: "Alpha",
    BETA_PHASE: "Beta",
    STABLE_PHASE: "",
}

# The alpha phase spans exactly these ten versions.
ALPHA_MAJOR = 1
ALPHA_SLOTS = 10

# Frozen boundary between the two phases: everything created before this
# instant is alpha history, everything from it on follows the public release
# cycle (open beta through 2.9, stable from 3.0).
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
# Ten minor slots keep public versions on one decimal digit. Once 2.9 fills,
# the next slot is 3.0; after 3.9 comes 4.0.
MINOR_SLOTS_PER_MAJOR = 10
# How many published updates fill one public version.
UPDATES_PER_VERSION = 6

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
    text = re.sub(
        r"same names, smoother behavior",
        "same commands, smoother behavior",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r'Initial tracked release for v\d+\.\d+\.\d+(?:\s+"Nova")?',
        "Initial tracked NovaGuard release",
        text,
        flags=re.IGNORECASE,
    )
    return " ".join(text.split()).strip(" -–—•")


def format_version(major, minor):
    return f"{major}.{minor}"


def public_version_for_slot(slot):
    """Return the one-decimal public version for a post-alpha slot."""
    major_offset, minor = divmod(max(0, int(slot)), MINOR_SLOTS_PER_MAJOR)
    return format_version(BETA_MAJOR + major_offset, minor)


def public_phase_for_slot(slot):
    """Open beta covers 2.x; 3.0 and every later version are stable."""
    major = BETA_MAJOR + max(0, int(slot)) // MINOR_SLOTS_PER_MAJOR
    return BETA_PHASE if major < 3 else STABLE_PHASE


def public_release_label(release, prefix=""):
    """Version text for people; lifecycle phase remains machine-readable."""
    return f"{prefix}{(release or {}).get('version', '')}".strip()


def _as_lines(value):
    if isinstance(value, str):
        return [value]
    return list(value or [])


def _highlights_of(entry):
    """The lines the site prints for an update."""
    highlights = (entry or {}).get("highlights") or (entry or {}).get("summary") or []
    return _as_lines(highlights)


def _significance_text(entry):
    """Every line that could say an update shipped a feature.

    Deliberately wider than what gets displayed. The changelog engine writes
    two parallel summaries - `highlights` and `changes` - and which one carries
    the "Added commands: ..." line depends on how the entry was recorded. For
    eleven real releases it lived only in `changes`, so a detector reading
    `highlights` alone called them routine, and the version number sat still
    while feature after feature shipped.
    """
    entry = entry or {}
    return _highlights_of(entry) + _as_lines(entry.get("changes"))


def is_significant(entry):
    """Whether this update should push the version number forward.

    A new command or a feature-level highlight counts. Everything else is
    still published, just not as a reason to renumber.
    """
    explicit = (entry or {}).get("significant")
    if isinstance(explicit, bool):
        return explicit

    for item in _significance_text(entry):
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
    public_slot = 0
    updates_in_version = 0

    for entry in ordered:
        significant = is_significant(entry)

        if is_alpha(entry):
            entry["release"] = _alpha_release_for(alpha_seen, sizes)
            entry["phase"] = ALPHA_PHASE
            alpha_seen += 1
        else:
            # A version opens, collects updates, and closes once it is full -
            # so the update that fills it is the last of its version, not the
            # first of the next.
            entry["release"] = public_version_for_slot(public_slot)
            entry["phase"] = public_phase_for_slot(public_slot)
            updates_in_version += 1
            if updates_in_version >= UPDATES_PER_VERSION:
                public_slot += 1
                updates_in_version = 0

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
        # Alpha is closed, so no 1.x group can ever be marked current. The
        # newest post-alpha group is current whether it is beta or stable.
        group["current"] = index == 0 and group["phase"] != ALPHA_PHASE
    return ordered


def current_release(entries):
    """The version the project is on right now."""
    groups = release_groups(entries)
    if not groups or groups[0]["phase"] == ALPHA_PHASE:
        return {
            "version": format_version(3, 0),
            "phase": STABLE_PHASE,
            "phase_label": PHASE_LABELS[STABLE_PHASE],
        }
    newest = groups[0]
    return {
        "version": newest["version"],
        "phase": newest["phase"],
        "phase_label": newest["phase_label"],
    }


def current_project_release(state=None, archive=None):
    """Return the canonical live release from the committed archive + engine state.

    Imports stay local so the update engine can call this helper without a
    module-import cycle. ``state`` and ``archive`` are injectable for tests and
    for code that already loaded them.
    """
    if state is None:
        from .config import UPDATE_STATE_FILE
        from .storage import load_json_file

        state = load_json_file(UPDATE_STATE_FILE, {})
    if not isinstance(state, dict):
        state = {}

    from .update_feed import MAX_LIMIT, merged_update_feed

    feed = merged_update_feed(
        limit=MAX_LIMIT,
        archive=archive,
        history=state.get("history"),
        latest=state.get("latest"),
    )
    return current_release(feed)
