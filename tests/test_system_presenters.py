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
            "build_doctor_runtime_lines",
            "build_doctor_config_lines",
            "build_doctor_permission_lines",
            "build_doctor_github_lines",
            "build_doctor_feature_lines",
            "doctor_profile",
            "build_doctor_embed",
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
            release={"version": "3.0", "phase_label": ""},
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
        self.assertIn("3.0", embed.description)
        self.assertNotIn("Open Beta", embed.description)
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
            release={"version": "3.0", "phase_label": ""},
            command_count=81,
            project_label="VIK-DD/NovaGuard",
        )
        fields = {field.name: field.value for field in embed.fields}

        self.assertEqual(embed.title, "🟢 NovaGuard Status")
        self.assertEqual(embed.color.value, Palette.SUCCESS)
        self.assertIn("Healthy", fields["Event Loop"])
        self.assertIn("81", fields["Build"])
        self.assertNotIn("Open Beta", fields["Build"])
        self.assertIn("VIK-DD/NovaGuard", fields["Project"])
        self.assertIn("Streaming", fields["Project"])


class DoctorPresenterTests(unittest.TestCase):
    def test_runtime_thresholds_preserve_gateway_and_ack_severity(self):
        healthy = system_presenters.build_doctor_runtime_lines(
            gateway_ms=299,
            ack_ms=999,
            lag_line="✅ **Event loop** — healthy",
            uptime=timedelta(hours=2),
            python_version="3.14.0",
            discord_version="2.6.4",
            cog_count=22,
            command_count=81,
        )
        slow = system_presenters.build_doctor_runtime_lines(
            gateway_ms=300,
            ack_ms=1000,
            lag_line="⚠️ **Event loop** — small lag",
            uptime=timedelta(),
            python_version="3.14.0",
            discord_version="2.6.4",
            cog_count=22,
            command_count=81,
        )

        self.assertTrue(healthy[0].startswith("✅"))
        self.assertTrue(healthy[1].startswith("✅"))
        self.assertTrue(slow[0].startswith("⚠️"))
        self.assertTrue(slow[1].startswith("⚠️"))
        self.assertIn("22 cogs • 81 slash commands", healthy[-1])

    def test_config_permissions_and_github_lines_keep_missing_states(self):
        config = system_presenters.build_doctor_config_lines(
            token_configured=False,
            env_found=False,
            guild_id=None,
            update_channel_id=None,
            github_channel_id=None,
            github_token_configured=False,
            anthropic_configured=False,
            error_channel_id=None,
        )
        permissions = system_presenters.build_doctor_permission_lines(
            [("Send Messages", True), ("Manage Roles", False)]
        )
        github = system_presenters.build_doctor_github_lines(
            username=None,
            primary_repo=None,
            watch_repos=(),
            poll_seconds=90,
        )

        self.assertTrue(config[0].startswith("❌"))
        self.assertTrue(config[-1].startswith("ℹ️"))
        self.assertTrue(permissions[0].startswith("✅"))
        self.assertTrue(permissions[1].startswith("⚠️"))
        self.assertEqual(github[-1], "✅ **Polling** — every 90s")

    def test_feature_lines_prioritize_maintenance_over_stream_loop(self):
        lines = system_presenters.build_doctor_feature_lines(
            maintenance_state={"enabled": True, "message": "Deploying"},
            stream_running=True,
            stream_interval_seconds=60,
            update_channel_id=123,
            github_watcher_running=True,
            error_digest_line="✅ **Error digest** — ready",
        )

        self.assertEqual(lines[0], "⚠️ **Maintenance mode** — Deploying")
        self.assertEqual(lines[1], "ℹ️ **Streaming status** — paused while maintenance is active")
        self.assertTrue(lines[2].startswith("✅"))
        self.assertTrue(lines[3].startswith("✅"))

    def test_doctor_profile_counts_only_errors_and_warnings(self):
        danger = system_presenters.doctor_profile(
            ["❌ broken", "⚠️ note", "ℹ️ context", "✅ fine"]
        )
        warning = system_presenters.doctor_profile(["⚠️ note", "ℹ️ context"])
        healthy = system_presenters.doctor_profile(["ℹ️ context", "✅ fine"])

        self.assertEqual(danger[2], Palette.DANGER)
        self.assertIn("1 issue(s)", danger[1])
        self.assertIn("1 note(s)", danger[1])
        self.assertEqual(warning[2], Palette.WARNING)
        self.assertEqual(healthy[2], Palette.SUCCESS)

    def test_doctor_card_preserves_section_order_and_footer(self):
        embed = system_presenters.build_doctor_embed(
            runtime_lines=["✅ pulse"],
            config_lines=["✅ config"],
            storage_lines=["✅ storage"],
            permission_lines=["✅ permissions"],
            github_lines=["✅ github"],
            feature_lines=["✅ features"],
        )

        self.assertEqual(embed.title, "🩺 Doctor Check • All systems healthy")
        self.assertEqual(embed.color.value, Palette.SUCCESS)
        self.assertEqual(
            [field.name for field in embed.fields],
            ["Pulse", "Configuration", "Storage", "Permissions", "GitHub", "Feature Notes"],
        )
        self.assertEqual(embed.footer.text, "Developed by VIK & CloudMedia")


if __name__ == "__main__":
    unittest.main()
