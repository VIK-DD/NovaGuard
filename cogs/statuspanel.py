"""📡 The public service status card.

Separate from /status and /doctor on purpose. Those are operator diagnostics —
ephemeral, detailed, permission-gated. This is the card a community reads: a
handful of rows, edited twice a day at fixed hours. A restart publishes a fresh
card; a process that stays online rolls the message over after fourteen days.

Every reading is taken live. The API row is an actual HTTP request to the
bot's own API, not a guess from whether the object exists, because a status
panel that cannot be wrong is not worth posting.
"""

import asyncio
import logging
from datetime import UTC, datetime

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.guild_config import resolve_configured_channels
from core.loop_guard import keep_running
from core.maintenance import load_maintenance_state
from core.status_panel import (
    build_snapshot,
    build_status_embed,
    due_slot,
    status_message_is_stale,
    status_schedule_label,
)
from core.storage import get_guild_settings, update_guild_settings
from core.theme import Palette, brand_footer, make_embed
from core.utils import defer_interaction, respond
from core.webserver import WEB_PORT, db_ping

log = logging.getLogger(__name__)

STATUS_CHANNEL_KEY = "status_channel"
STATUS_MESSAGE_KEY = "status_panel_message"
API_TIMEOUT_SECONDS = 5
CHECK_INTERVAL_SECONDS = 30


class StatusPanel(commands.Cog):
    """Publishes and refreshes the public status card."""

    EMOJI = "📡"
    COLOR = Palette.INFO
    DESCRIPTION = "A public service status card, edited twice a day."

    def __init__(self, bot):
        self.bot = bot
        self.last_slot = None

    async def cog_load(self):
        self.status_loop.start()

    async def cog_unload(self):
        self.status_loop.cancel()

    # ── probes ────────────────────────────────────────────────────────

    async def _probe_api(self):
        """Ask the bot's own API whether it is serving, over real HTTP.

        Returns ``(ok, detail)``. A refusal and a timeout read differently to
        whoever has to fix it, so they are not flattened into one message.
        """
        url = f"http://127.0.0.1:{WEB_PORT}/api/v1/health"
        timeout = aiohttp.ClientTimeout(total=API_TIMEOUT_SECONDS)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        return False, f"answered HTTP {response.status}"
                    payload = await response.json()
        except asyncio.TimeoutError:
            return False, f"no response in {API_TIMEOUT_SECONDS}s"
        except aiohttp.ClientError as error:
            return False, f"unreachable ({type(error).__name__})"
        except ValueError:
            return False, "answered with something that is not JSON"

        if not payload.get("ok"):
            return False, "reports itself unhealthy"
        return True, "responding"

    async def collect_snapshot(self):
        api_ok, api_detail = await self._probe_api()
        try:
            database_ok = bool(await asyncio.to_thread(db_ping))
        except Exception:
            log.warning("Status panel could not reach the database", exc_info=True)
            database_ok = False

        launched_at = getattr(self.bot, "launched_at", None)
        uptime = (datetime.now(UTC) - launched_at).total_seconds() if launched_at else 0

        return build_snapshot(
            bot_ready=self.bot.is_ready(),
            latency_ms=round((self.bot.latency or 0) * 1000),
            api_ok=api_ok,
            api_detail=api_detail,
            database_ok=database_ok,
            maintenance=load_maintenance_state(),
            uptime_seconds=uptime,
            guilds=len(self.bot.guilds),
            members=sum(guild.member_count or 0 for guild in self.bot.guilds),
        )

    # ── publishing ────────────────────────────────────────────────────

    async def publish(self, channel, embed):
        """Post the new card, then remove the previous one.

        Deliberately in that order. Deleting first would leave the channel
        with no card at all if the post then failed.
        """
        settings = get_guild_settings(channel.guild.id)
        previous_id = settings.get(STATUS_MESSAGE_KEY)

        message = await channel.send(embed=embed)
        update_guild_settings(channel.guild.id, **{STATUS_MESSAGE_KEY: str(message.id)})

        if previous_id and str(previous_id) != str(message.id):
            try:
                old = channel.get_partial_message(int(previous_id))
                await old.delete()
            except (discord.NotFound, discord.Forbidden, ValueError):
                pass
            except discord.HTTPException:
                log.warning("Could not remove the previous status card in #%s", channel.id)
        return message

    async def refresh(self, channel, embed, *, now=None):
        """Edit the current card, replacing it only when it reaches 14 days.

        A partial message is enough to edit a bot-authored card and avoids
        requiring Read Message History merely to keep the status current.
        """
        settings = get_guild_settings(channel.guild.id)
        previous_id = settings.get(STATUS_MESSAGE_KEY)
        try:
            message_id = int(previous_id)
            created_at = discord.utils.snowflake_time(message_id)
        except (TypeError, ValueError, OverflowError, OSError):
            return await self.publish(channel, embed)

        if status_message_is_stale(created_at, now=now):
            return await self.publish(channel, embed)

        try:
            message = channel.get_partial_message(message_id)
            return await message.edit(embed=embed)
        except discord.NotFound:
            # Someone deleted the card manually. Restore it instead of leaving
            # the configured status channel empty until the next restart.
            return await self.publish(channel, embed)

    async def _deliver_to_configured_channels(self, *, publish_new=False):
        channels = await resolve_configured_channels(self.bot, STATUS_CHANNEL_KEY, None)
        if not channels:
            return

        snapshot = await self.collect_snapshot()
        embed = build_status_embed(snapshot)
        action = self.publish if publish_new else self.refresh
        for channel in channels:
            try:
                await action(channel, embed)
            except discord.Forbidden:
                log.warning("Status card permission denied in #%s", channel.id)
            except discord.HTTPException:
                log.warning("Status card could not be updated in #%s", channel.id, exc_info=True)

    # ── the schedule ──────────────────────────────────────────────────

    @tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
    @keep_running(log, "status panel refresh")
    async def status_loop(self):
        slot = due_slot()
        if not slot or slot == self.last_slot:
            return
        self.last_slot = slot

        await self._deliver_to_configured_channels()

    @status_loop.before_loop
    async def before_status_loop(self):
        await self.bot.wait_until_ready()
        # This hook runs once for the lifetime of the task, not on gateway
        # reconnects. A real process restart therefore posts one fresh card,
        # while an ordinary Discord resume does not create duplicates.
        await self._deliver_to_configured_channels(publish_new=True)

    # ── the command ───────────────────────────────────────────────────

    @app_commands.command(
        name="statuspanel",
        description="Post the public service status card right now",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def statuspanel(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)

        settings = get_guild_settings(interaction.guild_id)
        channel_id = settings.get(STATUS_CHANNEL_KEY)
        channel = interaction.guild.get_channel(int(channel_id)) if channel_id else None
        if channel is None:
            embed = make_embed(
                "📡 No status channel yet",
                "Pick one in `/setup` — choose **Service Status**, then the channel."
                "\n\nOnce set, a fresh card appears at the next restart and its status"
                f" is edited at {status_schedule_label()}.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "Service status")
            return await respond(interaction, embed, ephemeral=True)

        snapshot = await self.collect_snapshot()
        try:
            message = await self.publish(channel, build_status_embed(snapshot))
        except discord.Forbidden:
            embed = make_embed(
                "🔒 I cannot post there",
                f"Grant me **Send Messages** and **Embed Links** in {channel.mention}.",
                color=Palette.DANGER,
            )
            brand_footer(embed, "Service status")
            return await respond(interaction, embed, ephemeral=True)

        confirm = make_embed(
            "📡 Status card posted",
            f"Published in {channel.mention}.\nIt is edited at {status_schedule_label()}"
            " and replaced after a restart or 14 days online.",
            color=Palette.SUCCESS,
        )
        confirm.add_field(name="Message", value=message.jump_url, inline=False)
        brand_footer(confirm, "Service status")
        await respond(interaction, confirm, ephemeral=True)


async def setup(bot):
    await bot.add_cog(StatusPanel(bot))
