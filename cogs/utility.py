"""🧰 Utility category — info cards, polls, reminders, timestamps and small power tools."""

import asyncio
import random
import re
import uuid
from collections import Counter
from datetime import UTC, datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.storage import load_data, save_data
from core.theme import Palette, brand_footer, make_embed, progress_bar
from core.utils import format_timedelta, parse_duration, respond, truncate

HEX_COLOR_PATTERN = re.compile(r"^#?([0-9a-fA-F]{6})$")
TIMESTAMP_STYLES = [
    ("t", "Short time"),
    ("T", "Long time"),
    ("d", "Short date"),
    ("D", "Long date"),
    ("f", "Short date/time"),
    ("F", "Long date/time"),
    ("R", "Relative"),
]
BADGE_LABELS = {
    "staff": "Discord Staff",
    "partner": "Partner",
    "hypesquad": "HypeSquad Events",
    "bug_hunter": "Bug Hunter",
    "bug_hunter_level_2": "Bug Hunter Gold",
    "hypesquad_bravery": "Bravery",
    "hypesquad_brilliance": "Brilliance",
    "hypesquad_balance": "Balance",
    "early_supporter": "Early Supporter",
    "verified_bot_developer": "Early Verified Bot Dev",
    "active_developer": "Active Developer",
}


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
        total = len(self.votes)
        counts = Counter(self.votes.values())
        lines = []
        for index, option in enumerate(self.options):
            count = counts.get(index, 0)
            percent = round(count / total * 100) if total else 0
            bar = progress_bar(count, total or 1, slots=12)
            lines.append(f"**{option}**\n{bar} `{count} vote(s) • {percent}%`")

        title = ("🏁 " if closed else "📊 ") + self.question
        embed = make_embed(title, "\n\n".join(lines), color=Palette.SUCCESS if closed else Palette.INFO)
        status = "Final results" if closed else "Vote by clicking a button below"
        brand_footer(embed, f"Poll by {self.author_name} • {total} vote(s) • {status} • temporary 24h")
        return embed

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
        options = []
        for item in items[:25]:
            due = datetime.fromisoformat(item["due_at"])
            options.append(
                discord.SelectOption(
                    label=truncate(item["message"], 90),
                    value=item["id"],
                    description=f"in {format_timedelta(due - datetime.now(UTC))}",
                    emoji="⏰",
                )
            )
        super().__init__(placeholder="Cancel a reminder…", options=options)
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("These reminders are not yours!", ephemeral=True)

        reminders = await asyncio.to_thread(load_data, "reminders", [])
        reminders = [item for item in reminders if item["id"] != self.values[0]]
        await asyncio.to_thread(save_data, "reminders", reminders)

        embed = make_embed("🗑️ Reminder cancelled", "That reminder will not fire anymore.", color=Palette.SUCCESS)
        brand_footer(embed)
        await interaction.response.edit_message(embed=embed, view=None)


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
    async def reminder_loop(self):
        reminders = await asyncio.to_thread(load_data, "reminders", [])
        if not reminders:
            return

        now = datetime.now(UTC)
        due = [item for item in reminders if datetime.fromisoformat(item["due_at"]) <= now]
        if not due:
            return

        remaining = [item for item in reminders if item not in due]
        await asyncio.to_thread(save_data, "reminders", remaining)

        for item in due:
            channel = self.bot.get_channel(item["channel_id"])
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(item["channel_id"])
                except discord.HTTPException:
                    continue
            embed = make_embed("⏰ Reminder", item["message"], color=Palette.WARNING)
            brand_footer(embed, "You asked me to remind you")
            try:
                await channel.send(content=f"<@{item['user_id']}>", embed=embed)
            except discord.HTTPException:
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
        await interaction.response.send_message(embed=view.build_embed(), view=view)
        view.message = await interaction.original_response()

    @app_commands.command(name="remind", description="Set a reminder (e.g. 10m, 1h30m, 2d)")
    @app_commands.describe(duration="When? e.g. 10m, 1h30m, 2d", message="What should I remind you about?")
    async def remind(self, interaction: discord.Interaction, duration: str, message: str):
        delta = parse_duration(duration)
        if not delta:
            embed = make_embed(
                "🤔 I did not get that",
                "Use formats like `10m`, `1h30m`, `2d`, `1w`.",
                color=Palette.WARNING,
            )
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        if delta.days > 90:
            embed = make_embed("📅 Too far away", "Reminders max out at 90 days.", color=Palette.WARNING)
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        due_at = datetime.now(UTC) + delta
        reminders = await asyncio.to_thread(load_data, "reminders", [])
        reminders.append(
            {
                "id": uuid.uuid4().hex[:8],
                "user_id": interaction.user.id,
                "channel_id": interaction.channel_id,
                "message": message,
                "due_at": due_at.isoformat(),
            }
        )
        await asyncio.to_thread(save_data, "reminders", reminders)

        embed = make_embed(
            "⏰ Reminder set!",
            f"I'll ping you {discord.utils.format_dt(due_at, 'R')} about:\n> {message}",
            color=Palette.SUCCESS,
        )
        brand_footer(embed, "Reminder saved")
        await respond(interaction, embed, ephemeral=True)

    @app_commands.command(name="reminders", description="See and cancel your pending reminders")
    async def reminders(self, interaction: discord.Interaction):
        reminders = await asyncio.to_thread(load_data, "reminders", [])
        mine = sorted(
            (item for item in reminders if item["user_id"] == interaction.user.id),
            key=lambda item: item["due_at"],
        )
        if not mine:
            embed = make_embed("💤 Nothing pending", "You have no reminders. Set one with `/remind`!", color=Palette.INFO)
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        lines = []
        for item in mine[:15]:
            due = datetime.fromisoformat(item["due_at"])
            lines.append(f"⏰ {discord.utils.format_dt(due, 'R')} — {truncate(item['message'], 80)}")

        embed = make_embed("🗓️ Your reminders", "\n".join(lines), color=Palette.INFO)
        brand_footer(embed, f"{len(mine)} pending")
        view = discord.ui.View(timeout=180)
        view.add_item(ReminderCancelSelect(interaction.user.id, mine))
        await respond(interaction, embed, view=view, ephemeral=True)

    @app_commands.command(name="userinfo", description="Detailed profile card for a member")
    @app_commands.describe(member="Whose profile? (defaults to you)")
    @app_commands.guild_only()
    async def userinfo(self, interaction: discord.Interaction, member: discord.Member | None = None):
        target = member or interaction.user
        badges = [BADGE_LABELS[name] for name, value in target.public_flags if value and name in BADGE_LABELS]
        roles = [role.mention for role in reversed(target.roles[1:])][:5]

        color = target.color.value if target.color.value else Palette.PRIMARY
        embed = make_embed(f"👤 {target.display_name}", f"{target.mention} • `{target.id}`", color=color)
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(
            name="📅 Dates",
            value=(
                f"Created: {discord.utils.format_dt(target.created_at, 'R')}\n"
                f"Joined: {discord.utils.format_dt(target.joined_at, 'R') if target.joined_at else 'Unknown'}"
            ),
            inline=True,
        )
        embed.add_field(
            name="🎭 Identity",
            value=(
                f"Bot: `{('Yes 🤖' if target.bot else 'No')}`\n"
                f"Top role: {target.top_role.mention if target.top_role else '`None`'}"
            ),
            inline=True,
        )
        embed.add_field(
            name=f"🏷️ Roles ({max(len(target.roles) - 1, 0)})",
            value=" ".join(roles) if roles else "`No roles`",
            inline=False,
        )
        if badges:
            embed.add_field(name="✨ Badges", value=" • ".join(badges), inline=False)
        brand_footer(embed, "User info")
        await respond(interaction, embed)

    @app_commands.command(name="serverinfo", description="Everything about this server in one card")
    @app_commands.guild_only()
    async def serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild
        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)

        embed = make_embed(f"🏰 {guild.name}", guild.description or "A great place to be.", color=Palette.PURPLE)
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(
            name="👥 People",
            value=(
                f"Members: `{guild.member_count:,}`\n"
                f"Owner: {guild.owner.mention if guild.owner else 'Unknown'}"
            ),
            inline=True,
        )
        embed.add_field(
            name="💬 Channels",
            value=f"Text: `{text_channels}`\nVoice: `{voice_channels}`",
            inline=True,
        )
        embed.add_field(
            name="🎨 Flair",
            value=f"Roles: `{len(guild.roles)}`\nEmojis: `{len(guild.emojis)}`",
            inline=True,
        )
        embed.add_field(
            name="🚀 Boosts",
            value=f"Level: `{guild.premium_tier}`\nBoosts: `{guild.premium_subscription_count or 0}`",
            inline=True,
        )
        embed.add_field(
            name="📅 Created",
            value=discord.utils.format_dt(guild.created_at, "D"),
            inline=True,
        )
        if guild.banner:
            embed.set_image(url=guild.banner.url)
        brand_footer(embed, f"Server ID: {guild.id}")
        await respond(interaction, embed)

    @app_commands.command(name="avatar", description="Full-size avatar of a member")
    @app_commands.describe(user="Whose avatar? (defaults to you)")
    async def avatar(self, interaction: discord.Interaction, user: discord.User | None = None):
        target = user or interaction.user
        asset = target.display_avatar.with_size(1024)

        embed = make_embed(f"🖼️ {target.display_name}'s avatar", color=Palette.FUN)
        embed.set_image(url=asset.url)
        brand_footer(embed, "Avatar viewer")

        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label="Open original", url=asset.url))
        await respond(interaction, embed, view=view)

    @app_commands.command(name="roleinfo", description="Details about a role")
    @app_commands.describe(role="Which role?")
    @app_commands.guild_only()
    async def roleinfo(self, interaction: discord.Interaction, role: discord.Role):
        color = role.color.value if role.color.value else Palette.PRIMARY
        embed = make_embed(f"🏷️ {role.name}", f"{role.mention} • `{role.id}`", color=color)
        embed.add_field(
            name="Details",
            value=(
                f"Members: `{len(role.members)}`\n"
                f"Position: `{role.position}`\n"
                f"Color: `#{role.color.value:06X}`"
            ),
            inline=True,
        )
        embed.add_field(
            name="Flags",
            value=(
                f"Hoisted: `{('Yes' if role.hoist else 'No')}`\n"
                f"Mentionable: `{('Yes' if role.mentionable else 'No')}`\n"
                f"Managed: `{('Yes' if role.managed else 'No')}`"
            ),
            inline=True,
        )
        embed.add_field(
            name="📅 Created",
            value=discord.utils.format_dt(role.created_at, "R"),
            inline=False,
        )
        brand_footer(embed, "Role info")
        await respond(interaction, embed)

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

        unix = int(moment.timestamp())
        lines = [f"`<t:{unix}:{code}>` → <t:{unix}:{code}> — {label}" for code, label in TIMESTAMP_STYLES]
        embed = make_embed("🕐 Timestamp generator", "\n".join(lines), color=Palette.TEAL)
        brand_footer(embed, "Copy the code, paste anywhere")
        await respond(interaction, embed, ephemeral=True)

    @app_commands.command(name="choose", description="Can't decide? Let fate pick for you")
    @app_commands.describe(options="Options separated by commas, e.g. pizza, sushi, tacos")
    async def choose(self, interaction: discord.Interaction, options: str):
        choices = [item.strip() for item in options.split(",") if item.strip()]
        if len(choices) < 2:
            embed = make_embed("🤔 Give me options", "I need at least two options separated by commas.", color=Palette.WARNING)
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        winner = random.choice(choices)
        embed = make_embed(
            "🎯 The wheel of fate has spoken",
            f"Out of {', '.join(f'`{choice}`' for choice in choices)}…\n\n# 🏆 {winner}",
            color=Palette.FUN,
        )
        brand_footer(embed, "Destiny delivered")
        await respond(interaction, embed)

    @app_commands.command(name="color", description="Preview any hex color")
    @app_commands.describe(hex_code="Hex color, e.g. #5865F2")
    async def color(self, interaction: discord.Interaction, hex_code: str):
        match = HEX_COLOR_PATTERN.match(hex_code.strip())
        if not match:
            embed = make_embed("🎨 Invalid color", "Give me a hex color like `#5865F2`.", color=Palette.WARNING)
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        value = int(match.group(1), 16)
        red, green, blue = (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF
        embed = make_embed(f"🎨 #{match.group(1).upper()}", color=value)
        embed.add_field(name="RGB", value=f"`{red}, {green}, {blue}`", inline=True)
        embed.add_field(name="Int", value=f"`{value}`", inline=True)
        embed.set_image(url=f"https://singlecolorimage.com/get/{match.group(1)}/400x100")
        brand_footer(embed, "Color preview")
        await respond(interaction, embed)


async def setup(bot):
    await bot.add_cog(Utility(bot))
