"""Tests for the monthly voice-time ledger behind /vh."""

import os
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.voice_hours import (  # noqa: E402
    counts_towards_hours,
    current_month,
    daily_pace,
    decimal_hours,
    format_hours,
    month_key,
    month_label,
    month_window,
    projected_total,
    recap_due,
    rewardable,
    shift_month,
    split_by_month,
    voice_payout,
    voice_timezone_name,
)

CHISINAU = ZoneInfo("Europe/Chisinau")


def utc(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


class MonthKeyTests(unittest.TestCase):
    def test_a_moment_lands_in_its_local_month(self):
        self.assertEqual(month_key(utc(2026, 8, 10, 12), CHISINAU), "2026-08")

    def test_late_evening_on_the_last_day_belongs_to_the_month_that_is_starting(self):
        # 21:30 UTC on 31 July is already 00:30 on 1 August in Chisinau. A
        # member asking "this month" at that moment means August.
        self.assertEqual(month_key(utc(2026, 7, 31, 21, 30), CHISINAU), "2026-08")

    def test_the_same_moment_read_in_utc_disagrees(self):
        # Documents why the ledger is not stored in UTC months: it would tell
        # the member the wrong month for the hours they just spent.
        self.assertEqual(month_key(utc(2026, 7, 31, 21, 30), ZoneInfo("UTC")), "2026-07")

    def test_current_month_matches_the_clock(self):
        self.assertEqual(len(current_month(CHISINAU)), 7)
        self.assertEqual(current_month(CHISINAU)[4], "-")


class TimezoneTests(unittest.TestCase):
    def setUp(self):
        self._saved = {name: os.environ.get(name) for name in ("VOICE_TIMEZONE", "BACKUP_TIMEZONE")}
        for name in self._saved:
            os.environ.pop(name, None)

    def tearDown(self):
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def test_falls_back_to_the_default_zone(self):
        self.assertEqual(voice_timezone_name(), "Europe/Chisinau")

    def test_reuses_the_backup_zone_when_that_is_the_only_one_set(self):
        # An operator who already configured a zone for backups should not have
        # to configure a second one that means the same thing.
        os.environ["BACKUP_TIMEZONE"] = "Europe/Bucharest"

        self.assertEqual(voice_timezone_name(), "Europe/Bucharest")

    def test_the_voice_zone_wins_when_both_are_set(self):
        os.environ["BACKUP_TIMEZONE"] = "Europe/Bucharest"
        os.environ["VOICE_TIMEZONE"] = "Europe/Chisinau"

        self.assertEqual(voice_timezone_name(), "Europe/Chisinau")

    def test_a_blank_setting_is_treated_as_unset(self):
        os.environ["VOICE_TIMEZONE"] = "   "

        self.assertEqual(voice_timezone_name(), "Europe/Chisinau")


class SplitTests(unittest.TestCase):
    def test_an_ordinary_call_produces_one_bucket(self):
        buckets = split_by_month(utc(2026, 8, 10, 18), utc(2026, 8, 10, 20), CHISINAU)

        self.assertEqual(buckets, [("2026-08", 7200.0)])

    def test_a_call_across_the_month_boundary_is_split(self):
        # 21:00 UTC on 31 July is 00:00 on 1 August local, so a call from 20:00
        # to 22:00 UTC gives one hour to each month.
        buckets = split_by_month(utc(2026, 7, 31, 20), utc(2026, 7, 31, 22), CHISINAU)

        self.assertEqual(buckets, [("2026-07", 3600.0), ("2026-08", 3600.0)])

    def test_splitting_never_creates_or_loses_time(self):
        start, end = utc(2026, 7, 31, 18), utc(2026, 8, 1, 6)
        buckets = split_by_month(start, end, CHISINAU)

        self.assertEqual(sum(seconds for _, seconds in buckets), (end - start).total_seconds())

    def test_a_call_spanning_a_whole_month_covers_every_month_it_touches(self):
        buckets = split_by_month(utc(2026, 6, 15), utc(2026, 8, 15), CHISINAU)

        self.assertEqual([month for month, _ in buckets], ["2026-06", "2026-07", "2026-08"])

    def test_a_year_boundary_rolls_the_year(self):
        buckets = split_by_month(utc(2026, 12, 31, 21), utc(2026, 12, 31, 23), CHISINAU)

        self.assertEqual([month for month, _ in buckets], ["2026-12", "2027-01"])

    def test_zero_length_and_reversed_stretches_produce_nothing(self):
        moment = utc(2026, 8, 10, 12)

        self.assertEqual(split_by_month(moment, moment, CHISINAU), [])
        self.assertEqual(split_by_month(moment, utc(2026, 8, 10, 11), CHISINAU), [])
        self.assertEqual(split_by_month(None, moment, CHISINAU), [])
        self.assertEqual(split_by_month(moment, None, CHISINAU), [])

    def test_a_call_through_a_daylight_saving_change_keeps_real_elapsed_time(self):
        # Clocks go back on the last Sunday of October. The member was in voice
        # for two real hours and must be credited two, not one or three.
        start, end = utc(2026, 10, 25, 0), utc(2026, 10, 25, 2)
        buckets = split_by_month(start, end, CHISINAU)

        self.assertEqual(sum(seconds for _, seconds in buckets), 7200.0)


class MonthArithmeticTests(unittest.TestCase):
    def test_shifting_back_within_a_year(self):
        self.assertEqual(shift_month("2026-08", -1), "2026-07")

    def test_shifting_back_across_january(self):
        self.assertEqual(shift_month("2026-01", -1), "2025-12")

    def test_shifting_forward_across_december(self):
        self.assertEqual(shift_month("2026-12", 1), "2027-01")

    def test_shifting_by_a_year(self):
        self.assertEqual(shift_month("2026-08", -12), "2025-08")

    def test_a_month_reads_as_a_name(self):
        self.assertEqual(month_label("2026-08"), "August 2026")

    def test_a_broken_key_is_shown_as_is_rather_than_crashing(self):
        self.assertEqual(month_label("nonsense"), "nonsense")


class FormattingTests(unittest.TestCase):
    def test_hours_and_minutes(self):
        self.assertEqual(format_hours(9420), "2h 37m")

    def test_minutes_are_padded_so_columns_line_up(self):
        self.assertEqual(format_hours(3660), "1h 01m")

    def test_under_an_hour_drops_the_hour(self):
        self.assertEqual(format_hours(1800), "30m")

    def test_under_a_minute_still_says_something(self):
        self.assertEqual(format_hours(42), "42s")

    def test_nothing_is_shown_as_zero_rather_than_blank(self):
        self.assertEqual(format_hours(0), "0s")
        self.assertEqual(format_hours(None), "0s")

    def test_negative_time_cannot_leak_into_the_display(self):
        self.assertEqual(format_hours(-500), "0s")

    def test_decimal_hours_round_to_two_places(self):
        self.assertEqual(decimal_hours(9420), 2.62)
        self.assertEqual(decimal_hours(0), 0.0)
        self.assertEqual(decimal_hours(-10), 0.0)


class EligibilityTests(unittest.TestCase):
    @staticmethod
    def member(**overrides):
        return {"bot": False, "self_deaf": False, "deaf": False, **overrides}

    def test_a_connected_member_counts(self):
        self.assertTrue(counts_towards_hours(self.member()))

    def test_a_muted_member_still_counts(self):
        # Listening without talking is still time spent with the server, and
        # not counting it would punish the quiet members.
        self.assertTrue(counts_towards_hours(self.member(self_mute=True, mute=True)))

    def test_a_deafened_member_does_not_count(self):
        self.assertFalse(counts_towards_hours(self.member(self_deaf=True)))
        self.assertFalse(counts_towards_hours(self.member(deaf=True)))

    def test_the_afk_channel_does_not_count(self):
        self.assertFalse(counts_towards_hours(self.member(), channel_is_afk=True))

    def test_bots_do_not_count(self):
        # A bot sitting in voice for hours must not top the board.
        self.assertFalse(counts_towards_hours(self.member(bot=True)))

    def test_an_empty_record_is_treated_as_a_plain_member(self):
        self.assertTrue(counts_towards_hours({}))

    def test_time_alone_is_tracked_but_not_paid_for(self):
        # Tracked: it happened, and /vh should say so. Not paid: an idle mic
        # must not be the best-earning activity on the server.
        self.assertTrue(counts_towards_hours(self.member()))
        self.assertFalse(rewardable(1))
        self.assertFalse(rewardable(0))

    def test_two_members_together_can_earn(self):
        self.assertTrue(rewardable(2))
        self.assertTrue(rewardable(9))


class MonthWindowTests(unittest.TestCase):
    """The command answers "so far this month", so it has to say how far."""

    def test_a_running_month_counts_only_the_days_that_happened(self):
        window = month_window("2026-08", utc(2026, 8, 10, 12), CHISINAU)

        self.assertTrue(window["current"])
        self.assertEqual(window["elapsed"], 10)
        self.assertEqual(window["days"], 31)
        self.assertEqual(window["remaining"], 21)
        self.assertEqual(window["label"], "1–10 August 2026")

    def test_a_finished_month_covers_all_of_its_days(self):
        window = month_window("2026-07", utc(2026, 8, 10, 12), CHISINAU)

        self.assertFalse(window["current"])
        self.assertEqual(window["elapsed"], 31)
        self.assertEqual(window["remaining"], 0)

    def test_short_months_are_not_assumed_to_have_thirty_one_days(self):
        self.assertEqual(month_window("2026-02", utc(2026, 3, 1), CHISINAU)["days"], 28)
        self.assertEqual(month_window("2026-04", utc(2026, 5, 1), CHISINAU)["days"], 30)

    def test_a_leap_february_has_its_extra_day(self):
        self.assertEqual(month_window("2028-02", utc(2028, 3, 1), CHISINAU)["days"], 29)

    def test_the_first_day_of_a_month_is_day_one_not_day_zero(self):
        window = month_window("2026-08", utc(2026, 8, 1, 6), CHISINAU)

        self.assertEqual(window["elapsed"], 1)
        self.assertEqual(window["label"], "1–1 August 2026")

    def test_late_utc_on_the_last_day_is_already_the_next_month_locally(self):
        # 21:30 UTC on 31 July is 00:30 on 1 August in Chisinau, so August is
        # the month that is running.
        window = month_window("2026-08", utc(2026, 7, 31, 21, 30), CHISINAU)

        self.assertTrue(window["current"])
        self.assertEqual(window["elapsed"], 1)

    def test_a_month_that_has_not_started_has_banked_nothing(self):
        window = month_window("2026-12", utc(2026, 8, 10), CHISINAU)

        self.assertEqual(window["elapsed"], 0)
        self.assertFalse(window["current"])

    def test_a_broken_key_does_not_crash_the_command(self):
        window = month_window("nonsense", utc(2026, 8, 10), CHISINAU)

        self.assertEqual(window["days"], 0)
        self.assertFalse(window["current"])


class PaceTests(unittest.TestCase):
    def test_pace_is_the_average_across_the_days_so_far(self):
        self.assertEqual(daily_pace(36000, 10), 3600.0)

    def test_a_month_with_no_elapsed_days_has_no_pace(self):
        # Guards the division rather than letting the command raise.
        self.assertEqual(daily_pace(36000, 0), 0.0)
        self.assertEqual(daily_pace(36000, -3), 0.0)

    def test_the_projection_extends_the_pace_to_the_end_of_the_month(self):
        # An hour a day for ten days projects to 31 hours across August.
        self.assertEqual(projected_total(36000, 10, 31), 3600.0 * 31)

    def test_a_projection_needs_days_to_extend_from(self):
        self.assertEqual(projected_total(36000, 0, 31), 0.0)
        self.assertEqual(projected_total(36000, 10, 0), 0.0)

    def test_nothing_banked_projects_to_nothing(self):
        self.assertEqual(projected_total(0, 10, 31), 0.0)


class RecapDueTests(unittest.TestCase):
    def test_a_month_never_posted_is_due(self):
        self.assertTrue(recap_due(None, "2026-07"))

    def test_the_same_month_twice_is_not_due(self):
        self.assertFalse(recap_due("2026-07", "2026-07"))

    def test_a_new_completed_month_is_due(self):
        self.assertTrue(recap_due("2026-06", "2026-07"))

    def test_catching_up_after_being_offline_is_still_just_due_once(self):
        # Whether the bot checked on day 1 or day 5 after downtime, the
        # question is only ever "have we posted this exact month yet?".
        self.assertTrue(recap_due("2026-05", "2026-07"))


class PayoutTests(unittest.TestCase):
    def test_an_unfinished_block_pays_nothing_yet(self):
        coins, xp, remainder = voice_payout(300)

        self.assertEqual((coins, xp), (0, 0))
        self.assertEqual(remainder, 300)

    def test_a_finished_block_pays_once(self):
        coins, xp, remainder = voice_payout(600)

        self.assertGreater(coins, 0)
        self.assertGreater(xp, 0)
        self.assertEqual(remainder, 0)

    def test_several_blocks_pay_together(self):
        one, _, _ = voice_payout(600)
        three, _, _ = voice_payout(1800)

        self.assertEqual(three, one * 3)

    def test_the_remainder_is_carried_rather_than_dropped(self):
        # Time split across ticks has to pay exactly what the same time in one
        # stretch would, or a busy server quietly underpays everyone.
        banked = 0.0
        paid = 0
        for _ in range(4):
            coins, _, banked = voice_payout(banked + 300)
            paid += coins

        in_one_go, _, _ = voice_payout(1200)

        self.assertEqual(paid, in_one_go)

    def test_nothing_banked_pays_nothing(self):
        self.assertEqual(voice_payout(0), (0, 0, 0.0))
        self.assertEqual(voice_payout(None), (0, 0, 0.0))

    def test_negative_time_cannot_pay(self):
        self.assertEqual(voice_payout(-5000), (0, 0, 0.0))

    def test_the_rate_can_be_overridden_for_a_calculation(self):
        coins, xp, _ = voice_payout(600, block=600, coins=100, xp=7)

        self.assertEqual((coins, xp), (100, 7))


class LedgerStorageTests(unittest.TestCase):
    """The running totals /vh reads, against a real (temporary) database."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)

        import core.database as database

        self.db = database
        for patch in (
            mock.patch.object(database, "DATA_DIR", Path(self._dir.name)),
            mock.patch.object(database, "DB_PATH", Path(self._dir.name) / "test.sqlite3"),
            mock.patch.object(database, "_INITIALIZED", False),
        ):
            patch.start()
            self.addCleanup(patch.stop)

        database.init_database()

    def test_a_member_with_no_voice_time_gets_zero_rather_than_nothing(self):
        # The command has to render something for a member who has never
        # joined a call, so this must not be None.
        self.assertEqual(
            self.db.voice_month_total("111", "a", "2026-08"), {"seconds": 0.0, "sessions": 0}
        )

    def test_time_accumulates_across_separate_calls(self):
        self.db.add_voice_seconds("111", "a", [("2026-08", 600)], sessions=1)
        self.db.add_voice_seconds("111", "a", [("2026-08", 300)], sessions=1)

        self.assertEqual(
            self.db.voice_month_total("111", "a", "2026-08"), {"seconds": 900.0, "sessions": 2}
        )

    def test_months_are_kept_apart(self):
        self.db.add_voice_seconds("111", "a", [("2026-07", 100), ("2026-08", 200)], sessions=1)

        self.assertEqual(self.db.voice_month_total("111", "a", "2026-07")["seconds"], 100.0)
        self.assertEqual(self.db.voice_month_total("111", "a", "2026-08")["seconds"], 200.0)

    def test_one_call_across_a_month_boundary_counts_as_one_session(self):
        # Otherwise a single New Year's Eve call would show up as two, and the
        # session counts would not add up to the number of calls that happened.
        self.db.add_voice_seconds("111", "a", [("2026-07", 100), ("2026-08", 200)], sessions=1)

        total = sum(
            self.db.voice_month_total("111", "a", month)["sessions"]
            for month in ("2026-07", "2026-08")
        )
        self.assertEqual(total, 1)

    def test_guilds_never_see_each_other(self):
        self.db.add_voice_seconds("111", "a", [("2026-08", 600)], sessions=1)
        self.db.add_voice_seconds("222", "a", [("2026-08", 9999)], sessions=1)

        self.assertEqual(self.db.voice_month_total("111", "a", "2026-08")["seconds"], 600.0)
        self.assertEqual(
            [row["user_id"] for row in self.db.voice_month_leaderboard("111", "2026-08")], ["a"]
        )

    def test_empty_buckets_write_nothing(self):
        self.db.add_voice_seconds("111", "a", [], sessions=1)
        self.db.add_voice_seconds("111", "a", [("2026-08", 0)], sessions=1)

        self.assertEqual(self.db.voice_month_total("111", "a", "2026-08"), {"seconds": 0.0, "sessions": 0})

    def test_the_leaderboard_is_ordered_by_time(self):
        for user, seconds in (("a", 100), ("b", 900), ("c", 500)):
            self.db.add_voice_seconds("111", user, [("2026-08", seconds)], sessions=1)

        board = self.db.voice_month_leaderboard("111", "2026-08")

        self.assertEqual([row["user_id"] for row in board], ["b", "c", "a"])

    def test_the_leaderboard_respects_its_limit(self):
        for user in "abcdef":
            self.db.add_voice_seconds("111", user, [("2026-08", 100)], sessions=1)

        self.assertEqual(len(self.db.voice_month_leaderboard("111", "2026-08", limit=3)), 3)

    def test_rank_counts_only_members_ahead(self):
        for user, seconds in (("a", 100), ("b", 900), ("c", 500)):
            self.db.add_voice_seconds("111", user, [("2026-08", seconds)], sessions=1)

        self.assertEqual(self.db.voice_month_rank("111", "b", "2026-08"), 1)
        self.assertEqual(self.db.voice_month_rank("111", "c", "2026-08"), 2)
        self.assertEqual(self.db.voice_month_rank("111", "a", "2026-08"), 3)

    def test_a_member_with_no_time_has_no_rank(self):
        self.db.add_voice_seconds("111", "a", [("2026-08", 100)], sessions=1)

        self.assertIsNone(self.db.voice_month_rank("111", "ghost", "2026-08"))

    def test_history_comes_back_newest_first(self):
        for month in ("2026-06", "2026-07", "2026-08"):
            self.db.add_voice_seconds("111", "a", [(month, 100)], sessions=1)

        history = self.db.voice_member_history("111", "a")

        self.assertEqual([row["month"] for row in history], ["2026-08", "2026-07", "2026-06"])

    def test_the_month_summary_adds_up_the_server(self):
        for user, seconds in (("a", 100), ("b", 900)):
            self.db.add_voice_seconds("111", user, [("2026-08", seconds)], sessions=1)

        self.assertEqual(
            self.db.voice_month_summary("111", "2026-08"), {"members": 2, "seconds": 1000.0}
        )

    def test_an_export_carries_the_guild_voice_ledger_and_no_one_else_s(self):
        self.db.add_voice_seconds("111", "a", [("2026-08", 600)], sessions=1)
        self.db.add_voice_seconds("222", "z", [("2026-08", 600)], sessions=1)

        export = self.db.export_guild_data("111")

        self.assertEqual(export["counts"]["voice"], 1)
        self.assertEqual([row["user_id"] for row in export["voice"]], ["a"])


if __name__ == "__main__":
    unittest.main()
