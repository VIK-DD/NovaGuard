"""🎁 Giveaways category — button-entry giveaways with automatic winner draws."""

import random
from datetime import UTC, datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.storage import load_data, save_data
from core.theme import Palette, brand_footer, make_embed
from core.utils import parse_duration, respond


def load_giveaways():
    return load_data("giveaways", [])


def save_giveaways(entries):
    save_data("giveaways", entries)


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
        entries = load_giveaways()
        entry = next((g for g in entries if g["message_id"] == self.message_id), None)
        if entry is None or entry.get("ended"):
            return await interaction.response.send_message("This giveaway has already ended!", ephemeral=True)

        user_id = interaction.user.id
        if user_id in entry["entrants"]:
            entry["entrants"].remove(user_id)
            note = "You left the giveaway. 😢"
        else:
            entry["entrants"].append(user_id)
            note = "You're in — good luck! 🍀"
        save_giveaways(entries)

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

    async def finish_giveaway(self, entry, entries):
        entry["ended"] = True
        entrants = entry.get("entrants", [])
        count = min(entry["winners"], len(entrants))
        winner_ids = random.sample(entrants, count) if count else []
        entry["winner_ids"] = winner_ids
        save_giveaways(entries)

        channel = self.bot.get_channel(entry["channel_id"])
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(entry["channel_id"])
            except discord.HTTPException:
                return winner_ids

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
        return winner_ids

    @tasks.loop(seconds=30)
    async def giveaway_watcher(self):
        entries = load_giveaways()
        now = datetime.now(UTC)
        for entry in entries:
            if not entry.get("ended") and datetime.fromisoformat(entry["ends_at"]) <= now:
                await self.finish_giveaway(entry, entries)

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
        delta = parse_duration(duration)
        if not delta or delta < timedelta(minutes=1) or delta > timedelta(days=30):
            embed = make_embed(
                "🤔 Invalid duration",
                "Use formats like `30m`, `1h`, `2d` — between 1 minute and 30 days.",
                color=Palette.WARNING,
            )
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        ends_at = datetime.now(UTC) + delta
        entry = {
            "message_id": 0,
            "channel_id": interaction.channel_id,
            "guild_id": interaction.guild_id,
            "prize": prize,
            "winners": winners,
            "host_id": interaction.user.id,
            "host_name": interaction.user.display_name,
            "ends_at": ends_at.isoformat(),
            "entrants": [],
            "ended": False,
        }

        await interaction.response.send_message(embed=build_giveaway_embed(entry))
        message = await interaction.original_response()
        entry["message_id"] = message.id

        view = discord.ui.View(timeout=None)
        view.add_item(GiveawayButton(message.id))
        await message.edit(view=view)

        entries = load_giveaways()
        entries.append(entry)
        save_giveaways(entries)

    @giveaway.command(name="end", description="End a giveaway right now")
    @app_commands.describe(message_id="The giveaway message ID")
    async def giveaway_end(self, interaction: discord.Interaction, message_id: str):
        entries = load_giveaways()
        entry = next((g for g in entries if str(g["message_id"]) == message_id.strip()), None)
        if entry is None or entry.get("ended"):
            embed = make_embed("🔍 Not found", "No active giveaway with that message ID.", color=Palette.WARNING)
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        await self.finish_giveaway(entry, entries)
        embed = make_embed("🏁 Giveaway ended", f"**{entry['prize']}** was drawn early.", color=Palette.SUCCESS)
        brand_footer(embed)
        await respond(interaction, embed, ephemeral=True)

    @giveaway.command(name="reroll", description="Pick new winner(s) for an ended giveaway")
    @app_commands.describe(message_id="The giveaway message ID")
    async def giveaway_reroll(self, interaction: discord.Interaction, message_id: str):
        entries = load_giveaways()
        entry = next((g for g in entries if str(g["message_id"]) == message_id.strip()), None)
        if entry is None or not entry.get("ended"):
            embed = make_embed("🔍 Not found", "No **ended** giveaway with that message ID.", color=Palette.WARNING)
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        entrants = entry.get("entrants", [])
        if not entrants:
            embed = make_embed("😢 No entries", "Nobody entered that giveaway — nothing to reroll.", color=Palette.WARNING)
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        count = min(entry["winners"], len(entrants))
        winner_ids = random.sample(entrants, count)
        entry["winner_ids"] = winner_ids
        save_giveaways(entries)

        mentions = ", ".join(f"<@{uid}>" for uid in winner_ids)
        embed = make_embed("🎲 Reroll!", f"New winner{'s' if count > 1 else ''} for **{entry['prize']}**: {mentions} 🎊", color=Palette.GOLD)
        brand_footer(embed, "Giveaway reroll")
        await respond(interaction, embed)


async def setup(bot):
    await bot.add_cog(Giveaways(bot))
