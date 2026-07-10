"""💰 Economy category — coins, daily streaks, work, gambling and a trophy shop."""

import random
from datetime import UTC, datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from core.database import load_economy_data, save_economy_data
from core.theme import Palette, brand_footer, make_embed, progress_bar
from core.utils import humanize_number, respond

CURRENCY = "🪙"
DAILY_BASE = 200
DAILY_STREAK_BONUS = 50
WORK_COOLDOWN = timedelta(hours=1)
TROPHIES = {
    "star": ("⭐ Star", 1000),
    "rocket": ("🚀 Rocket", 2500),
    "gem": ("💎 Gem", 5000),
    "crown": ("👑 Crown", 10000),
    "trophy": ("🏆 Golden Trophy", 25000),
}
SLOT_REELS = ["🍒", "🍋", "🍇", "💎", "7️⃣"]
WORK_FLAVORS = [
    "You debugged production at 3 AM",
    "You wrote documentation nobody will read",
    "You closed 14 browser tabs and found the bug",
    "You reviewed a 2,000-line pull request",
    "You explained recursion using recursion",
    "You turned it off and on again — it worked",
    "You renamed `data2_final_FINAL.py` responsibly",
    "You centered a div on the first try",
]


def parse_saved_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def load_economy():
    return load_economy_data()


def save_economy(data):
    save_economy_data(data)


def get_wallet(data, guild_id, user_id):
    guild_data = data.setdefault(str(guild_id), {})
    return guild_data.setdefault(
        str(user_id),
        {"coins": 0, "daily_streak": 0, "last_daily": None, "last_work": None, "trophies": []},
    )


class Economy(commands.Cog):
    """Server currency with daily rewards, work and games of chance."""

    EMOJI = "💰"
    COLOR = Palette.GOLD
    DESCRIPTION = "Coins, daily streaks, work, gambling, slots and a trophy shop."

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="balance", description="Check a wallet")
    @app_commands.describe(member="Whose wallet? (defaults to you)")
    @app_commands.guild_only()
    async def balance(self, interaction: discord.Interaction, member: discord.Member | None = None):
        target = member or interaction.user
        data = load_economy()
        wallet = get_wallet(data, interaction.guild_id, target.id)

        embed = make_embed(
            f"💰 {target.display_name}'s wallet",
            f"# {CURRENCY} {humanize_number(wallet['coins'])}",
            color=Palette.GOLD,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="🔥 Daily streak", value=f"`{wallet.get('daily_streak', 0)} day(s)`", inline=True)
        trophies = wallet.get("trophies", [])
        if trophies:
            shelf = " ".join(TROPHIES[t][0].split()[0] for t in trophies if t in TROPHIES)
            embed.add_field(name="🏆 Trophy shelf", value=shelf, inline=True)
        brand_footer(embed, "Economy")
        await respond(interaction, embed)

    @app_commands.command(name="daily", description="Claim your daily coins (streak bonus!)")
    @app_commands.guild_only()
    async def daily(self, interaction: discord.Interaction):
        data = load_economy()
        wallet = get_wallet(data, interaction.guild_id, interaction.user.id)
        now = datetime.now(UTC)

        last_daily = parse_saved_datetime(wallet.get("last_daily"))
        if last_daily:
            if now - last_daily < timedelta(hours=24):
                next_claim = last_daily + timedelta(hours=24)
                embed = make_embed(
                    "⏳ Already claimed",
                    f"Come back {discord.utils.format_dt(next_claim, 'R')}!",
                    color=Palette.WARNING,
                )
                brand_footer(embed, "Economy")
                return await respond(interaction, embed, ephemeral=True)
            streak = wallet.get("daily_streak", 0) + 1 if now - last_daily < timedelta(hours=48) else 1
        else:
            streak = 1

        reward = DAILY_BASE + DAILY_STREAK_BONUS * min(streak - 1, 10)
        wallet["coins"] += reward
        wallet["daily_streak"] = streak
        wallet["last_daily"] = now.isoformat()
        save_economy(data)

        embed = make_embed(
            "🎁 Daily reward claimed!",
            f"# +{CURRENCY} {reward}\n\n🔥 Streak: `{streak} day(s)` {progress_bar(min(streak, 11), 11, slots=11, filled='🔥', empty='▫️')}",
            color=Palette.GOLD,
        )
        brand_footer(embed, f"Balance: {humanize_number(wallet['coins'])} coins")
        await respond(interaction, embed)

    @app_commands.command(name="work", description="Do an honest hour of work for coins")
    @app_commands.guild_only()
    async def work(self, interaction: discord.Interaction):
        data = load_economy()
        wallet = get_wallet(data, interaction.guild_id, interaction.user.id)
        now = datetime.now(UTC)

        last_work = parse_saved_datetime(wallet.get("last_work"))
        if last_work:
            if now - last_work < WORK_COOLDOWN:
                next_shift = last_work + WORK_COOLDOWN
                embed = make_embed(
                    "😮‍💨 Still on break",
                    f"Next shift starts {discord.utils.format_dt(next_shift, 'R')}.",
                    color=Palette.WARNING,
                )
                brand_footer(embed, "Economy")
                return await respond(interaction, embed, ephemeral=True)

        earnings = random.randint(50, 150)
        wallet["coins"] += earnings
        wallet["last_work"] = now.isoformat()
        save_economy(data)

        embed = make_embed(
            "🔨 Shift complete",
            f"{random.choice(WORK_FLAVORS)} and earned **{CURRENCY} {earnings}**!",
            color=Palette.TEAL,
        )
        brand_footer(embed, f"Balance: {humanize_number(wallet['coins'])} coins")
        await respond(interaction, embed)

    @app_commands.command(name="pay", description="Send coins to another member")
    @app_commands.describe(member="Who receives the coins?", amount="How many coins?")
    @app_commands.guild_only()
    async def pay(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        amount: app_commands.Range[int, 1, 1000000],
    ):
        if member.bot or member.id == interaction.user.id:
            embed = make_embed("🤔 Invalid target", "Pick a real member other than yourself.", color=Palette.WARNING)
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        data = load_economy()
        sender = get_wallet(data, interaction.guild_id, interaction.user.id)
        if sender["coins"] < amount:
            embed = make_embed("💸 Not enough coins", f"You only have {CURRENCY} {humanize_number(sender['coins'])}.", color=Palette.DANGER)
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        receiver = get_wallet(data, interaction.guild_id, member.id)
        sender["coins"] -= amount
        receiver["coins"] += amount
        save_economy(data)

        embed = make_embed(
            "💸 Payment sent",
            f"{interaction.user.mention} → {member.mention}\n# {CURRENCY} {humanize_number(amount)}",
            color=Palette.SUCCESS,
        )
        brand_footer(embed, "Economy")
        await respond(interaction, embed)

    @app_commands.command(name="gamble", description="Double or nothing")
    @app_commands.describe(amount="How much to risk? (min 10)")
    @app_commands.guild_only()
    async def gamble(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 10, 1000000],
    ):
        data = load_economy()
        wallet = get_wallet(data, interaction.guild_id, interaction.user.id)
        if wallet["coins"] < amount:
            embed = make_embed("💸 Not enough coins", f"You only have {CURRENCY} {humanize_number(wallet['coins'])}.", color=Palette.DANGER)
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        if random.random() < 0.47:
            wallet["coins"] += amount
            embed = make_embed("🎉 You won!", f"# +{CURRENCY} {humanize_number(amount)}", color=Palette.SUCCESS)
        else:
            wallet["coins"] -= amount
            embed = make_embed("💀 You lost…", f"# -{CURRENCY} {humanize_number(amount)}", color=Palette.DANGER)
        save_economy(data)

        brand_footer(embed, f"Balance: {humanize_number(wallet['coins'])} coins • The house always wins")
        await respond(interaction, embed)

    @app_commands.command(name="slots", description="Spin the slot machine")
    @app_commands.describe(amount="Your bet (min 10)")
    @app_commands.guild_only()
    async def slots(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 10, 100000],
    ):
        data = load_economy()
        wallet = get_wallet(data, interaction.guild_id, interaction.user.id)
        if wallet["coins"] < amount:
            embed = make_embed("💸 Not enough coins", f"You only have {CURRENCY} {humanize_number(wallet['coins'])}.", color=Palette.DANGER)
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        reels = [random.choice(SLOT_REELS) for _ in range(3)]
        display = " | ".join(reels)

        if reels[0] == reels[1] == reels[2]:
            multiplier = 10 if reels[0] == "7️⃣" else 5
            net = amount * multiplier - amount
            title, color = f"🎰 JACKPOT x{multiplier}!", Palette.GOLD
        elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
            # 1.5x payout keeps the long-run house edge at ~4% (a 2x pair made slots player-positive)
            net = amount // 2
            title, color = "🎰 Two of a kind!", Palette.SUCCESS
        else:
            net = -amount
            title, color = "🎰 No luck…", Palette.DANGER

        wallet["coins"] += net
        save_economy(data)

        sign = "+" if net >= 0 else "-"
        embed = make_embed(title, f"# [ {display} ]\n\n**{sign}{CURRENCY} {humanize_number(abs(net))}**", color=color)
        brand_footer(embed, f"Balance: {humanize_number(wallet['coins'])} coins")
        await respond(interaction, embed)

    @app_commands.command(name="richest", description="Top 10 richest members")
    @app_commands.guild_only()
    async def richest(self, interaction: discord.Interaction):
        data = load_economy()
        guild_data = data.get(str(interaction.guild_id), {})
        ordered = sorted(guild_data.items(), key=lambda kv: kv[1].get("coins", 0), reverse=True)
        ordered = [(uid, wallet) for uid, wallet in ordered if wallet.get("coins")]

        if not ordered:
            embed = make_embed("🌱 Nothing yet", "Nobody has earned coins. Try `/daily`!", color=Palette.INFO)
            brand_footer(embed)
            return await respond(interaction, embed)

        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = [
            f"{medals.get(index, f'`#{index}`')} <@{uid}> — {CURRENCY} `{humanize_number(wallet['coins'])}`"
            for index, (uid, wallet) in enumerate(ordered[:10], 1)
        ]
        embed = make_embed(f"💰 Richest • {interaction.guild.name}", "\n".join(lines), color=Palette.GOLD)
        brand_footer(embed, "Economy leaderboard")
        await respond(interaction, embed)

    @app_commands.command(name="shop", description="Browse the trophy shop")
    @app_commands.guild_only()
    async def shop(self, interaction: discord.Interaction):
        lines = [
            f"{label} — {CURRENCY} `{humanize_number(price)}`"
            for label, price in TROPHIES.values()
        ]
        embed = make_embed(
            "🛍️ Trophy shop",
            "Flex on the leaderboard — trophies show on your `/balance`.\n\n" + "\n".join(lines),
            color=Palette.PURPLE,
        )
        brand_footer(embed, "Buy with /buy")
        await respond(interaction, embed)

    @app_commands.command(name="buy", description="Buy a trophy from the shop")
    @app_commands.describe(item="Which trophy?")
    @app_commands.choices(
        item=[app_commands.Choice(name=f"{label} — {price}", value=key) for key, (label, price) in TROPHIES.items()]
    )
    @app_commands.guild_only()
    async def buy(self, interaction: discord.Interaction, item: app_commands.Choice[str]):
        label, price = TROPHIES[item.value]
        data = load_economy()
        wallet = get_wallet(data, interaction.guild_id, interaction.user.id)

        if item.value in wallet.get("trophies", []):
            embed = make_embed("🤷 Already owned", f"You already have {label}.", color=Palette.WARNING)
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        if wallet["coins"] < price:
            missing = price - wallet["coins"]
            embed = make_embed("💸 Not enough coins", f"You need {CURRENCY} `{humanize_number(missing)}` more for {label}.", color=Palette.DANGER)
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        wallet["coins"] -= price
        wallet.setdefault("trophies", []).append(item.value)
        save_economy(data)

        embed = make_embed("🛍️ Purchase complete!", f"{label} is now on your shelf. Flex responsibly. 😎", color=Palette.SUCCESS)
        brand_footer(embed, f"Balance: {humanize_number(wallet['coins'])} coins")
        await respond(interaction, embed)


async def setup(bot):
    await bot.add_cog(Economy(bot))
