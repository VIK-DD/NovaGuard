"""The instructions someone follows while the service is down.

This is read once, under pressure, by somebody who cannot afford to
experiment. Every defect in it costs more than the same defect anywhere else
in the project: a wrong path wastes minutes nobody has, and a missing step
pushes the reader toward the one flag the restore tool itself calls dangerous.

It had no tests at all until now, which is roughly the inverse of how much it
matters.
"""

import os
import sys
import unittest
from datetime import UTC, datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import BASE_DIR  # noqa: E402
from core.privacy_ledger import LEDGER_PATH, REMOTE_LEDGER_PATH  # noqa: E402

BACKUP = {
    "name": "novaguard-full-20260820-0700-auto.zip.ngbackup",
    "size_text": "4.2 MB",
    "mtime": datetime(2026, 8, 20, 7, 0, tzinfo=UTC),
}

HEALTHY_REPORT = {
    "ok": True,
    "encrypted": True,
    "sqlite": "ok",
    "errors": [],
    "warnings": [],
    "included": ["data/novaguard.sqlite3"],
}


def build_plan(remote_dest="gdrive:NovaGuard"):
    import cogs.setup as setup_module

    with mock.patch.dict(os.environ, {}, clear=False):
        if remote_dest:
            os.environ["BACKUP_REMOTE_DEST"] = remote_dest
        else:
            os.environ.pop("BACKUP_REMOTE_DEST", None)
        return setup_module.backup_restore_plan_embed(BACKUP, HEALTHY_REPORT)


def plan_text(remote_dest="gdrive:NovaGuard"):
    embed = build_plan(remote_dest)
    return "\n".join(
        [embed.title or "", embed.description or ""]
        + [f"{field.name}\n{field.value}" for field in embed.fields]
    )


class RestorePlanTests(unittest.TestCase):
    # --- the path has to be one that exists ----------------------------

    def test_it_names_the_directory_the_bot_is_actually_installed_in(self):
        # It used to say `cd ~/NovaGuard`. The live host is ~/Novaguard, and
        # Linux does not consider those the same directory — so the first line
        # of the emergency plan failed before anything else could run.
        self.assertIn(str(BASE_DIR), plan_text())

    def test_it_does_not_guess_a_home_directory_name(self):
        self.assertNotIn("~/NovaGuard", plan_text())

    # --- the deletion ledger, and why the plan stalls without it -------

    def test_it_tells_the_reader_about_the_deletion_ledger(self):
        # Without it the restore refuses, correctly, and the plan gave no
        # indication of why or of what to do next.
        self.assertIn(LEDGER_PATH.name, plan_text())

    def test_it_gives_the_off_site_path_when_a_remote_is_configured(self):
        # On a fresh host the local ledger does not exist. This is the only
        # other copy, and nothing else in the bot ever says where it lives.
        text = plan_text(remote_dest="gdrive:NovaGuard")

        self.assertIn(REMOTE_LEDGER_PATH, text)
        self.assertIn("gdrive:NovaGuard", text)

    def test_it_says_so_plainly_when_no_remote_is_configured(self):
        # Promising a copy that was never uploaded is worse than silence.
        text = plan_text(remote_dest="")

        self.assertNotIn(REMOTE_LEDGER_PATH, text)
        self.assertIn(LEDGER_PATH.name, text)

    def test_it_never_recommends_skipping_the_ledger(self):
        # --allow-missing-deletion-ledger resurrects erased data. It exists for
        # a deliberate operator decision, never as a step in a printed plan.
        self.assertNotIn("--allow-missing-deletion-ledger", plan_text())

    # --- nothing may be cut off mid-instruction ------------------------

    def test_no_command_block_is_truncated(self):
        # The old plan sliced its command block at 920 characters, so adding a
        # step could silently cut the last command in half — and a plan that
        # looks complete while ending mid-line is worse than one that admits
        # it is long.
        lines = plan_text().splitlines()

        for index, line in enumerate(lines):
            if not line.rstrip().endswith("\\"):
                continue
            # A backslash is a legitimate shell continuation. What must never
            # happen is one with nothing after it — that is a command cut in
            # half, and pasting it hangs the shell waiting for the rest.
            following = lines[index + 1].strip() if index + 1 < len(lines) else ""
            self.assertTrue(following, f"continuation with nothing after it: {line}")
            self.assertNotEqual(following, "```", f"continuation ends the block: {line}")

    def test_every_field_fits_inside_discord_limits(self):
        embed = build_plan()

        for field in embed.fields:
            with self.subTest(field=field.name):
                self.assertLessEqual(len(field.value), 1024)

    # --- the ordering that keeps live data recoverable -----------------

    def test_it_stops_the_bot_before_touching_data(self):
        text = plan_text()

        self.assertLess(text.index("pm2 stop"), text.index("novaguard.sqlite3"))

    def test_it_copies_live_data_aside_before_overwriting_it(self):
        # The archive is verified, but the operator's own current data is not —
        # and a restore run against the wrong archive is survivable only while
        # the previous state still exists somewhere.
        text = plan_text()

        self.assertIn("data-before-restore", text)
        self.assertLess(text.index("data-before-restore"), text.index("pm2 restart"))

    def test_it_restores_into_a_scratch_directory_first(self):
        # Never straight over live data: the extract is verified after it
        # lands, so it has to land somewhere disposable.
        text = plan_text()

        self.assertIn("--output", text)
        self.assertIn("--replace", text)


if __name__ == "__main__":
    unittest.main()
