"""Discord presentation helpers for read-only economy commands."""

from __future__ import annotations

import discord

from . import shop
from .economy_helpers import CURRENCY
from .theme import Palette, brand_footer, make_embed
from .utils import humanize_number


def _active_effect_lines(wallet):
    return [
        (
            f"{shop.label_for(record.get('item'))} —"
            f" ends {discord.utils.format_dt(shop.parse_time(record['expires_at']), 'R')}"
        )
        for record in shop.active_effects(wallet).values()
    ]


def build_balance_embed(target, wallet):
    title = shop.worn_title(wallet)
    embed = make_embed(
        f"💰 {target.display_name}'s wallet",
        f"# {CURRENCY} {humanize_number(wallet['coins'])}",
        color=Palette.GOLD,
    )
    if title:
        embed.set_author(
            name=f"{title} · {target.display_name}",
            icon_url=target.display_avatar.url,
        )
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(
        name="🔥 Daily streak",
        value=f"`{wallet.get('daily_streak', 0)} day(s)`",
        inline=True,
    )

    shields = shop.shields(wallet)
    if shields:
        embed.add_field(name="🛡️ Streak shields", value=f"`{shields}`", inline=True)

    trophies = [key for key in wallet.get("trophies", []) if shop.item(key)]
    if trophies:
        shelf = " ".join(shop.item(key)["icon"] for key in trophies)
        embed.add_field(name="🏆 Trophy shelf", value=shelf, inline=True)

    effects = _active_effect_lines(wallet)
    if effects:
        embed.add_field(name="✨ Active", value="\n".join(effects), inline=False)

    brand_footer(embed, "Economy · /shop to spend, /inventory for yours")
    return embed


def build_richest_embed(guild, wallets):
    if not wallets:
        embed = make_embed(
            "🌱 Nothing yet",
            "Nobody has earned coins. Try `/daily`!",
            color=Palette.INFO,
        )
        brand_footer(embed)
        return embed

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = [
        f"{medals.get(index, f'`#{index}`')} <@{user_id}> — "
        f"{CURRENCY} `{humanize_number(coins)}`"
        for index, (user_id, coins) in enumerate(wallets, 1)
    ]
    embed = make_embed(f"💰 Richest • {guild.name}", "\n".join(lines), color=Palette.GOLD)
    brand_footer(embed, "Economy leaderboard")
    return embed


def build_shop_embed(wallet):
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
                f"{shop.label_for(entry['key'])} — {CURRENCY} "
                f"`{humanize_number(entry['price'])}`{owned}{note}"
            )
        embed.add_field(name=heading, value="\n".join(lines), inline=False)

    brand_footer(embed, "Crates open with /crate · titles equip with /title")
    return embed


def build_inventory_embed(target, wallet):
    worn = shop.worn_title(wallet)
    embed = make_embed(
        f"🎒 {target.display_name}'s inventory",
        f"Wearing **{worn}**." if worn else "No title worn.",
        color=Palette.PURPLE,
    )

    embed.add_field(
        name="✨ Running now",
        value="\n".join(_active_effect_lines(wallet)) or "-# Nothing active.",
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
    return embed
