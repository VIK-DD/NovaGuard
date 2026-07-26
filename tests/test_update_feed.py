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
        "summary": ["Third", "Also third"],
        "added_lines": 55,
        "removed_lines": 10,
        "changed_files": 3,
    }
]

feed = merged_update_feed(limit=50, archive=ARCHIVE, history=HISTORY, latest=None)
check("all entries merged", len(feed) == 3)
check("newest first", [entry["build"] for entry in feed] == [3, 2, 1])
check("engine summary becomes changes", feed[0]["changes"] == ["Third", "Also third"])
check("engine entry keeps no summary key", "summary" not in feed[0])
check("stats carried through", feed[0]["added_lines"] == 55)
check("archive highlights preserved", feed[1]["highlights"] == ["Second"])

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
check("latest included when history is empty", [entry["build"] for entry in with_latest] == [9])

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
