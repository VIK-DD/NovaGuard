"""Direct contracts for extracted system health summaries and cards."""

import unittest
from datetime import UTC, datetime, timedelta

import cogs.system as system_cog
from core import system_presenters
from core.theme import Palette


class SystemCompatibilityTests(unittest.TestCase):
    def test_cog_reexports_presenters(self):
        for name in (
            "summarize_loop_lag",
            "ping_profile",
            "build_ping_embed",
            "build_uptime_embed",
            "build_botinfo_embed",
            "public_status_profile",
            "public_status_links",
            "build_public_status_embed",
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(system_cog, name), getattr(system_presenters, name))


class LoopLagTests(unittest.TestCase):
    def test_empty_samples_report_warmup(self):
        snapshot = system_presenters.summarize_loop_lag([])

        self.assertEqual(snapshot["label"], "Warming up")
        self.assertEqual(snapshot["latest"], 0)
        self.assertTrue(snapshot["line"].startswith("ℹ️"))

    def test_lag_thresholds_keep_their_existing_severity(self):
        cases = (
            ([10, 20], "Healthy", Palette.SUCCESS, "✅"),
            ([10, 800], "Small lag", Palette.WARNING, "⚠️"),
            ([10, 3000], "High lag", Palette.DANGER, "❌"),
            ([1000, 1000], "High lag", Palette.DANGER, "❌"),
        )

        for samples, label, color, prefix in cases:
            with self.subTest(samples=samples):
                snapshot = system_presenters.summarize_loop_lag(samples)
                self.assertEqual(snapshot["label"], label)
                self.assertEqual(snapshot["color"], color)
                self.assertTrue(snapshot["line"].startswith(prefix))
                self.assertNotIn("`", snapshot["details"])


class SystemCardTests(unittest.TestCase):
    def test_ping_boundaries_keep_green_yellow_and_red_profiles(self):
        self.assertEqual(system_presenters.ping_profile(149)[0], Palette.SUCCESS)
        self.assertEqual(system_presenters.ping_profile(150)[0], Palette.WARNING)
        self.assertEqual(system_presenters.ping_profile(299)[0], Palette.WARNING)
        self.assertEqual(system_presenters.ping_profile(300)[0], Palette.DANGER)

        embed = system_presenters.build_ping_embed(150, 25, timedelta(hours=2))
        fields = {field.name: field.value for field in embed.fields}
        self.assertEqual(embed.title, "🏓 Pong!")
        self.assertEqual(fields["🛰️ Gateway"], "`150ms`")
        self.assertEqual(fields["⚡ REST"], "`25ms`")

    def test_uptime_card_uses_the_supplied_clock(self):
        launched = datetime(2026, 8, 27, 8, 0, tzinfo=UTC)
        checked = launched + timedelta(hours=2, minutes=15)

        embed = system_presenters.build_uptime_embed(launched, checked)

        self.assertEqual(embed.title, "⏱️ Uptime")
        self.assertIn("2h 15m", embed.description)
        self.assertIn(f"<t:{int(launched.timestamp())}:R>", embed.description)

    def test_botinfo_card_preserves_every_runtime_stat(self):
        embed = system_presenters.build_botinfo_embed(
            bot_name="NovaGuard",
            avatar_url="https://example.com/bot.png",
            release={"version": "2.8", "phase_label": "Open Beta"},
            build_count=42,
            server_count=6,
            total_members=12_345,
            command_count=81,
            category_count=22,
            python_version="3.14.0",
            discord_version="2.6.4",
            gateway_ms=75,
            uptime=timedelta(days=1, hours=2),
        )
        fields = {field.name: field.value for field in embed.fields}

        self.assertEqual(embed.title, "🤖 NovaGuard")
        self.assertIn("2.8", embed.description)
        self.assertIn("12,345", fields["🌍 Reach"])
        self.assertIn("81", fields["🧩 Commands"])
        self.assertIn("Python `3.14.0`", fields["🐍 Runtime"])
        self.assertEqual(embed.thumbnail.url, "https://example.com/bot.png")

    def test_public_status_priority_is_maintenance_then_pressure_then_healthy(self):
        profile = system_presenters.public_status_profile

        self.assertEqual(profile(900, "High lag", True)[0], Palette.WARNING)
        self.assertIn("Maintenance", profile(900, "High lag", True)[1])
        self.assertEqual(profile(500, "Healthy", False)[0], Palette.DANGER)
        self.assertEqual(profile(50, "High lag", False)[0], Palette.DANGER)
        self.assertEqual(profile(250, "Healthy", False)[0], Palette.WARNING)
        self.assertEqual(profile(50, "Small lag", False)[0], Palette.WARNING)
        self.assertEqual(profile(50, "Healthy", False)[0], Palette.SUCCESS)

    def test_public_status_links_include_only_configured_destinations(self):
        self.assertEqual(
            system_presenters.public_status_links(
                "VIK-DD/NovaGuard",
                "VIK-DD",
                "https://status.example.com",
            ),
            [
                ("Repository", "https://github.com/VIK-DD/NovaGuard"),
                ("GitHub Profile", "https://github.com/VIK-DD"),
                ("Uptime", "https://status.example.com"),
            ],
        )
        self.assertEqual(system_presenters.public_status_links(), [])

    def test_public_status_card_preserves_health_build_and_project_details(self):
        embed = system_presenters.build_public_status_embed(
            bot_name="NovaGuard",
            avatar_url="https://example.com/bot.png",
            gateway_ms=80,
            uptime=timedelta(hours=4),
            lag={"label": "Healthy", "details": "latest 3ms • avg 2ms • peak 8ms"},
            maintenance_active=False,
            release={"version": "2.8", "phase_label": "Open Beta"},
            command_count=81,
            project_label="VIK-DD/NovaGuard",
        )
        fields = {field.name: field.value for field in embed.fields}

        self.assertEqual(embed.title, "🟢 NovaGuard Status")
        self.assertEqual(embed.color.value, Palette.SUCCESS)
        self.assertIn("Healthy", fields["Event Loop"])
        self.assertIn("81", fields["Build"])
        self.assertIn("VIK-DD/NovaGuard", fields["Project"])
        self.assertIn("Streaming", fields["Project"])


if __name__ == "__main__":
    unittest.main()
