"""🧰 Utility category — info cards, polls, reminders, timestamps and small power tools."""

import logging
import asyncio
import random
import re
import uuid
from datetime import UTC, datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.loop_guard import keep_running
from core.storage import load_data, save_data
from core.theme import Palette, brand_footer, make_embed
from core.utility_presenters import (
    BADGE_LABELS,
    TIMESTAMP_STYLES,
    build_avatar_embed,
    build_choice_embed,
    build_color_embed,
    build_invalid_reminder_duration_embed,
    build_no_reminders_embed,
    build_poll_embed,
    build_reminder_cancelled_embed,
    build_reminder_delivery_embed,
    build_reminder_select_options,
    build_reminder_set_embed,
    build_reminder_too_far_embed,
    build_reminders_embed,
    build_roleinfo_embed,
    build_serverinfo_embed,
    build_timestamp_embed,
    build_userinfo_embed,
)
from core.utils import parse_duration, respond, truncate

log = logging.getLogger(__name__)


HEX_COLOR_PATTERN = re.compile(r"^#?([0-9a-fA-F]{6})$")
# Serialises load -> mutate -> save on the reminders file so concurrent
# /remind calls (or a cancel racing the delivery loop) cannot drop entries.
_REMINDERS_LOCK = asyncio.Lock()

class PollVoteButton(discord.ui.Button):
    def __init__(self, index, label):
        super().__init__(label=truncate(label, 70), style=discord.ButtonStyle.primary)
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        view.votes[interaction.user.id] = self.index
        await interaction.response.edit_message(embed=view.build_embed(), view=view)


class PollEndButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="End poll", emoji="🔒", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        is_author = interaction.user.id == view.author_id
        perms = getattr(interaction.user, "guild_permissions", None)
        if not is_author and not (perms and perms.manage_messages):
            return await interaction.response.send_message(
                "Only the poll author or a moderator can end this poll.", ephemeral=True
            )

        for child in view.children:
            child.disabled = True
        view.stop()
        await interaction.response.edit_message(embed=view.build_embed(closed=True), view=view)


class PollView(discord.ui.View):
    def __init__(self, question, options, author):
        super().__init__(timeout=86400)
        self.question = question
        self.options = options
        self.author_id = author.id
        self.author_name = author.display_name
        self.votes = {}
        self.message = None
        for index, option in enumerate(options):
            self.add_item(PollVoteButton(index, option))
        self.add_item(PollEndButton())

    def build_embed(self, closed=False):
        return build_poll_embed(
            self.question,
            self.options,
            self.votes,
            self.author_name,
            closed,
        )

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(embed=self.build_embed(closed=True), view=self)
            except discord.HTTPException:
                pass


class ReminderCancelSelect(discord.ui.Select):
    def __init__(self, user_id, items):
        super().__init__(
            placeholder="Cancel a reminder…",
            options=build_reminder_select_options(items),
        )
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("These reminders are not yours!", ephemeral=True)

        async with _REMINDERS_LOCK:
            reminders = await asyncio.to_thread(load_data, "reminders", [])
            reminders = [item for item in reminders if item.get("id") != self.values[0]]
            await asyncio.to_thread(save_data, "reminders", reminders)

        await interaction.response.edit_message(
            embed=build_reminder_cancelled_embed(),
            view=None,
        )


class Utility(commands.Cog):
    """Everyday power tools with a modern look."""

    EMOJI = "🧰"
    COLOR = Palette.INFO
    DESCRIPTION = "Info cards, interactive polls, reminders, timestamps and handy tools."

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.reminder_loop.start()

    async def cog_unload(self):
        self.reminder_loop.cancel()

    @tasks.loop(seconds=20)
    @keep_running(log, "reminder delivery")
    async def reminder_loop(self):
        async with _REMINDERS_LOCK:
            reminders = await asyncio.to_thread(load_data, "reminders", [])
            if not reminders:
                return

            now = datetime.now(UTC)
            due = []
            remaining = []
            for item in reminders:
                # A corrupt due_at must not raise: an unhandled exception stops
                # a tasks.loop for good and no reminder would ever fire again.
                try:
                    is_due = datetime.fromisoformat(item["due_at"]) <= now
                except (KeyError, TypeError, ValueError):
                    log.warning(f"Reminder {item.get('id')} has an invalid due_at; dropping it")
                    continue
                (due if is_due else remaining).append(item)

            if not due and len(remaining) == len(reminders):
                return
            await asyncio.to_thread(save_data, "reminders", remaining)

        # Delivery is at-most-once on purpose: the store above was already
        # rewritten without these, so a channel that is gone for good cannot
        # make the loop retry it forever. The price is that a failure here
        # loses the reminder — which has to be recorded, because the only
        # other symptom is a message that never arrived, and nobody can report
        # something they did not receive.
        for item in due:
            channel = self.bot.get_channel(item["channel_id"])
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(item["channel_id"])
                except discord.HTTPException:
                    log.warning(
                        "Reminder %s dropped: channel %s is unreachable",
                        item.get("id"),
                        item.get("channel_id"),
                    )
                    continue
            try:
                await channel.send(
                    content=f"<@{item['user_id']}>",
                    embed=build_reminder_delivery_embed(item["message"]),
                )
            except discord.HTTPException:
                log.warning(
                    "Reminder %s dropped: could not post in channel %s",
                    item.get("id"),
                    item.get("channel_id"),
                    exc_info=True,
                )
                continue

    @reminder_loop.before_loop
    async def before_reminder_loop(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="poll", description="Interactive poll with live vote bars")
    @app_commands.describe(
        question="What are we voting on?",
        option1="First choice",
        option2="Second choice",
        option3="Third choice (optional)",
        option4="Fourth choice (optional)",
        option5="Fifth choice (optional)",
    )
    async def poll(
        self,
        interaction: discord.Interaction,
        question: str,
        option1: str,
        option2: str,
        option3: str | None = None,
        option4: str | None = None,
        option5: str | None = None,
    ):
        options = [option for option in (option1, option2, option3, option4, option5) if option]
        view = PollView(question, options, interaction.user)
        message = await respond(interaction, view.build_embed(), view=view)
        view.message = message or await interaction.original_response()

    @app_commands.command(name="remind", description="Set a reminder (e.g. 10m, 1h30m, 2d)")
    @app_commands.describe(duration="When? e.g. 10m, 1h30m, 2d", message="What should I remind you about?")
    async def remind(self, interaction: discord.Interaction, duration: str, message: str):
        delta = parse_duration(duration)
        if not delta:
            return await respond(
                interaction,
                build_invalid_reminder_duration_embed(),
                ephemeral=True,
            )

        if delta.days > 90:
            return await respond(
                interaction,
                build_reminder_too_far_embed(),
                ephemeral=True,
            )

        due_at = datetime.now(UTC) + delta
        async with _REMINDERS_LOCK:
            reminders = await asyncio.to_thread(load_data, "reminders", [])
            reminders.append(
                {
                    "id": uuid.uuid4().hex[:8],
                    "user_id": interaction.user.id,
                    "guild_id": interaction.guild_id,
                    "channel_id": interaction.channel_id,
                    "message": message,
                    "due_at": due_at.isoformat(),
                }
            )
            await asyncio.to_thread(save_data, "reminders", reminders)

        await respond(
            interaction,
            build_reminder_set_embed(due_at, message),
            ephemeral=True,
        )

    @app_commands.command(name="reminders", description="See and cancel your pending reminders")
    async def reminders(self, interaction: discord.Interaction):
        reminders = await asyncio.to_thread(load_data, "reminders", [])
        mine = sorted(
            (item for item in reminders if item["user_id"] == interaction.user.id),
            key=lambda item: item["due_at"],
        )
        if not mine:
            return await respond(
                interaction,
                build_no_reminders_embed(),
                ephemeral=True,
            )

        view = discord.ui.View(timeout=180)
        view.add_item(ReminderCancelSelect(interaction.user.id, mine))
        await respond(
            interaction,
            build_reminders_embed(mine),
            view=view,
            ephemeral=True,
        )

    @app_commands.command(name="userinfo", description="Detailed profile card for a member")
    @app_commands.describe(member="Whose profile? (defaults to you)")
    @app_commands.guild_only()
    async def userinfo(self, interaction: discord.Interaction, member: discord.Member | None = None):
        target = member or interaction.user
        await respond(interaction, build_userinfo_embed(target))

    @app_commands.command(name="serverinfo", description="Everything about this server in one card")
    @app_commands.guild_only()
    async def serverinfo(self, interaction: discord.Interaction):
        await respond(interaction, build_serverinfo_embed(interaction.guild))

    @app_commands.command(name="avatar", description="Full-size avatar of a member")
    @app_commands.describe(user="Whose avatar? (defaults to you)")
    async def avatar(self, interaction: discord.Interaction, user: discord.User | None = None):
        target = user or interaction.user
        embed, asset_url = build_avatar_embed(target)

        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label="Open original", url=asset_url))
        await respond(interaction, embed, view=view)

    @app_commands.command(name="roleinfo", description="Details about a role")
    @app_commands.describe(role="Which role?")
    @app_commands.guild_only()
    async def roleinfo(self, interaction: discord.Interaction, role: discord.Role):
        await respond(interaction, build_roleinfo_embed(role))

    @app_commands.command(name="timestamp", description="Generate Discord timestamp codes")
    @app_commands.describe(date="Optional: YYYY-MM-DD HH:MM (UTC). Defaults to now.")
    async def timestamp(self, interaction: discord.Interaction, date: str | None = None):
        if date:
            try:
                moment = datetime.strptime(date, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
            except ValueError:
                embed = make_embed(
                    "🤔 Invalid date",
                    "Use the format `YYYY-MM-DD HH:MM`, e.g. `2026-07-03 18:30`.",
                    color=Palette.WARNING,
                )
                brand_footer(embed)
                return await respond(interaction, embed, ephemeral=True)
        else:
            moment = datetime.now(UTC)

        await respond(interaction, build_timestamp_embed(moment), ephemeral=True)

    @app_commands.command(name="choose", description="Can't decide? Let fate pick for you")
    @app_commands.describe(options="Options separated by commas, e.g. pizza, sushi, tacos")
    async def choose(self, interaction: discord.Interaction, options: str):
        choices = [item.strip() for item in options.split(",") if item.strip()]
        if len(choices) < 2:
            embed = make_embed("🤔 Give me options", "I need at least two options separated by commas.", color=Palette.WARNING)
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        winner = random.choice(choices)
        await respond(interaction, build_choice_embed(choices, winner))

    @app_commands.command(name="color", description="Preview any hex color")
    @app_commands.describe(hex_code="Hex color, e.g. #5865F2")
    async def color(self, interaction: discord.Interaction, hex_code: str):
        match = HEX_COLOR_PATTERN.match(hex_code.strip())
        if not match:
            embed = make_embed("🎨 Invalid color", "Give me a hex color like `#5865F2`.", color=Palette.WARNING)
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        await respond(interaction, build_color_embed(match.group(1)))


async def setup(bot):
    await bot.add_cog(Utility(bot))
