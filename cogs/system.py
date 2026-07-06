"""⚙️ System category — bot status, help hub, and the automatic update changelog."""

import asyncio
import json
import os
import platform
import time
from collections import deque
from datetime import UTC, datetime

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from core import updates
from core.backups import BACKUP_DIR, create_backup
from core.config import (
    BOT_CODENAME,
    BOT_VERSION,
    BASE_DIR,
    ERROR_LOG_CHANNEL_ID,
    GITHUB_STATE_FILE,
    GUILD_ID,
    STREAM_URL,
    UPDATE_STATE_FILE,
    github_config,
    stream_statuses,
)
from core.database import DB_PATH
from core.error_digest import send_error_digest
from core.github_api import github_api
from core.maintenance import (
    DEFAULT_MAINTENANCE_MESSAGE,
    load_maintenance_state,
    save_maintenance_state,
    user_can_bypass_maintenance,
)
from core.storage import DATA_DIR, get_guild_settings
from core.theme import Palette, brand_footer, make_embed
from core.utils import build_link_view, format_timedelta, respond, truncate

LAG_MONITOR_SECONDS = 5
BACKUP_INTERVAL_HOURS = 6
HEALTH_ALERT_COOLDOWN_SECONDS = 900
HIGH_LAG_ALERT_MS = 3000
HIGH_LAG_STREAK_REQUIRED = 2
IGNORE_HUGE_LAG_MS = 60000
PRESENCE_ERROR_LOG_COOLDOWN_SECONDS = 180
STARTUP_UPDATE_INITIAL_DELAY_SECONDS = 12
STARTUP_UPDATE_RETRY_DELAY_SECONDS = 20
STARTUP_UPDATE_MAX_ATTEMPTS = 6


def command_line_entries(command, prefix=""):
    current = f"{prefix} {command.name}".strip()
    if isinstance(command, app_commands.Group):
        lines = []
        for subcommand in command.commands:
            lines.extend(command_line_entries(subcommand, current))
        return lines or [f"`/{current}` — {command.description}"]
    return [f"`/{current}` — {command.description}"]


def cog_command_lines(cog):
    lines = []
    for command in cog.get_app_commands():
        lines.extend(command_line_entries(command))
    return lines


def build_category_embed(cog):
    emoji = getattr(cog, "EMOJI", "📦")
    color = getattr(cog, "COLOR", Palette.PRIMARY)
    description = getattr(cog, "DESCRIPTION", "")
    lines = cog_command_lines(cog)

    embed = make_embed(
        f"{emoji} {cog.qualified_name}",
        f"{description}\n\n" + "\n".join(lines),
        color=color,
    )
    brand_footer(embed, f"{len(lines)} command(s) in this category")
    return embed


def build_help_home_embed(bot):
    lines = []
    total = 0
    for name, cog in bot.cogs.items():
        commands_count = len(cog_command_lines(cog))
        total += commands_count
        emoji = getattr(cog, "EMOJI", "📦")
        description = getattr(cog, "DESCRIPTION", "Commands")
        lines.append(f"{emoji} **{name}** `{commands_count}` — {description}")

    embed = make_embed(
        "🌈 Command Hub",
        "Everything is a **slash command** now — type `/` and explore!\n"
        "Pick a category from the menu below for the full list.\n\n" + "\n".join(lines),
        color=Palette.PRIMARY,
    )
    embed.add_field(
        name="Quick Stats",
        value=f"Categories: `{len(bot.cogs)}` • Commands: `{total}` • Version: `v{BOT_VERSION} \"{BOT_CODENAME}\"`",
        inline=False,
    )
    brand_footer(embed, "Help hub")
    return embed


def ok_line(label, details=""):
    return f"✅ **{label}**" + (f" — {details}" if details else "")


def warn_line(label, details=""):
    return f"⚠️ **{label}**" + (f" — {details}" if details else "")


def info_line(label, details=""):
    return f"ℹ️ **{label}**" + (f" — {details}" if details else "")


def fail_line(label, details=""):
    return f"❌ **{label}**" + (f" — {details}" if details else "")


def clamp_field(lines, limit=1010):
    value = "\n".join(lines) if lines else "No checks were run."
    return value if len(value) <= limit else value[: limit - 3] + "..."


def json_file_status(path, label):
    if not path.exists():
        return warn_line(label, "not created yet")
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return fail_line(label, "invalid JSON")
    except OSError as error:
        return fail_line(label, truncate(str(error), 80))
    return ok_line(label, "valid JSON")


def storage_health_lines():
    lines = [
        ok_line("SQLite database", "ready") if DB_PATH.exists() else info_line("SQLite database", "will be created on first setup"),
        json_file_status(UPDATE_STATE_FILE, ".update_state.json"),
        json_file_status(GITHUB_STATE_FILE, ".github_state.json"),
    ]

    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        probe_file = DATA_DIR / ".doctor_write_test.tmp"
        probe_file.write_text("ok", encoding="utf-8")
        probe_file.unlink(missing_ok=True)
        lines.append(ok_line("data/", "writable"))
    except OSError as error:
        lines.append(fail_line("data/", truncate(str(error), 80)))

    data_files = sorted(DATA_DIR.glob("*.json")) if DATA_DIR.exists() else []
    if not data_files:
        lines.append(warn_line("feature data", "no JSON files yet"))
        return lines

    broken = []
    for path in data_files:
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            broken.append(path.name)

    if broken:
        lines.append(fail_line("feature data", "broken: " + ", ".join(broken[:5])))
    else:
        lines.append(ok_line("feature data", f"{len(data_files)} JSON file(s) valid"))

    backup_count = len(list(BACKUP_DIR.glob("novaguard-backup-*.zip"))) if BACKUP_DIR.exists() else 0
    lines.append(ok_line("backups", f"{backup_count} archive(s), auto every {BACKUP_INTERVAL_HOURS}h"))
    return lines


class HelpSelect(discord.ui.Select):
    def __init__(self, bot):
        options = [
            discord.SelectOption(
                label="Overview",
                value="__home__",
                emoji="🌈",
                description="Back to the category overview",
            )
        ]
        for name, cog in bot.cogs.items():
            options.append(
                discord.SelectOption(
                    label=name,
                    value=name,
                    emoji=getattr(cog, "EMOJI", "📦"),
                    description=truncate(getattr(cog, "DESCRIPTION", "Commands"), 90),
                )
            )
        super().__init__(placeholder="Pick a category to explore…", options=options[:25])
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "__home__":
            embed = build_help_home_embed(self.bot)
        else:
            cog = self.bot.cogs.get(self.values[0])
            embed = build_category_embed(cog) if cog else build_help_home_embed(self.bot)
        await interaction.response.edit_message(embed=embed)


class HelpView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=300)
        self.add_item(HelpSelect(bot))


class Paginator(discord.ui.View):
    def __init__(self, embeds, user_id):
        super().__init__(timeout=300)
        self.embeds = embeds
        self.user_id = user_id
        self.index = 0
        self._sync_buttons()

    def _sync_buttons(self):
        self.previous_page.disabled = self.index == 0
        self.next_page.disabled = self.index >= len(self.embeds) - 1
        self.counter.label = f"{self.index + 1}/{len(self.embeds)}"

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Start your own session to flip these pages!", ephemeral=True)
            return False
        return True

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.secondary)
    async def previous_page(self, interaction, button):
        self.index = max(self.index - 1, 0)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.gray, disabled=True)
    async def counter(self, interaction, button):
        pass

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction, button):
        self.index = min(self.index + 1, len(self.embeds) - 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)


class System(commands.Cog):
    """Bot status, diagnostics and the automatic update changelog."""

    EMOJI = "⚙️"
    COLOR = Palette.PRIMARY
    DESCRIPTION = "Bot status, diagnostics, help and the automatic update changelog."

    def __init__(self, bot):
        self.bot = bot
        self.status_index = 0
        self.startup_update_task = None
        self.loop_lag_samples = deque(maxlen=60)
        self.loop_lag_last_tick = None
        self.high_lag_streak = 0
        self.last_lag_alert_at = 0
        self.last_reconnect_alert_at = 0
        self.last_presence_error_log_at = 0

    async def cog_load(self):
        self.rotate_stream_status.start()
        self.monitor_event_loop.start()
        self.backup_loop.start()

    async def cog_unload(self):
        self.rotate_stream_status.cancel()
        self.monitor_event_loop.cancel()
        self.backup_loop.cancel()
        if self.startup_update_task and not self.startup_update_task.done():
            self.startup_update_task.cancel()

    def loop_lag_snapshot(self):
        samples = list(self.loop_lag_samples)
        if not samples:
            return {
                "label": "Warming up",
                "line": info_line("Event loop", "collecting lag samples"),
                "details": "Collecting samples",
                "color": Palette.INFO,
                "latest": 0,
                "average": 0,
                "peak": 0,
            }

        latest = samples[-1]
        average = sum(samples) / len(samples)
        peak = max(samples)

        details = f"latest `{latest:.0f}ms` • avg `{average:.0f}ms` • peak `{peak:.0f}ms`"
        if peak >= 3000 or average >= 1000:
            label = "High lag"
            line = fail_line("Event loop", details)
            color = Palette.DANGER
        elif peak >= 800 or average >= 250:
            label = "Small lag"
            line = warn_line("Event loop", details)
            color = Palette.WARNING
        else:
            label = "Healthy"
            line = ok_line("Event loop", details)
            color = Palette.SUCCESS

        return {
            "label": label,
            "line": line,
            "details": details.replace("`", ""),
            "color": color,
            "latest": latest,
            "average": average,
            "peak": peak,
        }

    def maintenance_state(self):
        return load_maintenance_state()

    async def apply_stream_presence(self, advance=True):
        try:
            await self.bot.change_presence(
                status=discord.Status.online,
                activity=discord.Streaming(
                    name=stream_statuses[self.status_index],
                    url=STREAM_URL,
                ),
            )
        except (
            discord.HTTPException,
            discord.ConnectionClosed,
            aiohttp.ClientError,
            asyncio.TimeoutError,
        ) as error:
            now = time.perf_counter()
            if now - self.last_presence_error_log_at >= PRESENCE_ERROR_LOG_COOLDOWN_SECONDS:
                self.last_presence_error_log_at = now
                print(f"Streaming status update skipped due to temporary connection issue: {error}")
            return False

        if advance:
            self.status_index = (self.status_index + 1) % len(stream_statuses)
        return True

    async def apply_maintenance_presence(self, state=None):
        state = state or self.maintenance_state()
        try:
            await self.bot.change_presence(
                status=discord.Status.dnd,
                activity=discord.Game(name=state.get("message") or DEFAULT_MAINTENANCE_MESSAGE),
            )
        except (
            discord.HTTPException,
            discord.ConnectionClosed,
            aiohttp.ClientError,
            asyncio.TimeoutError,
        ) as error:
            now = time.perf_counter()
            if now - self.last_presence_error_log_at >= PRESENCE_ERROR_LOG_COOLDOWN_SECONDS:
                self.last_presence_error_log_at = now
                print(f"Maintenance status update skipped due to temporary connection issue: {error}")
            return False
        return True

    async def refresh_presence_mode(self):
        ws = getattr(self.bot, "ws", None)
        ws_open = bool(ws and not getattr(ws, "closed", False))
        if self.bot.is_closed() or not self.bot.is_ready() or not ws_open:
            return False

        state = self.maintenance_state()
        if state.get("enabled"):
            return await self.apply_maintenance_presence(state)
        return await self.apply_stream_presence(advance=False)

    async def ensure_maintenance_manager(self, interaction):
        if await user_can_bypass_maintenance(self.bot, interaction.user):
            return True

        embed = make_embed(
            "🔒 Owner Only",
            "Only the bot owner can enable or disable global maintenance mode.",
            color=Palette.DANGER,
        )
        brand_footer(embed, "Maintenance control")
        await respond(interaction, embed, ephemeral=True)
        return False

    async def announce_startup_updates_later(self):
        await asyncio.sleep(STARTUP_UPDATE_INITIAL_DELAY_SECONDS)
        for attempt in range(1, STARTUP_UPDATE_MAX_ATTEMPTS + 1):
            try:
                sent = await asyncio.wait_for(updates.announce_startup_updates(self.bot), timeout=25)
                if sent:
                    if attempt == 1:
                        print("Startup updates delivered.")
                    else:
                        print(f"Startup updates delivered on retry attempt {attempt}.")
                    return

                if not await asyncio.to_thread(updates.has_pending_announcement):
                    print("Startup updates skipped: nothing pending to deliver.")
                    return

                if attempt < STARTUP_UPDATE_MAX_ATTEMPTS:
                    print(
                        "Startup updates pending: Discord was not ready for delivery. "
                        f"Retrying in {STARTUP_UPDATE_RETRY_DELAY_SECONDS}s... attempt {attempt}"
                    )
            except asyncio.TimeoutError:
                if attempt < STARTUP_UPDATE_MAX_ATTEMPTS:
                    print(
                        "Startup updates delayed: Discord was too slow to respond. "
                        f"Retrying in {STARTUP_UPDATE_RETRY_DELAY_SECONDS}s... attempt {attempt}"
                    )
                else:
                    print("Startup updates still pending: Discord did not respond quickly enough.")
            except (discord.HTTPException, aiohttp.ClientError) as error:
                if attempt < STARTUP_UPDATE_MAX_ATTEMPTS:
                    print(
                        "Startup updates delayed by a temporary network issue: "
                        f"{error}. Retrying in {STARTUP_UPDATE_RETRY_DELAY_SECONDS}s... attempt {attempt}"
                    )
                else:
                    print(f"Startup updates still pending due to temporary network issue: {error}")
            except Exception as error:
                print(f"Startup updates skipped due to unexpected issue: {error!r}")
                await send_error_digest(
                    self.bot,
                    "Startup Update Error",
                    error,
                    context="Automatic startup changelog failed.",
                )
                return

            if attempt < STARTUP_UPDATE_MAX_ATTEMPTS:
                await asyncio.sleep(STARTUP_UPDATE_RETRY_DELAY_SECONDS)

        print("Startup updates remain pending. NovaGuard will try again after the next ready/reconnect event.")

    def schedule_startup_update_retry(self):
        if self.startup_update_task and not self.startup_update_task.done():
            return
        self.startup_update_task = asyncio.create_task(self.announce_startup_updates_later())

    @tasks.loop(seconds=LAG_MONITOR_SECONDS)
    async def monitor_event_loop(self):
        now = time.perf_counter()
        if self.loop_lag_last_tick is None:
            self.loop_lag_last_tick = now
            return

        elapsed = now - self.loop_lag_last_tick
        lag_ms = max(0, (elapsed - LAG_MONITOR_SECONDS) * 1000)
        self.loop_lag_last_tick = now

        # Ignore one-off giant spikes caused by suspend/restart/network stalls;
        # they are useful to note in logs, but too noisy for admin panic alerts.
        if lag_ms >= IGNORE_HUGE_LAG_MS:
            self.high_lag_streak = 0
            print(f"Event-loop lag spike ignored as transient: {lag_ms:.0f}ms")
            return

        self.loop_lag_samples.append(lag_ms)
        if lag_ms >= HIGH_LAG_ALERT_MS:
            self.high_lag_streak += 1
        else:
            self.high_lag_streak = 0

        if (
            self.high_lag_streak >= HIGH_LAG_STREAK_REQUIRED
            and now - self.last_lag_alert_at >= HEALTH_ALERT_COOLDOWN_SECONDS
        ):
            self.last_lag_alert_at = now
            await send_error_digest(
                self.bot,
                "Health Alert",
                RuntimeError(
                    f"High event-loop lag detected: {lag_ms:.0f}ms "
                    f"for {self.high_lag_streak} consecutive checks"
                ),
                context=(
                    "NovaGuard detected repeated event-loop lag on the Raspberry Pi, "
                    "which can cause Discord timeouts or slow slash-command responses."
                ),
            )
            self.high_lag_streak = 0

    @monitor_event_loop.before_loop
    async def before_monitor_event_loop(self):
        await self.bot.wait_until_ready()
        self.loop_lag_last_tick = time.perf_counter()

    @tasks.loop(hours=BACKUP_INTERVAL_HOURS)
    async def backup_loop(self):
        try:
            backup = await asyncio.to_thread(create_backup, "auto")
            print(f"Automatic backup created: {backup['name']}")
        except Exception as error:
            print(f"Automatic backup failed: {error!r}")
            await send_error_digest(self.bot, "Automatic Backup Error", error, context="Scheduled backup failed.")

    @backup_loop.before_loop
    async def before_backup_loop(self):
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=30)
    async def rotate_stream_status(self):
        if self.maintenance_state().get("enabled"):
            return

        ws = getattr(self.bot, "ws", None)
        ws_open = bool(ws and not getattr(ws, "closed", False))
        if self.bot.is_closed() or not self.bot.is_ready() or not ws_open:
            return

        await self.apply_stream_presence()

    @rotate_stream_status.before_loop
    async def before_rotate_stream_status(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_ready(self):
        await self.refresh_presence_mode()
        if getattr(self.bot, "startup_update_announced", False):
            now = time.monotonic()
            if now - self.last_reconnect_alert_at >= HEALTH_ALERT_COOLDOWN_SECONDS:
                self.last_reconnect_alert_at = now
                await send_error_digest(
                    self.bot,
                    "Gateway Reconnect",
                    RuntimeError("Discord gateway reconnected after the bot was already ready."),
                    context="This can happen during network hiccups. If it repeats often, check host/network stability.",
                )
            if await asyncio.to_thread(updates.has_pending_announcement):
                self.schedule_startup_update_retry()
        if not getattr(self.bot, "startup_update_announced", False):
            self.bot.startup_update_announced = True
            self.schedule_startup_update_retry()
        print(f"{self.bot.user} is ready")

    @app_commands.command(name="ping", description="Latency, uptime and gateway health at a glance")
    async def ping(self, interaction: discord.Interaction):
        gateway_ms = round(self.bot.latency * 1000)
        started = time.perf_counter()
        await interaction.response.defer()
        rest_ms = round((time.perf_counter() - started) * 1000)

        if gateway_ms < 150:
            color, mood = Palette.SUCCESS, "Feeling fast today ⚡"
        elif gateway_ms < 300:
            color, mood = Palette.WARNING, "A little sleepy 😴"
        else:
            color, mood = Palette.DANGER, "Running through molasses 🐌"

        embed = make_embed("🏓 Pong!", mood, color=color)
        embed.add_field(name="🛰️ Gateway", value=f"`{gateway_ms}ms`", inline=True)
        embed.add_field(name="⚡ REST", value=f"`{rest_ms}ms`", inline=True)
        embed.add_field(
            name="⏱️ Uptime",
            value=f"`{format_timedelta(datetime.now(UTC) - self.bot.launched_at)}`",
            inline=True,
        )
        brand_footer(embed, "Pulse check")
        await respond(interaction, embed)

    @app_commands.command(name="uptime", description="How long the bot has been online")
    async def uptime(self, interaction: discord.Interaction):
        await interaction.response.defer()
        delta = datetime.now(UTC) - self.bot.launched_at
        embed = make_embed(
            "⏱️ Uptime",
            f"Online for **{format_timedelta(delta)}**\nBooted {discord.utils.format_dt(self.bot.launched_at, 'R')}",
            color=Palette.TEAL,
        )
        brand_footer(embed, "Still going strong")
        await respond(interaction, embed)

    @app_commands.command(name="botinfo", description="Version, build, runtime and live stats")
    async def botinfo(self, interaction: discord.Interaction):
        await interaction.response.defer()
        history = updates.load_update_state().get("history", [])
        total_members = sum(guild.member_count or 0 for guild in self.bot.guilds)
        command_count = len(list(self.bot.tree.walk_commands()))

        embed = make_embed(
            f"🤖 {self.bot.user.name}",
            f"v`{BOT_VERSION}` **\"{BOT_CODENAME}\"** — the slash-command era.",
            color=Palette.PRIMARY,
        )
        if self.bot.user.display_avatar:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.add_field(
            name="🏗️ Build",
            value=f"Builds shipped: `{len(history)}`\nAuto-changelog: `Active`",
            inline=True,
        )
        embed.add_field(
            name="🌍 Reach",
            value=f"Servers: `{len(self.bot.guilds)}`\nMembers: `{total_members:,}`",
            inline=True,
        )
        embed.add_field(
            name="🧩 Commands",
            value=f"Slash commands: `{command_count}`\nCategories: `{len(self.bot.cogs)}`",
            inline=True,
        )
        embed.add_field(
            name="🐍 Runtime",
            value=(
                f"Python `{platform.python_version()}`\n"
                f"discord.py `{discord.__version__}`\n"
                f"Gateway `{round(self.bot.latency * 1000)}ms`"
            ),
            inline=True,
        )
        embed.add_field(
            name="⏱️ Uptime",
            value=f"`{format_timedelta(datetime.now(UTC) - self.bot.launched_at)}`",
            inline=True,
        )
        brand_footer(embed, "Bot info")
        await respond(interaction, embed)

    @app_commands.command(name="status", description="Public bot status: uptime, latency and project links")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer()
        gateway_ms = round(self.bot.latency * 1000)
        uptime = datetime.now(UTC) - self.bot.launched_at
        lag = self.loop_lag_snapshot()
        maintenance_active = self.maintenance_state().get("enabled")

        if maintenance_active:
            color = Palette.WARNING
            mood = "Maintenance mode is active. Core systems are online, but commands are limited."
        elif gateway_ms >= 500 or lag["label"] == "High lag":
            color = Palette.DANGER
            mood = "Online, but the Raspberry Pi is feeling pressure."
        elif gateway_ms >= 250 or lag["label"] == "Small lag":
            color = Palette.WARNING
            mood = "Online with a little latency wobble."
        else:
            color = Palette.SUCCESS
            mood = "Online, responsive and ready."

        embed = make_embed(
            f"🟢 {self.bot.user.name} Status",
            mood,
            color=color,
        )
        if self.bot.user.display_avatar:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.add_field(name="Gateway", value=f"`{gateway_ms}ms`", inline=True)
        embed.add_field(name="Event Loop", value=f"`{lag['label']}`\n{lag['details']}", inline=True)
        embed.add_field(name="Uptime", value=f"`{format_timedelta(uptime)}`", inline=True)
        embed.add_field(
            name="Build",
            value=f"v`{BOT_VERSION}` **\"{BOT_CODENAME}\"**\nSlash commands: `{len(list(self.bot.tree.walk_commands()))}`",
            inline=True,
        )
        embed.add_field(
            name="Project",
            value=(
                f"GitHub: `{github_config.primary_repo or github_config.username or 'Not configured'}`\n"
                f"Presence: `{'Maintenance' if maintenance_active else 'Streaming'}`"
            ),
            inline=True,
        )
        brand_footer(embed, "Public status")

        buttons = []
        if github_config.primary_repo:
            buttons.append(("Repository", f"https://github.com/{github_config.primary_repo}"))
        if github_config.username:
            buttons.append(("GitHub Profile", f"https://github.com/{github_config.username}"))
        if github_config.uptime_url:
            buttons.append(("Uptime", github_config.uptime_url))
        await respond(interaction, embed, view=build_link_view(buttons))

    @app_commands.command(name="doctor", description="Deep health check for the bot, config and integrations")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def doctor(self, interaction: discord.Interaction):
        started = time.perf_counter()
        await interaction.response.defer(ephemeral=True)
        ack_ms = round((time.perf_counter() - started) * 1000)

        gateway_ms = round(self.bot.latency * 1000)
        uptime = datetime.now(UTC) - self.bot.launched_at
        command_count = len(list(self.bot.tree.walk_commands()))
        lag = self.loop_lag_snapshot()
        guild_settings = get_guild_settings(interaction.guild_id)
        update_channel_id = guild_settings.get("update_channel") or github_config.update_channel_id
        github_channel_id = guild_settings.get("github_event_channel") or github_config.event_channel_id
        error_channel_id = guild_settings.get("error_log_channel") or ERROR_LOG_CHANNEL_ID
        runtime_lines = [
            ok_line("Gateway", f"{gateway_ms}ms") if gateway_ms < 300 else warn_line("Gateway", f"{gateway_ms}ms, a little slow"),
            ok_line("Discord ACK", f"{ack_ms}ms") if ack_ms < 1000 else warn_line("Discord ACK", f"{ack_ms}ms, slow response"),
            lag["line"],
            ok_line("Uptime", format_timedelta(uptime)),
            ok_line("Runtime", f"Python {platform.python_version()} • discord.py {discord.__version__}"),
            ok_line("Loaded", f"{len(self.bot.cogs)} cogs • {command_count} slash commands"),
        ]

        config_lines = [
            ok_line("TOKEN", "configured") if os.getenv("TOKEN") else fail_line("TOKEN", "missing"),
            ok_line(".env", "found") if (BASE_DIR / ".env").exists() else warn_line(".env", "not found; using shell env only"),
            ok_line("GUILD_ID", f"{GUILD_ID} (instant sync)") if GUILD_ID else warn_line("GUILD_ID", "global sync can be slower"),
            ok_line("Update channel", f"<#{update_channel_id}>")
            if update_channel_id
            else warn_line("Update channel", "not configured; run /setup"),
            ok_line("GitHub feed", f"<#{github_channel_id}>")
            if github_channel_id
            else warn_line("GitHub feed", "not configured; run /setup"),
            ok_line("GITHUB_TOKEN", "configured")
            if github_config.token
            else warn_line("GITHUB_TOKEN", "optional, but recommended for rate limits"),
            ok_line("ANTHROPIC_API_KEY", "configured")
            if os.getenv("ANTHROPIC_API_KEY")
            else warn_line("ANTHROPIC_API_KEY", "/ask disabled until configured"),
            ok_line("Error digest channel", f"<#{error_channel_id}>")
            if error_channel_id
            else info_line("Error digest channel", "optional; run /setup to enable"),
        ]

        permissions = interaction.app_permissions
        permission_checks = [
            ("Send Messages", permissions.send_messages),
            ("Embed Links", permissions.embed_links),
            ("Read History", permissions.read_message_history),
            ("Manage Messages", permissions.manage_messages),
            ("Moderate Members", permissions.moderate_members),
            ("Create Threads", permissions.create_private_threads),
            ("Thread Messages", permissions.send_messages_in_threads),
            ("Manage Roles", permissions.manage_roles),
        ]
        permission_lines = [
            ok_line(label, "available") if granted else warn_line(label, "missing or channel-limited")
            for label, granted in permission_checks
        ]

        github_lines = [
            ok_line("Username", github_config.username) if github_config.username else warn_line("Username", "not configured"),
            ok_line("Primary Repo", github_config.primary_repo)
            if github_config.primary_repo
            else warn_line("Primary Repo", "not configured"),
            ok_line("Watcher Repos", ", ".join(github_config.watch_repos))
            if github_config.watch_repos
            else warn_line("Watcher Repos", "none configured"),
            ok_line("Polling", f"every {github_config.poll_seconds}s"),
        ]
        try:
            if github_config.primary_repo:
                repo = await asyncio.wait_for(github_api.fetch_repo(github_config.primary_repo), timeout=8)
                if repo:
                    github_lines.append(ok_line("GitHub API", f"repo reachable • ⭐ {repo.get('stargazers_count', 0)}"))
                else:
                    github_lines.append(fail_line("GitHub API", "primary repo not found"))
            elif github_config.username:
                user = await asyncio.wait_for(github_api.fetch_user(github_config.username), timeout=8)
                github_lines.append(ok_line("GitHub API", "profile reachable") if user else fail_line("GitHub API", "profile not found"))
            else:
                github_lines.append(warn_line("GitHub API", "skipped; no username/repo configured"))
        except (RuntimeError, asyncio.TimeoutError, aiohttp.ClientError) as error:
            github_lines.append(warn_line("GitHub API", truncate(str(error), 100)))

        developer_cog = self.bot.get_cog("Developer")
        github_watcher = getattr(developer_cog, "watch_github_activity", None) if developer_cog else None
        if error_channel_id:
            error_channel = self.bot.get_channel(int(error_channel_id))
            if isinstance(error_channel, discord.TextChannel) and error_channel.guild == interaction.guild:
                error_perms = error_channel.permissions_for(interaction.guild.me)
                error_digest_line = (
                    ok_line("Error digest", f"ready in {error_channel.mention}")
                    if error_perms.send_messages and error_perms.embed_links
                    else warn_line("Error digest", "missing Send Messages or Embed Links in configured channel")
                )
            elif error_channel is not None:
                error_digest_line = ok_line("Error digest", f"configured: <#{error_channel_id}>")
            else:
                error_digest_line = warn_line("Error digest", "channel not cached; verify ID and permissions")
        else:
            error_digest_line = info_line("Error digest", "disabled until configured with /setup")

        feature_lines = [
            warn_line("Maintenance mode", self.maintenance_state().get("message"))
            if self.maintenance_state().get("enabled")
            else ok_line("Maintenance mode", "inactive"),
            ok_line("Streaming status", "rotating every 30s")
            if self.rotate_stream_status.is_running() and not self.maintenance_state().get("enabled")
            else info_line("Streaming status", "paused while maintenance is active")
            if self.maintenance_state().get("enabled")
            else warn_line("Streaming status", "loop stopped"),
            ok_line("Startup updates", "background-safe") if update_channel_id else warn_line("Startup updates", "no channel set"),
            ok_line("GitHub watcher", "running")
            if github_watcher and github_watcher.is_running()
            else warn_line("GitHub watcher", "stopped or not configured"),
            ok_line("Giveaways/Roles/Tickets", "persistent buttons"),
            error_digest_line,
            info_line("Polls", "temporary by design; buttons expire after restart/24h"),
        ]

        storage_lines = storage_health_lines()
        all_lines = runtime_lines + config_lines + permission_lines + storage_lines + github_lines + feature_lines
        error_count = sum(line.startswith("❌") for line in all_lines)
        warning_count = sum(line.startswith("⚠️") for line in all_lines)

        if error_count:
            title = "🩺 Doctor Check • Needs attention"
            description = f"Found **{error_count} issue(s)** and **{warning_count} note(s)**."
            color = Palette.DANGER
        elif warning_count:
            title = "🩺 Doctor Check • Healthy with notes"
            description = f"No critical issues. **{warning_count} note(s)** are worth knowing."
            color = Palette.WARNING
        else:
            title = "🩺 Doctor Check • All systems healthy"
            description = "Everything looks clean. The little Raspberry Pi is vibing."
            color = Palette.SUCCESS

        embed = make_embed(title, description, color=color)
        embed.add_field(name="Pulse", value=clamp_field(runtime_lines), inline=False)
        embed.add_field(name="Configuration", value=clamp_field(config_lines), inline=False)
        embed.add_field(name="Storage", value=clamp_field(storage_lines), inline=False)
        embed.add_field(name="Permissions", value=clamp_field(permission_lines), inline=False)
        embed.add_field(name="GitHub", value=clamp_field(github_lines), inline=False)
        embed.add_field(name="Feature Notes", value=clamp_field(feature_lines), inline=False)
        brand_footer(embed, "Doctor diagnostics")
        await respond(interaction, embed, ephemeral=True)

    @app_commands.command(name="help", description="Interactive command hub — browse every category")
    async def help_command(self, interaction: discord.Interaction):
        await interaction.response.defer()
        embed = build_help_home_embed(self.bot)
        await respond(interaction, embed, view=HelpView(self.bot))

    @app_commands.command(name="maintenance", description="Enable, disable or inspect global maintenance mode")
    @app_commands.describe(action="What should NovaGuard do?", message="Visible presence text while maintenance is active")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="Enable", value="enable"),
            app_commands.Choice(name="Disable", value="disable"),
            app_commands.Choice(name="Status", value="status"),
        ]
    )
    async def maintenance(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        message: str | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        if not await self.ensure_maintenance_manager(interaction):
            return

        state = self.maintenance_state()

        if action.value == "status":
            color = Palette.WARNING if state.get("enabled") else Palette.SUCCESS
            title = "🛠️ Maintenance Mode • Active" if state.get("enabled") else "🛠️ Maintenance Mode • Inactive"
            description = (
                "NovaGuard is currently limiting commands for regular users."
                if state.get("enabled")
                else "NovaGuard is currently running normally with full command access."
            )
            embed = make_embed(title, description, color=color)
            embed.add_field(name="Presence", value=f"`{state.get('message', DEFAULT_MAINTENANCE_MESSAGE)}`", inline=False)
            if state.get("updated_by"):
                embed.add_field(name="Last Change", value=state["updated_by"], inline=True)
            if state.get("updated_at"):
                try:
                    changed_at = datetime.fromisoformat(state["updated_at"])
                except (TypeError, ValueError):
                    changed_at = None
                if changed_at:
                    embed.add_field(name="Updated", value=discord.utils.format_dt(changed_at, "R"), inline=True)
            brand_footer(embed, "Maintenance control")
            await respond(interaction, embed, ephemeral=True)
            return

        actor_label = f"{interaction.user} ({interaction.user.id})"
        if action.value == "enable":
            state = save_maintenance_state(True, message or state.get("message"), updated_by=actor_label)
            await self.apply_maintenance_presence(state)
            embed = make_embed(
                "🛠️ Maintenance Enabled",
                "NovaGuard is now in maintenance mode.\nRegular users will see a maintenance notice instead of command results.",
                color=Palette.WARNING,
            )
            embed.add_field(name="Presence", value=f"`{state['message']}`", inline=False)
            embed.add_field(name="Command Access", value="Only the bot owner can continue using commands.", inline=False)
            brand_footer(embed, "Maintenance control")
            await respond(interaction, embed, ephemeral=True)
            return

        state = save_maintenance_state(False, DEFAULT_MAINTENANCE_MESSAGE, updated_by=actor_label)
        await self.refresh_presence_mode()
        embed = make_embed(
            "✅ Maintenance Disabled",
            "NovaGuard is back to normal.\nStreaming rotation and public command access have been restored.",
            color=Palette.SUCCESS,
        )
        embed.add_field(name="Presence", value="`Streaming rotation resumed`", inline=False)
        brand_footer(embed, "Maintenance control")
        await respond(interaction, embed, ephemeral=True)

    @app_commands.command(name="latest", description="The latest automatic bot changelog")
    async def latest(self, interaction: discord.Interaction):
        await interaction.response.defer()
        update_state = updates.load_update_state()
        latest_update = update_state.get("latest")
        if not latest_update:
            embed = make_embed("🗒️ Nothing yet", "No automatic changelog has been generated yet.", color=Palette.WARNING)
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        await respond(
            interaction,
            updates.build_code_update_embed(latest_update),
            view=updates.build_update_buttons(),
        )

    @app_commands.command(name="updates", description="Browse the full bot release timeline")
    async def updates_command(self, interaction: discord.Interaction):
        await interaction.response.defer()
        update_state = updates.load_update_state()
        update_history = updates.normalize_update_history(update_state.get("history", []))
        if not update_history:
            embed = make_embed("🗒️ Nothing yet", "No update history has been saved yet.", color=Palette.WARNING)
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        embeds = updates.build_update_history_embeds(update_history)
        view = Paginator(embeds, interaction.user.id) if len(embeds) > 1 else None
        await respond(interaction, embeds[0], view=view)

    @app_commands.command(name="forceupdate", description="Preview the changelog for the current code state")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def forceupdate(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        update_entry = await asyncio.to_thread(updates.build_preview_update_entry)

        await respond(
            interaction,
            updates.build_code_update_embed(update_entry),
            view=updates.build_update_buttons(),
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(System(bot))
