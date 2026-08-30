"""Nothing a member types decides whether the bot's own reply succeeds.

Discord accepts up to 6000 characters in a slash-command string option, and
discord.py validates embed limits nowhere locally - an oversized title or
description is refused by the API as a 400. That 400 reaches the global
command error handler, which answers the member and files an error digest with
a full traceback into the admin channel. So an unclamped presenter turns a
free-text option into a way for any member to generate admin-channel traffic
on demand, at whatever rate the dedupe window allows.

Measured against the previous code:

    /poll question 300 chars   -> embed title 302        (limit 256)
    /choose 40 x 200 chars     -> description 8173       (limit 4096)
    3 long repo file paths     -> hot-files field 1094   (limit 1024)

Two layers now: `Range[str, 1, N]` on the options, so Discord itself refuses
the oversized value before the bot sees it, and a clamp in the presenter, so
text arriving from anywhere else - a watched repository's commit author, a
release tag - cannot overflow either.
"""

import os
import sys
import unittest
from datetime import UTC, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.github_insights import extract_hot_files  # noqa: E402
from core.github_watch_presenters import build_release_watcher_embed  # noqa: E402
from core.utility_presenters import (  # noqa: E402
    build_choice_embed,
    build_poll_embed,
    build_reminder_set_embed,
)
from core.utils import (  # noqa: E402
    EMBED_DESCRIPTION_LIMIT,
    EMBED_FIELD_VALUE_LIMIT,
    EMBED_TITLE_LIMIT,
    clamp,
)

HUGE = "x" * 6000  # what Discord will accept in one string option


def within_discord_limits(embed):
    """Every part of this embed is something Discord will actually accept."""
    problems = []
    if embed.title and len(embed.title) > EMBED_TITLE_LIMIT:
        problems.append(f"title {len(embed.title)} > {EMBED_TITLE_LIMIT}")
    if embed.description and len(embed.description) > EMBED_DESCRIPTION_LIMIT:
        problems.append(f"description {len(embed.description)} > {EMBED_DESCRIPTION_LIMIT}")
    for field in embed.fields:
        if field.value and len(field.value) > EMBED_FIELD_VALUE_LIMIT:
            problems.append(f"field {field.name!r} {len(field.value)} > {EMBED_FIELD_VALUE_LIMIT}")
    return problems


class ClampTests(unittest.TestCase):
    def test_short_text_is_untouched(self):
        self.assertEqual(clamp("hello", 100), "hello")

    def test_text_at_the_limit_is_untouched(self):
        self.assertEqual(clamp("abcde", 5), "abcde")

    def test_longer_text_is_cut_to_the_limit(self):
        self.assertEqual(len(clamp(HUGE, 256)), 256)

    def test_the_cut_is_marked(self):
        self.assertTrue(clamp(HUGE, 256).endswith("…"))

    def test_newlines_survive(self):
        # This is why clamp exists next to truncate: truncate collapses
        # whitespace, which destroys an assembled block of lines.
        self.assertEqual(clamp("a\nb\nc", 100), "a\nb\nc")

    def test_none_and_empty_are_handled(self):
        self.assertEqual(clamp(None, 10), "")
        self.assertEqual(clamp("", 10), "")


class MemberSuppliedTextTests(unittest.TestCase):
    """The presenters a member reaches through a command option."""

    def test_a_huge_poll_question_still_produces_a_valid_embed(self):
        embed = build_poll_embed(HUGE, ["a", "b"], {}, "author")
        self.assertEqual(within_discord_limits(embed), [])

    def test_huge_poll_options_still_produce_a_valid_embed(self):
        embed = build_poll_embed("Which?", [HUGE, HUGE, HUGE, HUGE, HUGE], {}, "author")
        self.assertEqual(within_discord_limits(embed), [])

    def test_a_huge_choose_list_still_produces_a_valid_embed(self):
        embed = build_choice_embed(["y" * 200] * 40, "winner")
        self.assertEqual(within_discord_limits(embed), [])

    def test_a_huge_reminder_message_still_produces_a_valid_embed(self):
        embed = build_reminder_set_embed(datetime.now(UTC), HUGE)
        self.assertEqual(within_discord_limits(embed), [])


class RepositorySuppliedTextTests(unittest.TestCase):
    """Text a watched repository's contributors control.

    These have no command option in front of them, so the presenter clamp is
    the only thing standing between a long file path or release tag and a card
    Discord refuses - which the watcher would then drop silently, having
    already recorded the commits as seen.
    """

    def test_long_file_paths_do_not_overflow_the_hot_files_field(self):
        commits = [{"files": [{"filename": f"{index}{'p' * 400}"} for index in range(5)]}]
        self.assertLessEqual(len(extract_hot_files(commits)), EMBED_FIELD_VALUE_LIMIT)

    def test_no_file_data_still_reads_sensibly(self):
        self.assertEqual(extract_hot_files([]), "No file change data yet.")

    def test_a_long_release_tag_does_not_overflow_its_field(self):
        event = {
            "actor": {"login": "someone"},
            "created_at": "2026-01-01T00:00:00Z",
            "payload": {
                "action": "published",
                "release": {
                    "tag_name": "release/" + "/".join("segment" for _ in range(200)),
                    "name": "n" * 3000,
                    "prerelease": False,
                    "html_url": "https://example.invalid",
                },
            },
        }
        embed, _view = build_release_watcher_embed("owner/repo", event)
        self.assertEqual(within_discord_limits(embed), [])


class CommandOptionLimitTests(unittest.TestCase):
    """The other layer: Discord refuses the oversized value at the door."""

    def _option(self, command, name):
        for parameter in command.parameters:
            if parameter.name == name:
                return parameter
        raise AssertionError(f"{command.name} has no option {name!r}")

    def test_the_free_text_options_declare_a_maximum_length(self):
        from cogs import fun as fun_cog
        from cogs import moderation as moderation_cog
        from cogs import utility as utility_cog

        cases = [
            (utility_cog.Utility.poll, "question"),
            (utility_cog.Utility.remind, "message"),
            (utility_cog.Utility.remind, "duration"),
            (utility_cog.Utility.choose, "options"),
            (fun_cog.Fun.eight_ball, "question"),
            (moderation_cog.Moderation.announce, "title"),
            (moderation_cog.Moderation.announce, "message"),
            (moderation_cog.Moderation.warn_add, "reason"),
        ]
        for command, option_name in cases:
            with self.subTest(command=command.name, option=option_name):
                option = self._option(command, option_name)
                # discord.py stores a Range[str, ...] bound as max_value on
                # the Parameter, and emits it as max_length on the wire.
                self.assertIsNotNone(
                    option.max_value,
                    f"/{command.name} {option_name} accepts up to 6000 characters",
                )
                self.assertLessEqual(option.max_value, 3000)


class UntimeoutHierarchyTests(unittest.TestCase):
    """/untimeout was the one moderation command without the actor check."""

    def test_untimeout_checks_the_actor_can_act_on_the_target(self):
        import inspect

        from cogs import moderation as moderation_cog

        source = inspect.getsource(moderation_cog.Moderation.untimeout.callback)
        self.assertIn("can_act_on", source)

    def test_every_member_targeting_moderation_command_checks_hierarchy(self):
        import inspect

        from cogs import moderation as moderation_cog

        for name in ("kick", "ban", "timeout", "untimeout"):
            with self.subTest(command=name):
                source = inspect.getsource(getattr(moderation_cog.Moderation, name).callback)
                self.assertIn("can_act_on", source, f"/{name} skips the hierarchy check")


if __name__ == "__main__":
    unittest.main()
