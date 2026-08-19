"""The introduction card a server gets when NovaGuard arrives.

The interesting failure here is not a crash. It is the card quietly telling
a whole server to type a command that does not exist — which nobody reports,
because the people reading it assume they got it wrong.
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.info_panel import (  # noqa: E402
    ADMIN_COMMANDS,
    EVERYONE_COMMANDS,
    build_info_embed,
)
from core.updates import extract_all_commands  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class FakeGuild:
    def __init__(self, name="Test Server"):
        self.name = name


def body(embed):
    return "\n".join(
        [embed.title or "", embed.description or ""]
        + [f"{field.name}\n{field.value}" for field in embed.fields]
    )


def bot_commands():
    sources = {
        str(path.relative_to(ROOT)): path.read_text(encoding="utf-8")
        for path in (ROOT / "cogs").glob("*.py")
    }
    return set(extract_all_commands(sources))


class InfoPanelTests(unittest.TestCase):
    def test_every_command_it_names_actually_exists(self):
        # The whole point of the card is that a stranger can act on it. A
        # command listed here and renamed in a cog leaves a server following
        # instructions the bot will refuse.
        named = {command for command, _ in EVERYONE_COMMANDS + ADMIN_COMMANDS}

        missing = {c for c in named if c.removeprefix("/") not in bot_commands()}

        self.assertFalse(missing, f"The panel names commands that do not exist: {missing}")

    def test_it_greets_the_server_by_name(self):
        self.assertIn("Aurora", body(build_info_embed(FakeGuild("Aurora"))))

    def test_it_says_nothing_is_on_until_someone_chooses_it(self):
        # Members are reading about a bot they did not install. Whether it is
        # already watching them is the first thing they want answered.
        text = body(build_info_embed(FakeGuild()))

        self.assertIn("Nothing is switched on until someone chooses it", text)

    def test_it_points_at_setup_without_making_that_the_whole_message(self):
        text = body(build_info_embed(FakeGuild()))

        self.assertIn("/setup", text)
        self.assertIn("/help", text)

    def test_it_tells_members_how_to_get_their_data_out(self):
        text = body(build_info_embed(FakeGuild()))

        self.assertIn("/privacy export", text)
        self.assertIn("/privacy delete", text)

    def test_it_stays_short_enough_to_read(self):
        # A wall of text is scrolled past, which costs the card its only job.
        # Discord's own ceiling is far higher; this is the readable one.
        embed = build_info_embed(FakeGuild())

        self.assertLessEqual(len(embed.fields), 5)
        self.assertLess(len(body(embed)), 1600)

    def test_no_field_is_laid_out_side_by_side(self):
        # Discord packs inline fields three to a row on desktop, which is what
        # made the status card unreadable before it was stacked.
        for field in build_info_embed(FakeGuild()).fields:
            self.assertFalse(field.inline)


if __name__ == "__main__":
    unittest.main()
