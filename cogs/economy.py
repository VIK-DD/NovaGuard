"""💰 Economy category — coins, daily streaks, work, gambling and a trophy shop."""

import asyncio
import random
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from cogs.admin import require_admin
from core import shop
from core.admin_auth import record_audit
from core.database import load_economy_data, upsert_economy_wallets
from core.economy_settings import ECONOMY_DEFAULTS, resolve_economy
from core.storage import get_guild_settings
from core.theme import Palette, brand_footer, make_embed, progress_bar
from core.utils import humanize_number, respond

CURRENCY = "🪙"
DAILY_BASE = ECONOMY_DEFAULTS["daily_base"]
DAILY_STREAK_BONUS = ECONOMY_DEFAULTS["daily_streak_bonus"]
WORK_COOLDOWN = timedelta(minutes=ECONOMY_DEFAULTS["work_cooldown_minutes"])
# How late a claim can be and still continue a streak. Past this the streak
# resets - unless a shield is spent.
STREAK_GRACE = timedelta(hours=48)
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


# How often the in-memory wallets are written back to SQLite as a safety net.
# Mutating commands also flush right away, so this only covers missed paths.
ECONOMY_FLUSH_SECONDS = 60


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

    # Wallets live in memory and flush to SQLite, mirroring the Levels cog.
    # The old pattern (load full table -> mutate -> delete + rewrite full table,
    # synchronously on the event loop, for every command) blocked the loop on a
    # Raspberry Pi and rewrote every guild's wallets on each /daily. Command
    # handlers mutate self.data without awaiting in between, so read-modify-write
    # races cannot interleave; the flush snapshots under a lock.
    def __init__(self, bot):
        self.bot = bot
        self.data = load_economy_data()
        # Which (guild_id, user_id) wallets changed since the last flush; only
        # those rows are written, never the whole table.
        self.dirty_keys: set[tuple[str, str]] = set()
        self.flush_lock = asyncio.Lock()

    async def cog_load(self):
        self.flush_loop.start()

    async def cog_unload(self):
        self.flush_loop.cancel()
        await self.flush()

    async def flush(self):
        async with self.flush_lock:
            if not self.dirty_keys:
                return
            keys = set(self.dirty_keys)
            self.dirty_keys.clear()
            rows = [
                (guild_id, user_id, deepcopy(self.data.get(guild_id, {}).get(user_id)))
                for guild_id, user_id in keys
                if self.data.get(guild_id, {}).get(user_id) is not None
            ]
            if not rows:
                return
            try:
                await asyncio.to_thread(upsert_economy_wallets, rows)
            except Exception:
                self.dirty_keys |= keys
                raise

    async def _save(self, guild_id, *user_ids):
        for user_id in user_ids:
            self.dirty_keys.add((str(guild_id), str(user_id)))
        try:
            await self.flush()
        except Exception as error:
            print(f"Economy flush skipped due to storage issue: {error!r}")

    async def _settings_or_reject(self, interaction, feature=None):
        config = resolve_economy(get_guild_settings(interaction.guild_id))
        if not config["enabled"]:
            description = "The economy is disabled on this server."
        elif feature and not config[feature]:
            labels = {
                "transfers_enabled": "Member transfers",
                "games_enabled": "Games of chance",
                "shop_enabled": "The economy shop",
            }
            description = f"{labels.get(feature, 'This economy feature')} is disabled on this server."
        else:
            return config
        embed = make_embed("💤 Economy unavailable", description, color=Palette.WARNING)
        brand_footer(embed, "Economy")
        await respond(interaction, embed, ephemeral=True)
        return None

    def status_payload(self, guild):
        guild_data = self.data.get(str(guild.id), {})
        wallets = [
            (user_id, wallet)
            for user_id, wallet in guild_data.items()
            if isinstance(wallet, dict)
        ]
        ordered = sorted(wallets, key=lambda item: int(item[1].get("coins", 0) or 0), reverse=True)
        leaderboard = []
        for position, (user_id, wallet) in enumerate(ordered[:10], 1):
            member = guild.get_member(int(user_id)) if str(user_id).isdigit() else None
            leaderboard.append(
                {
                    "position": position,
                    "user_id": str(user_id),
                    "display_name": member.display_name if member else f"Member {user_id}",
                    "coins": max(0, int(wallet.get("coins", 0) or 0)),
                    "daily_streak": max(0, int(wallet.get("daily_streak", 0) or 0)),
                }
            )
        return {
            "tracked_wallets": len(wallets),
            "total_coins": sum(max(0, int(wallet.get("coins", 0) or 0)) for _, wallet in wallets),
            "leaderboard": leaderboard,
            "shop": [
                {
                    "key": item["key"],
                    "label": item["label"],
                    "icon": item.get("icon") or "🪙",
                    "price": int(item["price"]),
                    "kind": item["kind"],
                    "description": item.get("description"),
                }
                for item in shop.catalog()
            ],
        }

    def wallet_snapshot(self, guild_id, user_id):
        """Read a wallet without creating one.

        Other cogs ask this to find out what someone bought. get_wallet would
        write an empty wallet for every member who ever sent a message, which
        is a lot of rows for a question that is almost always "nothing".
        """
        return self.data.get(str(guild_id), {}).get(str(user_id))

    def xp_multiplier(self, guild_id, user_id) -> float:
        """How much XP a member currently earns per message, as a factor."""
        wallet = self.wallet_snapshot(guild_id, user_id)
        return shop.effect_value(wallet, shop.XP_BOOST) if wallet else 1.0

    def worn_title(self, guild_id, user_id):
        wallet = self.wallet_snapshot(guild_id, user_id)
        return shop.worn_title(wallet) if wallet else None

    async def award_coins(self, guild_id, user_id, amount) -> int:
        """Pay a member for something earned outside this cog.

        Voice time uses this. It goes through the wallet rather than the
        database directly so the balance in memory, the one every command
        reads, is the one that changed.
        """
        if not resolve_economy(get_guild_settings(guild_id))["enabled"]:
            wallet = self.wallet_snapshot(guild_id, user_id)
            return int(wallet.get("coins", 0) or 0) if wallet else 0
        wallet = get_wallet(self.data, guild_id, user_id)
        wallet["coins"] = max(0, int(wallet.get("coins", 0)) + int(amount))
        await self._save(guild_id, user_id)
        return wallet["coins"]

    @tasks.loop(seconds=ECONOMY_FLUSH_SECONDS)
    async def flush_loop(self):
        try:
            await self.flush()
        except Exception as error:
            print(f"Economy flush skipped due to storage issue: {error!r}")

    @app_commands.command(name="balance", description="Check a wallet")
    @app_commands.describe(member="Whose wallet? (defaults to you)")
    @app_commands.guild_only()
    async def balance(self, interaction: discord.Interaction, member: discord.Member | None = None):
        if await self._settings_or_reject(interaction) is None:
            return
        target = member or interaction.user
        data = self.data
        wallet = get_wallet(data, interaction.guild_id, target.id)

        title = shop.worn_title(wallet)
        embed = make_embed(
            f"💰 {target.display_name}'s wallet",
            f"# {CURRENCY} {humanize_number(wallet['coins'])}",
            color=Palette.GOLD,
        )
        if title:
            embed.set_author(name=f"{title} · {target.display_name}", icon_url=target.display_avatar.url)
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="🔥 Daily streak", value=f"`{wallet.get('daily_streak', 0)} day(s)`", inline=True)

        shields = shop.shields(wallet)
        if shields:
            embed.add_field(name="🛡️ Streak shields", value=f"`{shields}`", inline=True)

        trophies = [key for key in wallet.get("trophies", []) if shop.item(key)]
        if trophies:
            shelf = " ".join(shop.item(key)["icon"] for key in trophies)
            embed.add_field(name="🏆 Trophy shelf", value=shelf, inline=True)

        effects = shop.active_effects(wallet)
        if effects:
            embed.add_field(
                name="✨ Active",
                value="\n".join(
                    f"{shop.label_for(record.get('item'))} —"
                    f" ends {discord.utils.format_dt(shop.parse_time(record['expires_at']), 'R')}"
                    for record in effects.values()
                ),
                inline=False,
            )

        brand_footer(embed, "Economy · /shop to spend, /inventory for yours")
        await respond(interaction, embed)

    @app_commands.command(name="daily", description="Claim your daily coins (streak bonus!)")
    @app_commands.guild_only()
    async def daily(self, interaction: discord.Interaction):
        config = await self._settings_or_reject(interaction)
        if config is None:
            return
        data = self.data
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
            on_time = now - last_daily < STREAK_GRACE
            # The shield is only spent on a streak that was actually about to
            # break, and only when there is one to protect.
            saved = not on_time and wallet.get("daily_streak", 0) > 0 and shop.use_shield(wallet)
            streak = wallet.get("daily_streak", 0) + 1 if on_time or saved else 1
        else:
            saved = False
            streak = 1

        reward = config["daily_base"] + config["daily_streak_bonus"] * min(streak - 1, 10)
        wallet["coins"] += reward
        wallet["daily_streak"] = streak
        wallet["last_daily"] = now.isoformat()
        await self._save(interaction.guild_id, interaction.user.id)

        embed = make_embed(
            "🎁 Daily reward claimed!",
            f"# +{CURRENCY} {reward}\n\n🔥 Streak: `{streak} day(s)` {progress_bar(min(streak, 11), 11, slots=11, filled='🔥', empty='▫️')}",
            color=Palette.GOLD,
        )
        if saved:
            embed.add_field(
                name="🛡️ Shield used",
                value=f"Your streak survived the missed day. `{shop.shields(wallet)}` left.",
                inline=False,
            )
        brand_footer(embed, f"Balance: {humanize_number(wallet['coins'])} coins")
        await respond(interaction, embed)

    @app_commands.command(name="work", description="Do an honest hour of work for coins")
    @app_commands.guild_only()
    async def work(self, interaction: discord.Interaction):
        config = await self._settings_or_reject(interaction)
        if config is None:
            return
        data = self.data
        wallet = get_wallet(data, interaction.guild_id, interaction.user.id)
        now = datetime.now(UTC)

        base_cooldown = timedelta(minutes=config["work_cooldown_minutes"])
        cooldown = shop.work_cooldown(wallet, base_cooldown, now)
        last_work = parse_saved_datetime(wallet.get("last_work"))
        if last_work:
            if now - last_work < cooldown:
                next_shift = last_work + cooldown
                embed = make_embed(
                    "😮‍💨 Still on break",
                    f"Next shift starts {discord.utils.format_dt(next_shift, 'R')}.",
                    color=Palette.WARNING,
                )
                brand_footer(embed, "Economy")
                return await respond(interaction, embed, ephemeral=True)

        earnings = random.randint(config["work_min"], config["work_max"])
        wallet["coins"] += earnings
        wallet["last_work"] = now.isoformat()
        await self._save(interaction.guild_id, interaction.user.id)

        embed = make_embed(
            "🔨 Shift complete",
            f"{random.choice(WORK_FLAVORS)} and earned **{CURRENCY} {earnings}**!",
            color=Palette.TEAL,
        )
        if cooldown < base_cooldown:
            embed.add_field(
                name="🛠️ Work Rush",
                value=(
                    f"Next shift in `{int(cooldown.total_seconds() // 60)}m` instead of "
                    f"`{config['work_cooldown_minutes']}m`."
                ),
                inline=False,
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
        if await self._settings_or_reject(interaction, "transfers_enabled") is None:
            return
        if member.bot or member.id == interaction.user.id:
            embed = make_embed("🤔 Invalid target", "Pick a real member other than yourself.", color=Palette.WARNING)
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        data = self.data
        sender = get_wallet(data, interaction.guild_id, interaction.user.id)
        if sender["coins"] < amount:
            embed = make_embed("💸 Not enough coins", f"You only have {CURRENCY} {humanize_number(sender['coins'])}.", color=Palette.DANGER)
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        receiver = get_wallet(data, interaction.guild_id, member.id)
        sender["coins"] -= amount
        receiver["coins"] += amount
        await self._save(interaction.guild_id, interaction.user.id, member.id)

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
        config = await self._settings_or_reject(interaction, "games_enabled")
        if config is None:
            return
        if amount > config["gamble_max_bet"]:
            embed = make_embed(
                "🎚️ Bet too high",
                f"This server caps `/gamble` bets at {CURRENCY} `{humanize_number(config['gamble_max_bet'])}`.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "Economy")
            return await respond(interaction, embed, ephemeral=True)
        data = self.data
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
        await self._save(interaction.guild_id, interaction.user.id)

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
        config = await self._settings_or_reject(interaction, "games_enabled")
        if config is None:
            return
        if amount > config["slots_max_bet"]:
            embed = make_embed(
                "🎚️ Bet too high",
                f"This server caps `/slots` bets at {CURRENCY} `{humanize_number(config['slots_max_bet'])}`.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "Economy")
            return await respond(interaction, embed, ephemeral=True)
        data = self.data
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
        await self._save(interaction.guild_id, interaction.user.id)

        sign = "+" if net >= 0 else "-"
        embed = make_embed(title, f"# [ {display} ]\n\n**{sign}{CURRENCY} {humanize_number(abs(net))}**", color=color)
        brand_footer(embed, f"Balance: {humanize_number(wallet['coins'])} coins")
        await respond(interaction, embed)

    @app_commands.command(name="richest", description="Top 10 richest members")
    @app_commands.guild_only()
    async def richest(self, interaction: discord.Interaction):
        if await self._settings_or_reject(interaction) is None:
            return
        data = self.data
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

    @app_commands.command(name="shop", description="Browse the shop")
    @app_commands.guild_only()
    async def shop_command(self, interaction: discord.Interaction):
        if await self._settings_or_reject(interaction, "shop_enabled") is None:
            return
        wallet = get_wallet(self.data, interaction.guild_id, interaction.user.id)
        embed = make_embed(
            "🛍️ Shop",
            f"You have {CURRENCY} `{humanize_number(wallet['coins'])}`. Buy with `/buy`.",
            color=Palette.PURPLE,
        )

        for kind, heading in (
            (shop.BOOSTER, "⚡ Boosters"),
            (shop.PERK, "🛠️ Perks"),
            (shop.TITLE, "🎖️ Titles"),
            (shop.TROPHY, "🏆 Trophies"),
            (shop.CRATE, "📦 Crates"),
        ):
            entries = shop.catalog(kind)
            if not entries:
                continue
            lines = []
            for entry in entries:
                owned = " *(owned)*" if shop.owns(wallet, entry["key"]) else ""
                note = f"\n-# {entry['description']}" if entry.get("description") else ""
                lines.append(
                    f"{shop.label_for(entry['key'])} — {CURRENCY} `{humanize_number(entry['price'])}`"
                    f"{owned}{note}"
                )
            embed.add_field(name=heading, value="\n".join(lines), inline=False)

        brand_footer(embed, "Crates open with /crate · titles equip with /title")
        await respond(interaction, embed)

    @app_commands.command(name="buy", description="Buy something from the shop")
    @app_commands.describe(item="What are you buying?")
    @app_commands.choices(
        item=[
            app_commands.Choice(name=f"{entry['label']} — {entry['price']}", value=entry["key"])
            for entry in shop.catalog()
            if entry["kind"] != shop.CRATE
        ]
    )
    @app_commands.guild_only()
    async def buy(self, interaction: discord.Interaction, item: app_commands.Choice[str]):
        if await self._settings_or_reject(interaction, "shop_enabled") is None:
            return
        wallet = get_wallet(self.data, interaction.guild_id, interaction.user.id)
        label = shop.label_for(item.value)
        result = shop.purchase(wallet, item.value)

        if not result.ok:
            messages = {
                "owned": ("🤷 Already owned", f"You already have {label}."),
                "poor": (
                    "💸 Not enough coins",
                    f"You need {CURRENCY} `{humanize_number(result.spent)}` more for {label}.",
                ),
                "crate": ("📦 Crates open, not buy", "Use `/crate` to open one."),
                "unknown": ("🤷 No such item", "That item is not in the shop."),
            }
            title, description = messages.get(result.error, ("🤷 Not available", "Try something else."))
            embed = make_embed(title, description, color=Palette.WARNING)
            brand_footer(embed, "Economy")
            return await respond(interaction, embed, ephemeral=True)

        await self._save(interaction.guild_id, interaction.user.id)

        embed = make_embed(
            "🛍️ Purchase complete",
            f"{label} is yours.",
            color=Palette.SUCCESS,
        )
        if result.expires_at:
            embed.add_field(
                name="Runs until",
                value=discord.utils.format_dt(result.expires_at, "R"),
                inline=True,
            )
        if shop.item(item.value)["kind"] == shop.TITLE:
            embed.add_field(name="Wear it", value="`/title` to put it on.", inline=True)
        brand_footer(embed, f"Balance: {humanize_number(wallet['coins'])} coins")
        await respond(interaction, embed)

    @app_commands.command(name="inventory", description="What you own and what is running")
    @app_commands.describe(member="Whose inventory? (defaults to you)")
    @app_commands.guild_only()
    async def inventory(self, interaction: discord.Interaction, member: discord.Member | None = None):
        if await self._settings_or_reject(interaction) is None:
            return
        target = member or interaction.user
        wallet = get_wallet(self.data, interaction.guild_id, target.id)

        worn = shop.worn_title(wallet)
        embed = make_embed(
            f"🎒 {target.display_name}'s inventory",
            f"Wearing **{worn}**." if worn else "No title worn.",
            color=Palette.PURPLE,
        )

        effects = shop.active_effects(wallet)
        embed.add_field(
            name="✨ Running now",
            value="\n".join(
                f"{shop.label_for(record.get('item'))} —"
                f" ends {discord.utils.format_dt(shop.parse_time(record['expires_at']), 'R')}"
                for record in effects.values()
            )
            or "-# Nothing active.",
            inline=False,
        )

        owned = [key for key in shop.owned_keys(wallet) if shop.item(key)]
        embed.add_field(
            name="📦 Owned",
            value=" · ".join(shop.label_for(key) for key in owned) or "-# Nothing yet.",
            inline=False,
        )

        shields = shop.shields(wallet)
        if shields:
            embed.add_field(name="🛡️ Streak shields", value=f"`{shields}`", inline=True)

        brand_footer(embed, "Economy · /shop to buy more")
        await respond(interaction, embed)

    @app_commands.command(name="crate", description="Open a mystery crate")
    @app_commands.guild_only()
    async def crate(self, interaction: discord.Interaction):
        if await self._settings_or_reject(interaction, "shop_enabled") is None:
            return
        wallet = get_wallet(self.data, interaction.guild_id, interaction.user.id)
        before = wallet["coins"]
        result = shop.open_crate(wallet)

        if not result.ok:
            embed = make_embed(
                "💸 Not enough coins",
                f"A crate costs {CURRENCY} `{humanize_number(shop.SHOP_ITEMS[shop.CRATE]['price'])}`."
                f" You need {CURRENCY} `{humanize_number(result.spent)}` more.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "Economy")
            return await respond(interaction, embed, ephemeral=True)

        await self._save(interaction.guild_id, interaction.user.id)

        embed = make_embed(
            "📦 Crate opened",
            f"Inside: **{', '.join(result.granted)}**",
            color=Palette.FUN,
        )
        embed.add_field(name="Spent", value=f"{CURRENCY} `{result.spent}`", inline=True)
        embed.add_field(
            name="Balance",
            value=f"{CURRENCY} `{humanize_number(wallet['coins'])}`"
            f" ({wallet['coins'] - before:+d})",
            inline=True,
        )
        brand_footer(embed, "Economy")
        await respond(interaction, embed)

    @app_commands.command(name="title", description="Wear a title you own")
    @app_commands.describe(title="Which title? Leave empty to take yours off")
    @app_commands.choices(
        title=[
            app_commands.Choice(name=entry["label"], value=entry["key"])
            for entry in shop.catalog(shop.TITLE)
        ]
    )
    @app_commands.guild_only()
    async def title(
        self,
        interaction: discord.Interaction,
        title: app_commands.Choice[str] | None = None,
    ):
        if await self._settings_or_reject(interaction) is None:
            return
        wallet = get_wallet(self.data, interaction.guild_id, interaction.user.id)
        key = title.value if title else None

        if not shop.equip_title(wallet, key):
            embed = make_embed(
                "🤷 Not yours yet",
                f"Buy {shop.label_for(key)} in `/shop` before wearing it.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "Economy")
            return await respond(interaction, embed, ephemeral=True)

        await self._save(interaction.guild_id, interaction.user.id)

        worn = shop.worn_title(wallet)
        embed = make_embed(
            "🎖️ Title updated",
            f"You are now **{worn}**." if worn else "Title removed.",
            color=Palette.SUCCESS,
        )
        brand_footer(embed, "Shows on /balance and /rank")
        await respond(interaction, embed)

    @app_commands.command(name="grant", description="Owner: add or remove coins from a member")
    @app_commands.describe(
        member="Who to adjust",
        amount="Coins to add, or a negative number to take away",
    )
    # Minting currency devalues everything anyone earned, so it is the bot
    # owner's alone - not a server admin's - and takes the key on top.
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def grant(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        amount: app_commands.Range[int, -1_000_000, 1_000_000],
    ):
        if not await require_admin(interaction, self.bot, action="economy.grant"):
            return

        if amount == 0:
            embed = make_embed("Nothing to do", "Pick a non-zero amount.", color=Palette.WARNING)
            brand_footer(embed, "Economy")
            return await respond(interaction, embed, ephemeral=True)

        data = self.data
        wallet = get_wallet(data, interaction.guild_id, member.id)
        before = wallet["coins"]
        # Balances never go negative: taking more than someone holds empties
        # the wallet rather than putting them in debt.
        wallet["coins"] = max(0, before + amount)
        applied = wallet["coins"] - before
        await self._save(interaction.guild_id, member.id)

        record_audit(
            interaction.user.id,
            "economy.grant",
            actor_name=str(interaction.user),
            target=f"{member.id} in {interaction.guild_id}",
            detail=f"{applied:+d} coins, balance {before} -> {wallet['coins']}",
        )

        given = applied >= 0
        embed = make_embed(
            "🪙 Coins granted" if given else "🪙 Coins removed",
            f"{member.mention} {'received' if given else 'lost'} "
            f"{CURRENCY} `{humanize_number(abs(applied))}`.",
            color=Palette.SUCCESS if given else Palette.WARNING,
        )
        embed.add_field(name="Before", value=f"`{humanize_number(before)}`", inline=True)
        embed.add_field(name="After", value=f"`{humanize_number(wallet['coins'])}`", inline=True)
        if applied != amount:
            embed.add_field(
                name="Adjusted",
                value=f"-# Asked for `{amount:+d}`, but the balance stops at zero.",
                inline=False,
            )
        brand_footer(embed, "Economy")
        await respond(interaction, embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Economy(bot))
