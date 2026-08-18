"""🎁 Giveaways category — button-entry giveaways with automatic winner draws."""

import logging
import asyncio
import random
import re
import time
from datetime import UTC, datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.loop_guard import keep_running
from core.storage import load_data, save_data
from core.theme import Palette, brand_footer, make_embed
from core.utils import defer_interaction, parse_duration, respond

log = logging.getLogger(__name__)



def load_giveaways():
    return load_data("giveaways", [])


def save_giveaways(entries):
    save_data("giveaways", entries)


async def load_giveaways_async():
    return await asyncio.to_thread(load_giveaways)


async def save_giveaways_async(entries):
    await asyncio.to_thread(save_giveaways, entries)


# Serialises every load -> mutate -> save on the giveaways file. Without it two
# concurrent button clicks (or a click racing the watcher) both read the same
# list and the second save silently drops the first one's change.
_STORE_LOCK = asyncio.Lock()


def validate_giveaway_input(duration, prize, winners):
    """Normalize dashboard/slash input before a Discord message is created."""
    errors = []
    duration_text = str(duration or "").strip().lower()
    if not re.fullmatch(r"(?:\d+\s*[smhdw]\s*)+", duration_text):
        delta = None
    else:
        delta = parse_duration(duration_text)
    if not delta or delta < timedelta(minutes=1) or delta > timedelta(days=30):
        errors.append("duration must be between 1 minute and 30 days, for example 30m, 1h or 2d")

    clean_prize = " ".join(str(prize or "").split())
    if not clean_prize or len(clean_prize) > 200:
        errors.append("prize must contain 1–200 characters")

    if isinstance(winners, bool) or not isinstance(winners, int) or not 1 <= winners <= 10:
        errors.append("winners must be a whole number between 1 and 10")
    return delta, clean_prize, winners, errors


def build_giveaway_embed(entry, ended=False, winner_ids=None):
    ends_at = datetime.fromisoformat(entry["ends_at"])
    entrants = entry.get("entrants", [])

    if ended:
        if winner_ids:
            winners_text = ", ".join(f"<@{uid}>" for uid in winner_ids)
            description = f"# {entry['prize']}\n\n🏆 **Winner{'s' if len(winner_ids) > 1 else ''}:** {winners_text}"
        else:
            description = f"# {entry['prize']}\n\n😢 No valid entries — nobody wins this time."
        embed = make_embed("🏁 GIVEAWAY ENDED", description, color=Palette.DARK)
    else:
        description = (
            f"# {entry['prize']}\n\n"
            f"Ends {discord.utils.format_dt(ends_at, 'R')} ({discord.utils.format_dt(ends_at, 'f')})\n"
            f"Winners: `{entry['winners']}` • Entries: `{len(entrants)}`\n\n"
            f"**Click 🎉 below to enter!**"
        )
        embed = make_embed("🎁 GIVEAWAY", description, color=Palette.FUN)

    brand_footer(embed, f"Hosted by {entry.get('host_name', 'staff')}")
    return embed


class GiveawayButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"gw:(?P<message_id>\d+)",
):
    _cooldown: dict[int, float] = {}  # user_id -> last click, anti-spam
    _COOLDOWN = 2.0

    def __init__(self, message_id: int):
        super().__init__(
            discord.ui.Button(
                emoji="🎉",
                label="Enter giveaway",
                style=discord.ButtonStyle.success,
                custom_id=f"gw:{message_id}",
            )
        )
        self.message_id = message_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["message_id"]))

    async def callback(self, interaction: discord.Interaction):
        now = time.monotonic()
        if now - self._cooldown.get(interaction.user.id, 0.0) < self._COOLDOWN:
            return await interaction.response.send_message("⏳ Slow down a moment.", ephemeral=True)
        self._cooldown[interaction.user.id] = now
        if len(self._cooldown) > 4000:
            for uid in [u for u, t in self._cooldown.items() if now - t > 60]:
                self._cooldown.pop(uid, None)

        note = None
        async with _STORE_LOCK:
            entries = await load_giveaways_async()
            entry = next((g for g in entries if g["message_id"] == self.message_id), None)
            if entry is not None and not entry.get("ended"):
                user_id = interaction.user.id
                if user_id in entry["entrants"]:
                    entry["entrants"].remove(user_id)
                    note = "You left the giveaway. 😢"
                else:
                    entry["entrants"].append(user_id)
                    note = "You're in — good luck! 🍀"
                await save_giveaways_async(entries)

        if entry is None or entry.get("ended") or note is None:
            return await interaction.response.send_message("This giveaway has already ended!", ephemeral=True)

        await interaction.response.edit_message(embed=build_giveaway_embed(entry))
        await interaction.followup.send(note, ephemeral=True)


class Giveaways(commands.Cog):
    """Giveaways with live entry counts and automatic draws."""

    EMOJI = "🎁"
    COLOR = Palette.FUN
    DESCRIPTION = "Button-entry giveaways with automatic winner draws and rerolls."

    giveaway = app_commands.Group(
        name="giveaway",
        description="Giveaway management",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_dynamic_items(GiveawayButton)
        self.giveaway_watcher.start()

    async def cog_unload(self):
        self.giveaway_watcher.cancel()

    def _entry_channel(self, entry):
        channel = self.bot.get_channel(entry["channel_id"])
        return channel

    async def _fetch_entry_channel(self, entry):
        channel = self._entry_channel(entry)
        if channel is not None:
            return channel
        try:
            return await self.bot.fetch_channel(entry["channel_id"])
        except discord.HTTPException:
            return None

    async def start_giveaway(
        self,
        channel,
        *,
        guild_id,
        host_id,
        host_name,
        duration,
        prize,
        winners,
    ):
        ends_at = datetime.now(UTC) + duration
        entry = {
            "message_id": 0,
            "channel_id": channel.id,
            "guild_id": guild_id,
            "prize": prize,
            "winners": winners,
            "host_id": host_id,
            "host_name": host_name,
            "ends_at": ends_at.isoformat(),
            "entrants": [],
            "ended": False,
        }
        message = await channel.send(embed=build_giveaway_embed(entry))
        entry["message_id"] = message.id
        view = discord.ui.View(timeout=None)
        view.add_item(GiveawayButton(message.id))
        try:
            await message.edit(view=view)
        except discord.HTTPException:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            raise

        async with _STORE_LOCK:
            try:
                entries = await load_giveaways_async()
                entries.append(entry)
                await save_giveaways_async(entries)
            except (OSError, TypeError, ValueError):
                try:
                    await message.delete()
                except discord.HTTPException:
                    pass
                raise
        return entry

    async def finish_giveaway(self, message_id):
        """End a giveaway by message id. Draws and saves under the store lock
        (re-reading the file so a racing button click is never lost), then does
        the slow Discord sends outside it. Returns the entry, or None when no
        active giveaway matched."""
        async with _STORE_LOCK:
            entries = await load_giveaways_async()
            entry = next((g for g in entries if str(g["message_id"]) == str(message_id)), None)
            if entry is None or entry.get("ended"):
                return None
            entry["ended"] = True
            entrants = entry.get("entrants", [])
            count = min(entry["winners"], len(entrants))
            winner_ids = random.sample(entrants, count) if count else []
            entry["winner_ids"] = winner_ids
            await save_giveaways_async(entries)

        channel = await self._fetch_entry_channel(entry)
        if channel is None:
            return entry

        try:
            message = await channel.fetch_message(entry["message_id"])
            await message.edit(embed=build_giveaway_embed(entry, ended=True, winner_ids=winner_ids), view=None)
        except discord.HTTPException:
            pass

        try:
            if winner_ids:
                mentions = ", ".join(f"<@{uid}>" for uid in winner_ids)
                embed = make_embed(
                    "🎊 We have a winner!",
                    f"Congratulations {mentions} — you won **{entry['prize']}**!",
                    color=Palette.GOLD,
                )
            else:
                embed = make_embed("😢 No winner", f"Nobody entered the giveaway for **{entry['prize']}**.", color=Palette.DARK)
            brand_footer(embed, "Giveaway result")
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass
        return entry

    async def reroll_giveaway(self, message_id):
        """Draw and persist replacement winners, then announce in the original channel."""
        async with _STORE_LOCK:
            entries = await load_giveaways_async()
            entry = next((g for g in entries if str(g["message_id"]) == str(message_id)), None)
            if entry is None or not entry.get("ended"):
                return None, None, False
            entrants = entry.get("entrants", [])
            if not entrants:
                return entry, [], False
            count = min(entry["winners"], len(entrants))
            winner_ids = random.sample(entrants, count)
            entry["winner_ids"] = winner_ids
            await save_giveaways_async(entries)

        channel = await self._fetch_entry_channel(entry)
        announced = False
        if channel is not None:
            mentions = ", ".join(f"<@{uid}>" for uid in winner_ids)
            embed = make_embed(
                "🎲 Giveaway rerolled",
                f"New winner{'s' if len(winner_ids) > 1 else ''} for **{entry['prize']}**: {mentions} 🎊",
                color=Palette.GOLD,
            )
            brand_footer(embed, "Giveaway reroll")
            try:
                await channel.send(embed=embed)
                announced = True
            except discord.HTTPException:
                pass
        return entry, winner_ids, announced

    @tasks.loop(seconds=30)
    @keep_running(log, "giveaway watcher")
    async def giveaway_watcher(self):
        entries = await load_giveaways_async()
        now = datetime.now(UTC)
        for entry in entries:
            if entry.get("ended"):
                continue
            # A corrupt ends_at must not raise: an unhandled exception stops a
            # tasks.loop for good and no giveaway would ever be drawn again.
            try:
                due = datetime.fromisoformat(entry["ends_at"]) <= now
            except (KeyError, TypeError, ValueError):
                log.warning(f"Giveaway entry #{entry.get('message_id')} has an invalid ends_at; skipping")
                continue
            if due:
                await self.finish_giveaway(entry.get("message_id"))

    @giveaway_watcher.before_loop
    async def before_giveaway_watcher(self):
        await self.bot.wait_until_ready()

    @giveaway.command(name="start", description="Start a giveaway (e.g. 1h, 1d)")
    @app_commands.describe(
        duration="How long? e.g. 30m, 1h, 2d (max 30 days)",
        prize="What are you giving away?",
        winners="Number of winners (1-10)",
    )
    async def giveaway_start(
        self,
        interaction: discord.Interaction,
        duration: str,
        prize: str,
        winners: app_commands.Range[int, 1, 10] = 1,
    ):
        delta, prize, winners, errors = validate_giveaway_input(duration, prize, winners)
        if errors:
            embed = make_embed(
                "🤔 Invalid duration",
                "\n".join(f"• {error}" for error in errors),
                color=Palette.WARNING,
            )
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        await defer_interaction(interaction, ephemeral=True)
        try:
            entry = await self.start_giveaway(
                interaction.channel,
                guild_id=interaction.guild_id,
                host_id=interaction.user.id,
                host_name=interaction.user.display_name,
                duration=delta,
                prize=prize,
                winners=winners,
            )
        except discord.HTTPException:
            embed = make_embed(
                "⚠️ Giveaway not published",
                "Discord did not accept the giveaway message. Nothing was saved.",
                color=Palette.DANGER,
            )
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)
        except (OSError, TypeError, ValueError):
            embed = make_embed(
                "⚠️ Giveaway not saved",
                "The giveaway store is unavailable, so no active giveaway was left behind.",
                color=Palette.DANGER,
            )
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        embed = make_embed(
            "✅ Giveaway started",
            f"**{entry['prize']}** is now live in {interaction.channel.mention}.",
            color=Palette.SUCCESS,
        )
        brand_footer(embed)
        await respond(interaction, embed, ephemeral=True)

    async def _giveaway_choices(self, interaction, current, ended):
        entries = await load_giveaways_async()
        current = (current or "").lower()
        choices = []
        for entry in reversed(entries):
            if entry.get("guild_id") != interaction.guild_id:
                continue
            if bool(entry.get("ended")) is not ended:
                continue
            label = f"🎁 {entry['prize']} • {len(entry.get('entrants', []))} entries"
            value = str(entry["message_id"])
            if current and current not in label.lower() and current not in value:
                continue
            choices.append(app_commands.Choice(name=label[:100], value=value))
            if len(choices) == 25:
                break
        return choices

    async def active_giveaway_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self._giveaway_choices(interaction, current, ended=False)

    async def ended_giveaway_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self._giveaway_choices(interaction, current, ended=True)

    @giveaway.command(name="end", description="End a giveaway right now")
    @app_commands.describe(message_id="Pick the giveaway to end")
    @app_commands.autocomplete(message_id=active_giveaway_autocomplete)
    async def giveaway_end(self, interaction: discord.Interaction, message_id: str):
        await defer_interaction(interaction, ephemeral=True)
        entry = await self.finish_giveaway(message_id.strip())
        if entry is None:
            embed = make_embed("🔍 Not found", "No active giveaway with that message ID.", color=Palette.WARNING)
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        embed = make_embed("🏁 Giveaway ended", f"**{entry['prize']}** was drawn early.", color=Palette.SUCCESS)
        brand_footer(embed)
        await respond(interaction, embed, ephemeral=True)

    @giveaway.command(name="reroll", description="Pick new winner(s) for an ended giveaway")
    @app_commands.describe(message_id="Pick the ended giveaway")
    @app_commands.autocomplete(message_id=ended_giveaway_autocomplete)
    async def giveaway_reroll(self, interaction: discord.Interaction, message_id: str):
        await defer_interaction(interaction, ephemeral=True)
        entry, winner_ids, announced = await self.reroll_giveaway(message_id.strip())

        if entry is None:
            embed = make_embed("🔍 Not found", "No **ended** giveaway with that message ID.", color=Palette.WARNING)
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        if not winner_ids:
            embed = make_embed("😢 No entries", "Nobody entered that giveaway — nothing to reroll.", color=Palette.WARNING)
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        embed = make_embed(
            "🎲 Giveaway rerolled",
            (
                f"New winner{'s were' if len(winner_ids) > 1 else ' was'} announced in the original channel."
                if announced
                else "The new winner draw was saved, but Discord did not accept the announcement."
            ),
            color=Palette.SUCCESS if announced else Palette.WARNING,
        )
        brand_footer(embed, "Giveaway reroll")
        await respond(interaction, embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Giveaways(bot))
