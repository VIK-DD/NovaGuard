"""🤖 AutoMod category — invite filter, anti-spam and a blocked-words list."""

import re
import time
from collections import deque
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.storage import get_guild_settings, update_guild_settings
from core.theme import Palette, brand_footer, make_embed
from core.utils import respond, truncate

INVITE_PATTERN = re.compile(r"(?:discord\.gg|discord(?:app)?\.com/invite)/[\w-]+", re.IGNORECASE)
AUTOMOD_DEFAULTS = {"invites": True, "spam": True, "badwords": []}
SPAM_MESSAGES = 6
SPAM_WINDOW_SECONDS = 6
SPAM_TIMEOUT_SECONDS = 60
SPAM_BUCKET_TTL_SECONDS = 300


def get_automod_config(guild_id):
    config = dict(AUTOMOD_DEFAULTS)
    config.update(get_guild_settings(guild_id).get("automod", {}))
    return config


def save_automod_config(guild_id, config):
    update_guild_settings(guild_id, automod=config)


class AutoMod(commands.Cog):
    """Automatic moderation: invites, spam and blocked words."""

    EMOJI = "🤖"
    COLOR = Palette.ORANGE
    DESCRIPTION = "Auto-moderation: invite filter, anti-spam and blocked words."

    automod = app_commands.Group(
        name="automod",
        description="Auto-moderation settings",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )
    badword = app_commands.Group(
        name="badword",
        description="Blocked words list",
        parent=automod,
    )

    def __init__(self, bot):
        self.bot = bot
        self.spam_buckets = {}

    async def cog_load(self):
        self.cleanup_spam_buckets.start()

    async def cog_unload(self):
        self.cleanup_spam_buckets.cancel()

    @tasks.loop(minutes=5)
    async def cleanup_spam_buckets(self):
        cutoff = time.monotonic() - SPAM_BUCKET_TTL_SECONDS
        stale_keys = [
            key
            for key, bucket in self.spam_buckets.items()
            if not bucket or bucket[-1] < cutoff
        ]
        for key in stale_keys:
            self.spam_buckets.pop(key, None)

    @cleanup_spam_buckets.before_loop
    async def before_cleanup_spam_buckets(self):
        await self.bot.wait_until_ready()

    async def punish(self, message, title, reason, timeout_member=False):
        try:
            await message.delete()
        except discord.HTTPException:
            pass

        if timeout_member and isinstance(message.author, discord.Member):
            try:
                await message.author.timeout(timedelta(seconds=SPAM_TIMEOUT_SECONDS), reason=f"AutoMod: {reason}")
            except discord.HTTPException:
                pass

        notice = make_embed(title, f"{message.author.mention} — {reason}", color=Palette.ORANGE)
        brand_footer(notice, "AutoMod")
        try:
            await message.channel.send(embed=notice, delete_after=8)
        except discord.HTTPException:
            pass

        log_embed = make_embed(
            f"🤖 AutoMod • {title}",
            (
                f"**Member:** {message.author.mention} (`{message.author.id}`)\n"
                f"**Channel:** {message.channel.mention}\n"
                f"**Reason:** {reason}\n\n>>> {truncate(message.content, 300)}"
            ),
            color=Palette.ORANGE,
        )
        brand_footer(log_embed, "AutoMod")
        self.bot.dispatch("modlog", message.guild, log_embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot or message.webhook_id:
            return
        if isinstance(message.author, discord.Member):
            perms = message.author.guild_permissions
            if perms.manage_messages or perms.administrator:
                return

        config = get_automod_config(message.guild.id)

        if config["invites"] and INVITE_PATTERN.search(message.content):
            return await self.punish(message, "Invite link blocked", "posting invite links is not allowed here.")

        content_lower = message.content.lower()
        for word in config["badwords"]:
            if re.search(rf"\b{re.escape(word)}\b", content_lower):
                return await self.punish(message, "Blocked word", "that word is on this server's blocked list.")

        if config["spam"]:
            key = (message.guild.id, message.author.id)
            bucket = self.spam_buckets.setdefault(key, deque(maxlen=SPAM_MESSAGES))
            bucket.append(time.monotonic())
            if len(bucket) >= SPAM_MESSAGES and bucket[-1] - bucket[0] <= SPAM_WINDOW_SECONDS:
                bucket.clear()
                await self.punish(
                    message,
                    "Spam detected",
                    f"slow down! Muted for `{SPAM_TIMEOUT_SECONDS}s`.",
                    timeout_member=True,
                )

    @automod.command(name="status", description="See the current AutoMod configuration")
    async def automod_status(self, interaction: discord.Interaction):
        config = get_automod_config(interaction.guild_id)
        embed = make_embed("🤖 AutoMod status", color=Palette.ORANGE)
        embed.add_field(name="🔗 Invite filter", value="`On`" if config["invites"] else "`Off`", inline=True)
        embed.add_field(name="⚡ Anti-spam", value="`On`" if config["spam"] else "`Off`", inline=True)
        embed.add_field(name="🚫 Blocked words", value=f"`{len(config['badwords'])}`", inline=True)
        embed.add_field(
            name="Notes",
            value="Members with **Manage Messages** or **Administrator** are exempt.",
            inline=False,
        )
        brand_footer(embed, "AutoMod")
        await respond(interaction, embed)

    @automod.command(name="invites", description="Toggle the invite-link filter")
    @app_commands.describe(enabled="Should invite links be blocked?")
    async def automod_invites(self, interaction: discord.Interaction, enabled: bool):
        config = get_automod_config(interaction.guild_id)
        config["invites"] = enabled
        save_automod_config(interaction.guild_id, config)
        embed = make_embed(
            "🔗 Invite filter " + ("enabled" if enabled else "disabled"),
            "Invite links will be deleted automatically." if enabled else "Invite links are allowed again.",
            color=Palette.SUCCESS if enabled else Palette.WARNING,
        )
        brand_footer(embed, "AutoMod")
        await respond(interaction, embed)

    @automod.command(name="spam", description="Toggle the anti-spam filter")
    @app_commands.describe(enabled="Should spam be punished?")
    async def automod_spam(self, interaction: discord.Interaction, enabled: bool):
        config = get_automod_config(interaction.guild_id)
        config["spam"] = enabled
        save_automod_config(interaction.guild_id, config)
        embed = make_embed(
            "⚡ Anti-spam " + ("enabled" if enabled else "disabled"),
            f"More than `{SPAM_MESSAGES}` messages in `{SPAM_WINDOW_SECONDS}s` earns a `{SPAM_TIMEOUT_SECONDS}s` timeout."
            if enabled
            else "Spam detection is off.",
            color=Palette.SUCCESS if enabled else Palette.WARNING,
        )
        brand_footer(embed, "AutoMod")
        await respond(interaction, embed)

    @badword.command(name="add", description="Add a word to the blocked list")
    @app_commands.describe(word="The word to block")
    async def badword_add(self, interaction: discord.Interaction, word: str):
        word = word.strip().lower()
        config = get_automod_config(interaction.guild_id)
        if word in config["badwords"]:
            embed = make_embed("🤷 Already blocked", f"`{word}` is already on the list.", color=Palette.WARNING)
        else:
            config["badwords"].append(word)
            save_automod_config(interaction.guild_id, config)
            embed = make_embed("🚫 Word blocked", f"Messages containing `{word}` will be deleted.", color=Palette.SUCCESS)
        brand_footer(embed, "AutoMod")
        await respond(interaction, embed, ephemeral=True)

    async def badword_autocomplete(self, interaction: discord.Interaction, current: str):
        config = get_automod_config(interaction.guild_id)
        current = current.lower()
        return [
            app_commands.Choice(name=word, value=word)
            for word in config["badwords"]
            if current in word
        ][:25]

    @badword.command(name="remove", description="Remove a word from the blocked list")
    @app_commands.describe(word="Pick the word to unblock")
    @app_commands.autocomplete(word=badword_autocomplete)
    async def badword_remove(self, interaction: discord.Interaction, word: str):
        word = word.strip().lower()
        config = get_automod_config(interaction.guild_id)
        if word not in config["badwords"]:
            embed = make_embed("🤷 Not on the list", f"`{word}` is not blocked.", color=Palette.WARNING)
        else:
            config["badwords"].remove(word)
            save_automod_config(interaction.guild_id, config)
            embed = make_embed("✅ Word unblocked", f"`{word}` is allowed again.", color=Palette.SUCCESS)
        brand_footer(embed, "AutoMod")
        await respond(interaction, embed, ephemeral=True)

    @badword.command(name="list", description="See the blocked words")
    async def badword_list(self, interaction: discord.Interaction):
        config = get_automod_config(interaction.guild_id)
        if not config["badwords"]:
            embed = make_embed("📭 List is empty", "No blocked words yet. Add one with `/automod badword add`.", color=Palette.INFO)
        else:
            words = ", ".join(f"`{word}`" for word in config["badwords"][:50])
            embed = make_embed(f"🚫 Blocked words ({len(config['badwords'])})", words, color=Palette.ORANGE)
        brand_footer(embed, "AutoMod")
        await respond(interaction, embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(AutoMod(bot))
