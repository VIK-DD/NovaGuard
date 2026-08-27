"""⚙️ System category — bot status, help hub, and the automatic update changelog."""

import asyncio
import json
import logging
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
from core.loop_guard import keep_running
from cogs.admin import require_admin
from core.admin_auth import record_audit
from core.backups import (
    BACKUP_DIR,
    backup_max_expected_age_seconds,
    backup_schedule,
    backup_schedule_label,
    backup_timezone,
    create_backup,
    guild_export_relative_path,
    inspect_backup,
    latest_backup,
    list_backups,
    remote_backup_config,
    update_remote_backup_state,
    upload_json_to_remote,
)
from core.config import (
    BASE_DIR,
    ERROR_LOG_CHANNEL_ID,
    GITHUB_STATE_FILE,
    GUILD_ID,
    STREAM_URL,
    UPDATE_STATE_FILE,
    github_config,
    stream_status_interval_seconds,
    stream_statuses,
)
from core.database import DB_PATH, load_economy_data, load_levels_data, load_voice_store
from core.error_digest import send_error_digest
from core.github_api import github_api
from core.help_ui import HelpView, Paginator, build_help_home_embed
from core.maintenance import (
    DEFAULT_MAINTENANCE_MESSAGE,
    load_maintenance_state,
    save_maintenance_state,
    user_can_bypass_maintenance,
)
from core.release_versions import current_project_release
from core.health_report import (
    clamp_field,
    fail_line,
    info_line,
    json_file_status,
    ok_line,
    storage_health_lines,
    warn_line,
)
from core.storage import DATA_DIR, get_guild_settings, load_data
from core.system_presenters import (
    build_botinfo_embed,
    build_ping_embed,
    build_public_status_embed,
    build_uptime_embed,
    ping_profile,
    public_status_links,
    public_status_profile,
    summarize_loop_lag,
)
from core.theme import Palette, brand_footer, make_embed
from core.utils import build_link_view, defer_interaction, format_timedelta, respond, truncate

log = logging.getLogger(__name__)

LAG_MONITOR_SECONDS = 5
BACKUP_STARTUP_DELAY_SECONDS = 120
BACKUP_HEALTH_CHECK_SECONDS = 30 * 60
BACKUP_STALE_ALERT_COOLDOWN_SECONDS = 6 * 3600
HEALTH_ALERT_COOLDOWN_SECONDS = 900
HIGH_LAG_ALERT_MS = 3000
HIGH_LAG_STREAK_REQUIRED = 2
IGNORE_HUGE_LAG_MS = 60000
PRESENCE_ERROR_LOG_COOLDOWN_SECONDS = 180
PRESENCE_UPDATE_TIMEOUT_SECONDS = 5
STARTUP_UPDATE_INITIAL_DELAY_SECONDS = 12
STARTUP_UPDATE_RETRY_DELAY_SECONDS = 20
STARTUP_UPDATE_MAX_ATTEMPTS = 6


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
        self.last_backup_stale_alert_at = 0
        self.last_backup_slot = None
        self.backup_running = False

    async def cog_load(self):
        self.rotate_stream_status.start()
        self.monitor_event_loop.start()
        self.backup_loop.start()
        self.backup_health_loop.start()

    async def cog_unload(self):
        self.rotate_stream_status.cancel()
        self.monitor_event_loop.cancel()
        self.backup_loop.cancel()
        self.backup_health_loop.cancel()
        if self.startup_update_task and not self.startup_update_task.done():
            self.startup_update_task.cancel()

    def loop_lag_snapshot(self):
        return summarize_loop_lag(self.loop_lag_samples)

    def maintenance_state(self):
        return load_maintenance_state()

    async def apply_stream_presence(self, advance=True):
        try:
            await asyncio.wait_for(
                self.bot.change_presence(
                    status=discord.Status.online,
                    activity=discord.Streaming(
                        name=stream_statuses[self.status_index],
                        url=STREAM_URL,
                    ),
                ),
                timeout=PRESENCE_UPDATE_TIMEOUT_SECONDS,
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
                log.warning(f"Streaming status update skipped due to temporary connection issue: {error}")
            return False

        if advance:
            self.status_index = (self.status_index + 1) % len(stream_statuses)
        return True

    async def apply_maintenance_presence(self, state=None):
        state = state or self.maintenance_state()
        try:
            await asyncio.wait_for(
                self.bot.change_presence(
                    status=discord.Status.dnd,
                    activity=discord.Game(name=state.get("message") or DEFAULT_MAINTENANCE_MESSAGE),
                ),
                timeout=PRESENCE_UPDATE_TIMEOUT_SECONDS,
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
                log.warning(f"Maintenance status update skipped due to temporary connection issue: {error}")
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
                        log.info("Startup updates delivered.")
                    else:
                        log.warning(f"Startup updates delivered on retry attempt {attempt}.")
                    return

                if not await asyncio.to_thread(updates.has_pending_announcement):
                    log.warning("Startup updates skipped: nothing pending to deliver.")
                    return

                if attempt < STARTUP_UPDATE_MAX_ATTEMPTS:
                    log.warning(
                        "Startup updates pending: Discord was not ready for delivery. "
                        f"Retrying in {STARTUP_UPDATE_RETRY_DELAY_SECONDS}s... attempt {attempt}"
                    )
            except asyncio.TimeoutError:
                if attempt < STARTUP_UPDATE_MAX_ATTEMPTS:
                    log.warning(
                        "Startup updates delayed: Discord was too slow to respond. "
                        f"Retrying in {STARTUP_UPDATE_RETRY_DELAY_SECONDS}s... attempt {attempt}"
                    )
                else:
                    log.warning("Startup updates still pending: Discord did not respond quickly enough.")
            except (discord.HTTPException, aiohttp.ClientError) as error:
                if attempt < STARTUP_UPDATE_MAX_ATTEMPTS:
                    log.warning(
                        "Startup updates delayed by a temporary network issue: "
                        f"{error}. Retrying in {STARTUP_UPDATE_RETRY_DELAY_SECONDS}s... attempt {attempt}"
                    )
                else:
                    log.warning(f"Startup updates still pending due to temporary network issue: {error}")
            except Exception as error:
                log.warning(f"Startup updates skipped due to unexpected issue: {error!r}", exc_info=True)
                await send_error_digest(
                    self.bot,
                    "Startup Update Error",
                    error,
                    context="Automatic startup changelog failed.",
                )
                return

            if attempt < STARTUP_UPDATE_MAX_ATTEMPTS:
                await asyncio.sleep(STARTUP_UPDATE_RETRY_DELAY_SECONDS)

        log.info("Startup updates remain pending. NovaGuard will try again after the next ready/reconnect event.")

    def schedule_startup_update_retry(self):
        if self.startup_update_task and not self.startup_update_task.done():
            return
        self.startup_update_task = asyncio.create_task(self.announce_startup_updates_later())

    @tasks.loop(seconds=LAG_MONITOR_SECONDS)
    @keep_running(log, "event loop lag monitor")
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
            log.info(f"Event-loop lag spike ignored as transient: {lag_ms:.0f}ms")
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

    def _scheduled_backup_slot(self, checked_at=None):
        local_now = (checked_at or datetime.now(UTC)).astimezone(backup_timezone())
        current = (local_now.hour, local_now.minute)
        if current not in backup_schedule():
            return None
        return local_now.strftime("%Y-%m-%d %H:%M")

    def _latest_backup_age(self):
        newest_backup = latest_backup()
        if not newest_backup:
            return None, None
        return newest_backup, datetime.now(UTC) - newest_backup["mtime"]

    @staticmethod
    def _filter_guild_entries(value, guild_id):
        if isinstance(value, dict):
            if str(guild_id) in value:
                return value.get(str(guild_id))
            return [
                item for item in value.values()
                if isinstance(item, dict) and str(item.get("guild_id")) == str(guild_id)
            ]
        if isinstance(value, list):
            return [
                item for item in value
                if isinstance(item, dict) and str(item.get("guild_id")) == str(guild_id)
            ]
        return [] if value is None else value

    async def _guild_export_sources(self):
        return await asyncio.to_thread(
            lambda: {
                "levels": load_levels_data(),
                "economy": load_economy_data(),
                "voice_sessions": load_voice_store("voice_sessions", {}),
                "voice_pending_reports": load_voice_store("voice_pending_reports", {}),
                "voice_report_history": load_voice_store("voice_report_history", {}),
                "giveaways": load_data("giveaways", []),
                "reminders": load_data("reminders", []),
                "warns": load_data("warns", {}),
            }
        )

    async def _guild_export_payload(self, guild, backup, created_at, sources):
        settings = await asyncio.to_thread(get_guild_settings, guild.id)
        guild_id = str(guild.id)
        return {
            "exported_at": created_at.isoformat(),
            "source_backup": backup.get("name"),
            "guild": {
                "id": guild_id,
                "name": guild.name,
                "member_count": guild.member_count or 0,
                "owner_id": str(guild.owner_id) if guild.owner_id else None,
                "icon": str(guild.icon) if guild.icon else None,
            },
            "settings": settings,
            "levels": sources["levels"].get(guild_id, {}),
            "economy": sources["economy"].get(guild_id, {}),
            "voice": {
                "sessions": sources["voice_sessions"].get(guild_id, {}) if isinstance(sources["voice_sessions"], dict) else {},
                "pending_reports": sources["voice_pending_reports"].get(guild_id, {}) if isinstance(sources["voice_pending_reports"], dict) else {},
                "report_history": sources["voice_report_history"].get(guild_id, []) if isinstance(sources["voice_report_history"], dict) else [],
            },
            "giveaways": self._filter_guild_entries(sources["giveaways"], guild_id),
            "reminders": self._filter_guild_entries(sources["reminders"], guild_id),
            "warns": self._filter_guild_entries(sources["warns"], guild_id),
        }

    async def _upload_guild_exports(self, backup, created_at):
        config = remote_backup_config()
        summary = {
            "configured": config["configured"],
            "destination": config["destination"],
            "uploaded": 0,
            "failed": 0,
            "skipped": 0,
            "exports": [],
            "updated_at": datetime.now(UTC).isoformat(),
        }
        if not config["configured"]:
            summary["skipped"] = len(self.bot.guilds)
            return summary

        sources = await self._guild_export_sources()
        for guild in self.bot.guilds:
            payload = await self._guild_export_payload(guild, backup, created_at, sources)
            remote_path = guild_export_relative_path(guild.id, guild.name, created_at)
            result = await asyncio.to_thread(upload_json_to_remote, payload, remote_path)
            export = {
                "guild_id": str(guild.id),
                "guild_name": guild.name,
                "ok": bool(result.get("ok")),
                "remote_path": result.get("remote_path"),
                "message": result.get("message"),
            }
            summary["exports"].append(export)
            if result.get("ok"):
                summary["uploaded"] += 1
            else:
                summary["failed"] += 1
        update_remote_backup_state(latest_guild_exports=summary)
        return summary

    def _deferred_guild_exports(self, reason):
        """Persist a deliberate no-op when Drive has already rejected a backup."""
        config = remote_backup_config()
        summary = {
            "configured": config["configured"],
            "destination": config["destination"],
            "uploaded": 0,
            "failed": 0,
            "skipped": len(self.bot.guilds),
            "deferred": True,
            "exports": [],
            "message": reason,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        update_remote_backup_state(latest_guild_exports=summary)
        return summary

    async def _run_automatic_backup(self):
        try:
            backup = await asyncio.to_thread(create_backup, "auto")
            created_at = datetime.fromisoformat(backup.get("created_at")) if backup.get("created_at") else datetime.now(UTC)
            log.info(f"Automatic backup created: {backup['name']}")
            remote = backup.get("remote") or {}
            if remote.get("configured"):
                if remote.get("ok"):
                    log.info(f"Automatic backup uploaded off-site: {backup['name']} -> {remote.get('remote_path')}")
                    check = remote.get("check") or {}
                    if check and not check.get("ok"):
                        await send_error_digest(
                            self.bot,
                            "Remote Backup Check Error",
                            RuntimeError(check.get("message") or "Remote file check failed"),
                            context=(
                                f"Backup `{backup['name']}` uploaded, but NovaGuard could not confirm "
                                "the file exists in remote storage."
                            ),
                        )
                else:
                    message = remote.get("message") or "off-site upload failed"
                    log.warning(f"Automatic backup off-site upload failed: {message}")
                    await send_error_digest(
                        self.bot,
                        "Off-site Backup Error",
                        RuntimeError(message),
                        context=(
                            f"Local backup `{backup['name']}` was created, but NovaGuard could not upload it "
                            f"to `{remote.get('destination')}`."
                        ),
                    )
                    self._deferred_guild_exports(
                        "Guild exports deferred because the full off-site backup upload failed."
                    )
                    return
            retention = backup.get("retention") or {}
            if retention.get("configured") and retention.get("enabled") and not retention.get("ok"):
                await send_error_digest(
                    self.bot,
                    "Remote Backup Retention Error",
                    RuntimeError(retention.get("message") or "Remote retention failed"),
                    context="NovaGuard could not prune old Google Drive backup files after the scheduled backup.",
                )
            guild_exports = await self._upload_guild_exports(backup, created_at)
            if guild_exports.get("configured"):
                log_method = log.warning if guild_exports["failed"] else log.info
                log_method(
                    "Guild backup exports finished: "
                    f"{guild_exports['uploaded']} uploaded, {guild_exports['failed']} failed"
                )
                if guild_exports["failed"]:
                    await send_error_digest(
                        self.bot,
                        "Guild Backup Export Error",
                        RuntimeError(f"{guild_exports['failed']} guild export(s) failed"),
                        context=(
                            f"Full backup `{backup['name']}` was created, but some per-server "
                            "Google Drive exports failed."
                        ),
                    )
        except Exception as error:
            log.warning(f"Automatic backup failed: {error!r}", exc_info=True)
            await send_error_digest(self.bot, "Automatic Backup Error", error, context="Scheduled backup failed.")

    @tasks.loop(seconds=60)
    @keep_running(log, "scheduled backup")
    async def backup_loop(self):
        slot = self._scheduled_backup_slot()
        if not slot or slot == self.last_backup_slot or self.backup_running:
            return
        self.last_backup_slot = slot
        self.backup_running = True
        try:
            await self._run_automatic_backup()
        finally:
            self.backup_running = False

    @backup_loop.before_loop
    async def before_backup_loop(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(BACKUP_STARTUP_DELAY_SECONDS)

    @tasks.loop(seconds=BACKUP_HEALTH_CHECK_SECONDS)
    @keep_running(log, "backup health check")
    async def backup_health_loop(self):
        newest_backup, age = self._latest_backup_age()
        if not newest_backup or age is None:
            return
        if age.total_seconds() <= backup_max_expected_age_seconds():
            return

        now = time.perf_counter()
        if now - self.last_backup_stale_alert_at < BACKUP_STALE_ALERT_COOLDOWN_SECONDS:
            return
        self.last_backup_stale_alert_at = now
        await send_error_digest(
            self.bot,
            "Backup Schedule Alert",
            RuntimeError(f"Latest backup is older than expected: {format_timedelta(age)}"),
            context=(
                f"Latest backup `{newest_backup['name']}` is {format_timedelta(age)} old. "
                f"Expected schedule: {backup_schedule_label()}."
            ),
        )

    @backup_health_loop.before_loop
    async def before_backup_health_loop(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(BACKUP_STARTUP_DELAY_SECONDS + 60)

    @tasks.loop(seconds=stream_status_interval_seconds)
    @keep_running(log, "presence rotation")
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
        log.info(f"{self.bot.user} is ready")

    @app_commands.command(name="ping", description="Latency, uptime and gateway health at a glance")
    async def ping(self, interaction: discord.Interaction):
        gateway_ms = round(self.bot.latency * 1000)
        started = time.perf_counter()
        await defer_interaction(interaction)
        rest_ms = round((time.perf_counter() - started) * 1000)

        uptime = datetime.now(UTC) - self.bot.launched_at
        await respond(interaction, build_ping_embed(gateway_ms, rest_ms, uptime))

    @app_commands.command(name="uptime", description="How long the bot has been online")
    async def uptime(self, interaction: discord.Interaction):
        await defer_interaction(interaction)
        await respond(interaction, build_uptime_embed(self.bot.launched_at))

    @app_commands.command(name="botinfo", description="Version, build, runtime and live stats")
    async def botinfo(self, interaction: discord.Interaction):
        await defer_interaction(interaction)
        history = updates.load_update_state().get("history", [])
        release = current_project_release()
        total_members = sum(guild.member_count or 0 for guild in self.bot.guilds)
        command_count = len(list(self.bot.tree.walk_commands()))

        embed = build_botinfo_embed(
            bot_name=self.bot.user.name,
            avatar_url=self.bot.user.display_avatar.url if self.bot.user.display_avatar else None,
            release=release,
            build_count=len(history),
            server_count=len(self.bot.guilds),
            total_members=total_members,
            command_count=command_count,
            category_count=len(self.bot.cogs),
            python_version=platform.python_version(),
            discord_version=discord.__version__,
            gateway_ms=round(self.bot.latency * 1000),
            uptime=datetime.now(UTC) - self.bot.launched_at,
        )
        await respond(interaction, embed)

    @app_commands.command(name="status", description="Public bot status: uptime, latency and project links")
    async def status(self, interaction: discord.Interaction):
        await defer_interaction(interaction)
        release = current_project_release()
        gateway_ms = round(self.bot.latency * 1000)
        uptime = datetime.now(UTC) - self.bot.launched_at
        lag = self.loop_lag_snapshot()
        maintenance_active = self.maintenance_state().get("enabled")

        embed = build_public_status_embed(
            bot_name=self.bot.user.name,
            avatar_url=self.bot.user.display_avatar.url if self.bot.user.display_avatar else None,
            gateway_ms=gateway_ms,
            uptime=uptime,
            lag=lag,
            maintenance_active=maintenance_active,
            release=release,
            command_count=len(list(self.bot.tree.walk_commands())),
            project_label=github_config.primary_repo or github_config.username,
        )
        buttons = public_status_links(
            github_config.primary_repo,
            github_config.username,
            github_config.uptime_url,
        )
        await respond(interaction, embed, view=build_link_view(buttons))

    @app_commands.command(name="doctor", description="Deep health check for the bot, config and integrations")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def doctor(self, interaction: discord.Interaction):
        started = time.perf_counter()
        await defer_interaction(interaction, ephemeral=True)
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
            ok_line("GUILD_ID", f"{GUILD_ID} (use /resync server for instant updates)")
            if GUILD_ID
            else warn_line("GUILD_ID", "global sync can be slower"),
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
            ok_line("Streaming status", f"rotating every {stream_status_interval_seconds}s")
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
        await defer_interaction(interaction)
        embed = build_help_home_embed(self.bot)
        await respond(interaction, embed, view=HelpView(self.bot))

    @app_commands.default_permissions(administrator=True)
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
        await defer_interaction(interaction, ephemeral=True)
        # A global kill switch for every guild at once, so it takes the key
        # as well as the owner account.
        if not await require_admin(interaction, self.bot, action="maintenance"):
            return
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
                "NovaGuard is now in maintenance mode.\n"
                "Regular users will see a maintenance notice instead of command results, "
                "and the website dashboard is closed with the same message.",
                color=Palette.WARNING,
            )
            embed.add_field(name="Presence", value=f"`{state['message']}`", inline=False)
            preview_code = state.get("preview_code")
            if preview_code:
                embed.add_field(
                    name="Preview code",
                    value=(
                        # A fenced block, not inline code in a spoiler: Discord
                        # puts a Copy button on fenced blocks, and this string is
                        # long enough that selecting it by hand is a chore. The
                        # reply is ephemeral, so the spoiler was only ever
                        # guarding against a screenshot.
                        f"```\n{preview_code}\n```\n"
                        "Use it at `novaguard.fun/preview/` to walk the closed site. "
                        "Shown once — it will not be repeated."
                    ),
                    inline=False,
                )
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
        # The empty-state reply is ephemeral, so check before deferring — an
        # early public defer would freeze the response as public.
        update_state = updates.load_update_state()
        latest_update = update_state.get("latest")
        if not latest_update:
            embed = make_embed("🗒️ Nothing yet", "No automatic changelog has been generated yet.", color=Palette.WARNING)
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        await defer_interaction(interaction)
        await respond(
            interaction,
            updates.build_code_update_embed(latest_update),
            view=updates.build_update_buttons(),
        )

    @app_commands.command(name="updates", description="Browse the full bot release timeline")
    async def updates_command(self, interaction: discord.Interaction):
        update_state = updates.load_update_state()
        update_history = updates.normalize_update_history(update_state.get("history", []))
        if not update_history:
            embed = make_embed("🗒️ Nothing yet", "No update history has been saved yet.", color=Palette.WARNING)
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        await defer_interaction(interaction)
        embeds = updates.build_update_history_embeds(update_history)
        view = Paginator(embeds, interaction.user.id) if len(embeds) > 1 else None
        await respond(interaction, embeds[0], view=view)

    @app_commands.command(name="forceupdate", description="Preview the changelog for the current code state")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def forceupdate(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        update_entry = await asyncio.to_thread(updates.build_preview_update_entry)

        await respond(
            interaction,
            updates.build_code_update_embed(update_entry),
            view=updates.build_update_buttons(),
            ephemeral=True,
        )

    # Discord has no "bot owner" permission, so the closest it can do is hide
    # the command from non-administrators. The real gate is the owner check
    # in the body; this only keeps it out of everyone else's picker.
    @app_commands.default_permissions(administrator=True)
    @app_commands.command(name="resync", description="Owner: re-push all slash commands to Discord")
    @app_commands.describe(scope="server is immediate; global can take up to ~1h")
    @app_commands.choices(scope=[
        app_commands.Choice(name="server - current server, usually immediate", value="server"),
        app_commands.Choice(name="global - every server, slower propagation", value="global"),
        app_commands.Choice(name="clear-server - remove instant server copies", value="clear-server"),
    ])
    @app_commands.guild_only()
    async def resync(self, interaction: discord.Interaction, scope: str = "server"):
        await defer_interaction(interaction, ephemeral=True)
        # Owner only, but deliberately NOT behind the admin key. /resync is
        # how new commands get published, including /admin unlock itself, so
        # requiring an unlock here deadlocks the very first setup: the key
        # cannot be used until the command that uses it exists. It only
        # re-publishes the command list, which is why the owner check alone
        # is proportionate.
        if not await user_can_bypass_maintenance(self.bot, interaction.user):
            record_audit(
                interaction.user.id,
                "resync",
                actor_name=str(interaction.user),
                outcome="denied",
                detail="not_owner",
            )
            embed = make_embed(
                "🔒 Owner Only",
                "Only the bot owner can re-sync slash commands.",
                color=Palette.DANGER,
            )
            brand_footer(embed, "Command resync")
            return await respond(interaction, embed, ephemeral=True)

        # Clearing removes commands rather than publishing them, so it is not
        # part of the bootstrap path and can afford the second factor.
        if scope == "clear-server" and not await require_admin(
            interaction, self.bot, action="resync.clear"
        ):
            return

        record_audit(
            interaction.user.id, "resync", actor_name=str(interaction.user), target=scope
        )

        guild = discord.Object(id=interaction.guild_id)
        try:
            if scope == "global":
                synced = await self.bot.tree.sync()
                description = (
                    f"Re-pushed `{len(synced)}` slash commands globally. New or changed "
                    "commands can take up to ~1h to appear on every server (usually minutes)."
                )
            elif scope == "clear-server":
                self.bot.tree.clear_commands(guild=guild)
                synced = await self.bot.tree.sync(guild=guild)
                description = (
                    "Cleared this server's instant command copies. Discord will fall back "
                    "to the global commands after propagation."
                )
            else:
                self.bot.tree.copy_global_to(guild=guild)
                synced = await self.bot.tree.sync(guild=guild)
                description = (
                    f"Synced `{len(synced)}` slash commands directly to this server. "
                    "They should appear almost immediately; reopen Discord if the UI is stale."
                )
        except discord.HTTPException as error:
            embed = make_embed(
                "⚠️ Resync failed",
                f"Discord API issue: `{error}`",
                color=Palette.DANGER,
            )
            brand_footer(embed, "Command resync")
            return await respond(interaction, embed, ephemeral=True)

        embed = make_embed(
            "🔄 Commands re-synced",
            description,
            color=Palette.SUCCESS,
        )
        brand_footer(embed, "Command resync")
        await respond(interaction, embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(System(bot))
