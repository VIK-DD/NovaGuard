"""The command count the status page shows.

/stats reported 131 by counting every node in the tree — groups plus the
leaves inside them. The number people recognise is the one Discord shows when
they type "/": the top-level entries, where /backup appears once rather than
as its eight subcommands. That is 81, and it matches the "synced N slash
commands" line the bot logs on startup.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# core.webserver reads these once at import into module constants, so whichever
# test file imports it first fixes them for the run. Match tests/test_webserver.py
# exactly, with setdefault, so that script-style test still starts its server on
# the port it later connects to.
os.environ.setdefault("WEB_ENABLED", "true")
os.environ.setdefault("WEB_PORT", "8399")
os.environ.setdefault("WEB_HOST", "127.0.0.1")
os.environ.setdefault("WEB_CORS_ORIGIN", "http://localhost:5173")

from core.webserver import count_visible_commands  # noqa: E402


class FakeTree:
    """A stand-in that returns a fixed set of top-level commands."""

    def __init__(self, top_level):
        self._top_level = top_level

    def get_commands(self):
        return list(self._top_level)


class CommandCountTests(unittest.TestCase):
    def test_each_top_level_entry_counts_once(self):
        tree = FakeTree(["ping", "help", "rank"])

        self.assertEqual(count_visible_commands(tree), 3)

    def test_a_group_counts_as_one_not_as_its_subcommands(self):
        # /backup is one entry in the Discord picker, whatever it contains.
        # get_commands() returns only the top level, so a group is a single
        # entry — the whole point of the fix.
        tree = FakeTree(["ping", "backup-group", "config-group"])

        self.assertEqual(count_visible_commands(tree), 3)

    def test_the_real_shape_of_the_tree(self):
        # 69 standalone commands + 12 groups = 81 top-level entries, the way
        # the live tree registers with Discord. The old count returned 131.
        top_level = [f"c{i}" for i in range(69)] + [f"g{i}" for i in range(12)]

        self.assertEqual(count_visible_commands(FakeTree(top_level)), 81)

    def test_an_empty_tree_is_zero_not_an_error(self):
        self.assertEqual(count_visible_commands(FakeTree([])), 0)


if __name__ == "__main__":
    unittest.main()
