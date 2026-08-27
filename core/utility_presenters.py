"""Discord cards for read-only utility commands."""

import discord

from .theme import Palette, brand_footer, make_embed


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


def build_userinfo_embed(target):
    badges = [
        BADGE_LABELS[name]
        for name, value in target.public_flags
        if value and name in BADGE_LABELS
    ]
    roles = [role.mention for role in reversed(target.roles[1:])][:5]
    color = target.color.value if target.color.value else Palette.PRIMARY

    embed = make_embed(
        f"👤 {target.display_name}",
        f"{target.mention} • `{target.id}`",
        color=color,
    )
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
    return embed


def build_serverinfo_embed(guild):
    embed = make_embed(
        f"🏰 {guild.name}",
        guild.description or "A great place to be.",
        color=Palette.PURPLE,
    )
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
        value=f"Text: `{len(guild.text_channels)}`\nVoice: `{len(guild.voice_channels)}`",
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
    return embed


def build_avatar_embed(target):
    asset = target.display_avatar.with_size(1024)
    embed = make_embed(f"🖼️ {target.display_name}'s avatar", color=Palette.FUN)
    embed.set_image(url=asset.url)
    brand_footer(embed, "Avatar viewer")
    return embed, asset.url


def build_roleinfo_embed(role):
    color = role.color.value if role.color.value else Palette.PRIMARY
    embed = make_embed(
        f"🏷️ {role.name}",
        f"{role.mention} • `{role.id}`",
        color=color,
    )
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
    return embed
