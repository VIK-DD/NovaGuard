"""Merge rules for the public update feed."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.update_feed import merged_update_feed, normalize_engine_entry

results = []


def check(name, ok):
    results.append((name, ok))
    print(f"{'ok  ' if ok else 'FAIL'} {name}")


ARCHIVE = [
    {"build": 1, "created_at": "2026-06-28T10:00:00+00:00", "changes": ["First"]},
    {"build": 2, "created_at": "2026-07-01T10:00:00+00:00", "highlights": ["Second"]},
]
HISTORY = [
    {
        "build": 3,
        "created_at": "2026-07-20T10:00:00+00:00",
        "summary": ["🚀 Third", "🧳 Also third"],
        "added_lines": 55,
        "removed_lines": 10,
        "changed_files": 3,
    }
]

feed = merged_update_feed(limit=50, archive=ARCHIVE, history=HISTORY, latest=None)
check("all entries merged", len(feed) == 3)
check("newest first", [entry["build"] for entry in feed] == [3, 2, 1])
check("engine summary becomes changes", feed[0]["changes"] == ["Third", "Also third"])
check("leading emoji stripped from engine entries", "🚀" not in repr(feed[0]))
check("engine entry keeps no summary key", "summary" not in feed[0])
check("stats carried through", feed[0]["added_lines"] == 55)
check("archive highlights preserved", feed[1]["highlights"] == ["Second"])

# The archive stamps a release with its Discord message time and the engine with
# when it recorded it, so the same release carries two timestamps seconds apart.
# Only the tail beyond the archive may come from the engine.
near_duplicate = {
    "build": 2,
    "created_at": "2026-07-01T09:59:58+00:00",  # seconds before the archive's #2
    "summary": ["Second"],
}
tail = {"build": 4, "created_at": "2026-07-26T10:00:00+00:00", "summary": ["Tail"]}
tailed = merged_update_feed(
    limit=50, archive=ARCHIVE, history=[near_duplicate, tail], latest=None
)
check("engine entry at or below the archive cutoff dropped", len(tailed) == 3)
check("only the tail beyond the archive is admitted", tailed[0]["changes"] == ["Tail"])
# Renumbered by chronological position, so the newest of three is #3 — not the 4
# the engine happened to call it.
check("newest of three is numbered 3", tailed[0]["build"] == 3)
check(
    "no near-duplicate of an archived release survives",
    sum(1 for e in tailed if e.get("changes") == ["Second"] or e.get("highlights") == ["Second"])
    == 1,
)
check(
    "engine history is used in full when there is no archive",
    len(merged_update_feed(limit=50, archive=[], history=[near_duplicate, tail], latest=None)) == 2,
)

duplicate = dict(ARCHIVE[1], build=99, summary=["Dup"])
deduped = merged_update_feed(limit=50, archive=ARCHIVE, history=[duplicate], latest=None)
check("duplicate created_at dropped", len(deduped) == 2)
check("archive entry wins over engine duplicate", deduped[0]["build"] == 2)

limited = merged_update_feed(limit=1, archive=ARCHIVE, history=HISTORY, latest=None)
check("limit applied", len(limited) == 1)
check("limit keeps the newest", limited[0]["build"] == 3)

check(
    "limit clamped to the maximum",
    len(merged_update_feed(limit=9999, archive=ARCHIVE, history=HISTORY, latest=None)) == 3,
)
check(
    "unparsable limit falls back to the default",
    len(merged_update_feed(limit="abc", archive=ARCHIVE, history=HISTORY, latest=None)) == 3,
)

with_latest = merged_update_feed(
    limit=50,
    archive=[],
    history=[],
    latest={"build": 9, "created_at": "2026-07-25T10:00:00+00:00", "summary": ["Latest"]},
)
check("latest included when history is empty", len(with_latest) == 1)
check("latest carries its content", with_latest[0]["changes"] == ["Latest"])
# The engine called it #9; as the only release in the feed it is #1.
check("a lone release is numbered 1", with_latest[0]["build"] == 1)

check("entry without created_at rejected", normalize_engine_entry({"summary": ["x"]}) is None)
check(
    "entry without bullets or stats rejected",
    normalize_engine_entry({"created_at": "2026-07-01T00:00:00+00:00"}) is None,
)
check(
    "entry with only stats accepted",
    normalize_engine_entry({"created_at": "2026-07-01T00:00:00+00:00", "added_lines": 4})
    is not None,
)
check(
    "unparsable created_at rejected",
    normalize_engine_entry({"created_at": "nope", "summary": ["x"]}) is None,
)
check("non-dict rejected", normalize_engine_entry("not an entry") is None)
check(
    "blank summary lines dropped",
    normalize_engine_entry(
        {"created_at": "2026-07-01T00:00:00+00:00", "summary": ["Real", "  ", ""]}
    )["changes"]
    == ["Real"],
)

check(
    "empty inputs give an empty feed",
    merged_update_feed(limit=50, archive=[], history=[], latest=None) == [],
)
check(
    "malformed archive rows skipped",
    merged_update_feed(limit=50, archive=["nope", {"created_at": "bad"}], history=[], latest=None)
    == [],
)

failed = [name for name, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
if failed:
    raise SystemExit(1)
