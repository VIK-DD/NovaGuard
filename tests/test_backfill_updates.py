"""Parser tests for the Discord update archive builder."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.backfill_updates import (
    normalize_field_name,
    parse_bullets,
    parse_deploy_embed,
)

results = []


def check(name, ok):
    results.append((name, ok))
    print(f"{'ok  ' if ok else 'FAIL'} {name}")


FULL_EMBED = {
    "title": "\U0001f680 Bot Update Deployed",
    "description": "A fresh NovaGuard build is live.",
    "fields": [
        {
            "name": "✨ Release Highlights",
            "value": "• Setup wizard upgraded\n• Automatic backups added",
        },
        {
            "name": "\U0001f9ed Command & Project Changes",
            "value": "• Internal engine improvements: `cogs/voice.py`",
        },
        {
            "name": "\U0001f4ca Code Stats",
            "value": "```diff\n+ 48 lines added\n- 8 lines removed\n~ 1 tracked files changed\n```",
        },
        {"name": "\U0001f3d7️ Build", "value": '`#16` • v3.0.0 "Nova"'},
    ],
}

PLAIN_NAMES_EMBED = {
    "title": "Bot Update Deployed",
    "fields": [
        {"name": "What Changed", "value": "• Tickets reworked"},
        {"name": "Code Stats", "value": "```diff\n+ 5 lines added\n- 0 lines removed\n```"},
    ],
}

STATS_ONLY_EMBED = {
    "title": "\U0001f680 Bot Update Deployed",
    "fields": [
        {
            "name": "\U0001f4ca Code Stats",
            "value": "```diff\n+ 12 lines added\n- 3 lines removed\n~ 2 tracked files changed\n```",
        }
    ],
}

RESTART_EMBED = {
    "title": "\U0001f504 Bot Restarted • Current Live Build",
    "fields": [{"name": "\U0001f3d7️ Build", "value": "`#17`"}],
}

check("emoji field name normalises", normalize_field_name("\U0001f4ca Code Stats") == "code stats")
check(
    "ampersand kept",
    normalize_field_name("\U0001f9ed Command & Project Changes") == "command & project changes",
)
check("plain name unchanged", normalize_field_name("What Changed") == "what changed")

check("bullet markers stripped", parse_bullets("• One\n• Two") == ["One", "Two"])
check("code fences dropped", parse_bullets("```diff\n+ 1 lines added\n```") == ["+ 1 lines added"])
check("blank lines dropped", parse_bullets("• One\n\n• Two") == ["One", "Two"])
# Highlight bullets carry a category emoji after the marker; the page has none.
check(
    "leading emoji stripped after the marker",
    parse_bullets("• \U0001f680 Setup wizard upgraded") == ["Setup wizard upgraded"],
)
check(
    "emoji with a variation selector stripped",
    parse_bullets("• \U0001f5c4️ SQLite now powers server config")
    == ["SQLite now powers server config"],
)
check(
    "several leading emoji stripped",
    parse_bullets("• \U0001f6e0️ \U0001f9f3 Backups added") == ["Backups added"],
)
check(
    "emoji inside the sentence is left alone",
    parse_bullets("• Renamed the \U0001f680 command") == ["Renamed the \U0001f680 command"],
)
check("plain bullet untouched", parse_bullets("• Internal engine improvements") == ["Internal engine improvements"])

entry = parse_deploy_embed(FULL_EMBED, "2026-07-24T01:28:56+00:00", 99)
check("full embed parsed", entry is not None)
check("build read from embed not fallback", entry["build"] == 16)
check("version read", entry["version"] == "3.0.0")
check("codename read", entry["codename"] == "Nova")
check(
    "highlights grouped",
    entry["highlights"] == ["Setup wizard upgraded", "Automatic backups added"],
)
check("changes grouped", entry["changes"] == ["Internal engine improvements: `cogs/voice.py`"])
check("added lines", entry["added_lines"] == 48)
check("removed lines", entry["removed_lines"] == 8)
check("changed files", entry["changed_files"] == 1)
check("created_at carried", entry["created_at"] == "2026-07-24T01:28:56+00:00")
check("no emoji leaks into content", "\U0001f680" not in repr(entry))

plain = parse_deploy_embed(PLAIN_NAMES_EMBED, "2026-07-01T00:00:00+00:00", 7)
check("plain field names accepted", plain["highlights"] == ["Tickets reworked"])
check("fallback build used when embed has none", plain["build"] == 7)
check("missing changed_files omitted", "changed_files" not in plain)

stats_only = parse_deploy_embed(STATS_ONLY_EMBED, "2026-07-02T00:00:00+00:00", 8)
check("release with stats but no bullets is kept", stats_only is not None)
check(
    "stats-only entry has no bullet keys",
    "highlights" not in stats_only and "changes" not in stats_only,
)

check(
    "restart notice rejected",
    parse_deploy_embed(RESTART_EMBED, "2026-07-03T00:00:00+00:00", 9) is None,
)
check("empty embed rejected", parse_deploy_embed({"title": "Bot Update Deployed"}, "x", 1) is None)

failed = [name for name, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
if failed:
    raise SystemExit(1)
