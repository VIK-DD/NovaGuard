"""The public status card: what it claims, and when it is due.

Two separable jobs, both testable without Discord or a network. Deciding a
slot is due is arithmetic on a clock. Rendering the card is a function of a
snapshot. The cog does the probing and the posting; neither is here.

A status panel earns its place only by being right when something is wrong,
so most of these tests are about the unhappy cases.
"""

import os
import sys
import unittest
from datetime import UTC, datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.status_panel import (  # noqa: E402
    build_snapshot,
    build_status_embed,
    due_slot,
    overall_state,
    status_message_is_stale,
    status_schedule,
    status_schedule_label,
)

CHISINAU = ZoneInfo("Europe/Chisinau")


def snapshot(**overrides):
    base = dict(
        bot_ready=True,
        latency_ms=42,
        api_ok=True,
        api_detail="responding",
        database_ok=True,
        maintenance={"enabled": False, "message": ""},
        uptime_seconds=3 * 3600,
        guilds=12,
        members=3400,
        generated_at=datetime(2026, 8, 19, 7, 0, tzinfo=UTC),
    )
    base.update(overrides)
    return build_snapshot(**base)


class ScheduleTests(unittest.TestCase):
    def test_the_default_is_morning_and_evening(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("STATUS_SCHEDULE", None)
            self.assertEqual(status_schedule(), ((7, 0), (19, 0)))

    def test_the_schedule_can_be_overridden(self):
        with mock.patch.dict(os.environ, {"STATUS_SCHEDULE": "06:30,12:00,22:15"}):
            self.assertEqual(status_schedule(), ((6, 30), (12, 0), (22, 15)))

    def test_the_label_names_the_timezone_it_means(self):
        # "07:00" alone is useless to anyone reading from another country.
        label = status_schedule_label()

        self.assertIn("07:00", label)
        self.assertIn("Europe/Chisinau", label)


class DueSlotTests(unittest.TestCase):
    """A slot is the minute a post is owed, expressed in the operator's clock."""

    def at(self, hour, minute, tz=CHISINAU):
        return datetime(2026, 8, 19, hour, minute, tzinfo=tz)

    def test_the_morning_slot_is_due_on_the_minute(self):
        self.assertEqual(due_slot(self.at(7, 0)), "2026-08-19 07:00")

    def test_the_evening_slot_is_due_too(self):
        self.assertEqual(due_slot(self.at(19, 0)), "2026-08-19 19:00")

    def test_a_minute_either_side_is_not_due(self):
        self.assertIsNone(due_slot(self.at(6, 59)))
        self.assertIsNone(due_slot(self.at(7, 1)))

    def test_the_slot_is_read_in_the_configured_timezone_not_utc(self):
        # 04:00 UTC is 07:00 in Chisinau during summer time. Reading the raw
        # UTC hour would post at the wrong time of day for the whole year.
        utc_moment = datetime(2026, 8, 19, 4, 0, tzinfo=UTC)

        self.assertEqual(due_slot(utc_moment), "2026-08-19 07:00")

    def test_two_posts_in_one_day_carry_different_slots(self):
        # The loop skips a slot it has already served, so the two must differ.
        self.assertNotEqual(due_slot(self.at(7, 0)), due_slot(self.at(19, 0)))


class MessageLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)

    def test_a_card_younger_than_fourteen_days_is_edited(self):
        created_at = self.now - timedelta(days=13, hours=23, minutes=59)

        self.assertFalse(status_message_is_stale(created_at, now=self.now))

    def test_a_card_is_replaced_once_it_reaches_fourteen_days(self):
        created_at = self.now - timedelta(days=14)

        self.assertTrue(status_message_is_stale(created_at, now=self.now))

    def test_an_unknown_creation_time_is_treated_as_stale(self):
        self.assertTrue(status_message_is_stale(None, now=self.now))


class OverallStateTests(unittest.TestCase):
    def test_everything_up_reads_as_operational(self):
        self.assertEqual(overall_state(snapshot()), "operational")

    def test_a_failing_component_degrades_the_whole_card(self):
        self.assertEqual(overall_state(snapshot(database_ok=False)), "degraded")
        self.assertEqual(overall_state(snapshot(api_ok=False)), "degraded")
        self.assertEqual(overall_state(snapshot(bot_ready=False)), "degraded")

    def test_maintenance_outranks_a_failing_component(self):
        # During maintenance things are expected to be down; calling that
        # "degraded" would send people chasing a fault that is not one.
        state = overall_state(
            snapshot(database_ok=False, maintenance={"enabled": True, "message": "Upgrading"})
        )

        self.assertEqual(state, "maintenance")


class EmbedTests(unittest.TestCase):
    def body(self, snap):
        embed = build_status_embed(snap)
        parts = [embed.title or "", embed.description or ""]
        parts += [f.name + " " + f.value for f in embed.fields]
        return "\n".join(parts)

    def test_every_row_stacks_instead_of_sitting_three_to_a_line(self):
        # Discord packs inline fields side by side on desktop, which squeezes
        # each row into a narrow column and wraps its detail. Mobile stacks
        # them anyway, so inline only ever made the desktop view worse.
        embed = build_status_embed(snapshot())

        self.assertTrue(
            all(not field.inline for field in embed.fields),
            "a field is still inline: " + ", ".join(f.name for f in embed.fields if f.inline),
        )

    def test_every_component_is_named_on_the_card(self):
        text = self.body(snapshot())

        for label in ("NovaGuard", "Dashboard API", "Database"):
            self.assertIn(label, text)

    def test_a_healthy_card_says_all_operational(self):
        self.assertIn("All Operational", self.body(snapshot()))

    def test_a_failing_component_is_marked_not_quietly_dropped(self):
        text = self.body(snapshot(database_ok=False))

        self.assertIn("Database", text)
        self.assertIn("🔴", text)
        self.assertNotIn("All Operational", text)

    def test_a_failing_row_does_not_say_the_same_thing_twice(self):
        # "🔴 Not responding" followed by "not responding" is noise.
        text = self.body(snapshot(database_ok=False))

        self.assertEqual(text.lower().count("not responding"), 1)

    def test_maintenance_leaves_healthy_components_reading_as_healthy(self):
        # The banner carries the maintenance state. Painting a component amber
        # while it says "Operational" contradicts itself, and hides whether
        # anything is actually broken underneath the maintenance window.
        text = self.body(
            snapshot(maintenance={"enabled": True, "message": "Upgrading"})
        )

        self.assertIn("🟢", text)
        self.assertIn("Under Maintenance", text)

    def test_maintenance_still_shows_a_genuinely_broken_component_as_broken(self):
        text = self.body(
            snapshot(database_ok=False, maintenance={"enabled": True, "message": "Upgrading"})
        )

        self.assertIn("🔴", text)

    def test_maintenance_shows_the_operators_own_message(self):
        text = self.body(
            snapshot(maintenance={"enabled": True, "message": "Upgrading the database"})
        )

        self.assertIn("Upgrading the database", text)

    def test_uptime_is_written_for_people_not_in_seconds(self):
        text = self.body(snapshot(uptime_seconds=90000))

        self.assertNotIn("90000", text)
        self.assertIn("1d", text)

    def test_the_servers_line_reports_reach(self):
        text = self.body(snapshot(guilds=12, members=3400))

        self.assertIn("12", text)
        self.assertIn("3,400", text)

    def test_one_server_is_not_written_as_servers(self):
        self.assertIn("1 server", self.body(snapshot(guilds=1, members=5)))

    def test_latency_is_shown_when_the_bot_is_up(self):
        self.assertIn("42", self.body(snapshot(latency_ms=42)))

    def test_an_unreachable_api_explains_itself(self):
        # The detail is rendered with a capital first letter, so the reason
        # still comes through — just tidier than the raw lowercase probe text.
        text = self.body(snapshot(api_ok=False, api_detail="no response in 5s"))

        self.assertIn("No response in 5s", text)

    def test_a_lowercase_detail_is_capitalised_for_the_card(self):
        text = self.body(snapshot(database_ok=True))

        self.assertIn("Responding", text)
        self.assertNotIn("\nresponding", text)

    def test_a_detail_that_starts_with_a_number_is_left_alone(self):
        # "101 ms to Discord" reads fine; upper-casing a digit would do nothing
        # and must not mangle the rest.
        text = self.body(snapshot(latency_ms=101))

        self.assertIn("101 ms to Discord", text)

    def test_the_colour_reflects_the_state(self):
        healthy = build_status_embed(snapshot()).color
        broken = build_status_embed(snapshot(database_ok=False)).color
        paused = build_status_embed(
            snapshot(maintenance={"enabled": True, "message": "x"})
        ).color

        self.assertNotEqual(healthy, broken)
        self.assertNotEqual(healthy, paused)
        self.assertNotEqual(broken, paused)

    def test_the_card_names_its_next_refresh(self):
        # Readers need to know whether a green card is fresh or from yesterday.
        morning = datetime(2026, 8, 19, 8, 0, tzinfo=CHISINAU)

        text = self.body(snapshot(generated_at=morning))

        self.assertIn("Next refresh", text)
        self.assertIn("19:00", text)

    def test_the_last_slot_of_the_day_points_at_tomorrow_morning(self):
        evening = datetime(2026, 8, 19, 20, 0, tzinfo=CHISINAU)

        text = self.body(snapshot(generated_at=evening))

        self.assertIn("07:00", text)

    def test_the_next_refresh_names_the_clock_a_reader_recognises(self):
        # "Europe/Chisinau" is a database key, not a time. Someone glancing at
        # the card wants the zone people actually say out loud.
        summer = datetime(2026, 8, 19, 8, 0, tzinfo=CHISINAU)

        text = self.body(snapshot(generated_at=summer))

        self.assertIn("19:00 EEST", text)
        self.assertNotIn("Europe/Chisinau", text)

    def test_the_clock_follows_daylight_saving_rather_than_a_fixed_string(self):
        # Same zone, January: EET, not EEST. Hardcoding either one is wrong for
        # half the year, and a status card that misstates the hour is worse
        # than one that omits it.
        winter = datetime(2026, 1, 15, 8, 0, tzinfo=CHISINAU)

        self.assertIn("19:00 EET", self.body(snapshot(generated_at=winter)))

    def test_the_rows_are_not_padded_with_blank_lines(self):
        # A zero-width space on its own line buys a gap Discord already puts
        # between stacked fields. Two gaps read as a card that has come apart.
        for field in build_status_embed(snapshot()).fields:
            self.assertNotIn("​", field.value)


if __name__ == "__main__":
    unittest.main()
