"""The command count the status page shows.

/stats reported 131 slash commands while the bot has 116 a member can run.
The difference was every group counted as a command: walk_commands() yields
the group container as well as the leaves inside it, so /backup added one to
the total on top of its eight subcommands. A status page that overstates the
bot by 13 percent is a small lie, but a visible one.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("WEB_ENABLED", "false")

from discord import app_commands  # noqa: E402

from core.webserver import count_runnable_commands  # noqa: E402


class FakeTree:
    """A stand-in that walks a fixed set of command nodes."""

    def __init__(self, nodes):
        self._nodes = nodes

    def walk_commands(self):
        return iter(self._nodes)


def leaf(name):
    node = object.__new__(app_commands.Command)
    node.name = name
    return node


def group(name):
    node = object.__new__(app_commands.Group)
    node.name = name
    return node


class CommandCountTests(unittest.TestCase):
    def test_a_flat_set_of_commands_counts_each_one(self):
        tree = FakeTree([leaf("ping"), leaf("help"), leaf("rank")])

        self.assertEqual(count_runnable_commands(tree), 3)

    def test_a_group_is_not_counted_as_a_command(self):
        # The bug: /backup itself is not runnable, only its subcommands are.
        tree = FakeTree([group("backup"), leaf("backup create"), leaf("backup list")])

        self.assertEqual(count_runnable_commands(tree), 2)

    def test_the_real_shape_of_the_tree(self):
        # 116 leaves and 15 groups, the way the live tree actually walks. The
        # old count returned 131; only the leaves are real commands.
        nodes = [leaf(f"c{i}") for i in range(116)] + [group(f"g{i}") for i in range(15)]

        self.assertEqual(count_runnable_commands(FakeTree(nodes)), 116)

    def test_an_empty_tree_is_zero_not_an_error(self):
        self.assertEqual(count_runnable_commands(FakeTree([])), 0)

    def test_only_groups_counts_nothing(self):
        tree = FakeTree([group("backup"), group("admin")])

        self.assertEqual(count_runnable_commands(tree), 0)


if __name__ == "__main__":
    unittest.main()
