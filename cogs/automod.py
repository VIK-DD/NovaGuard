"""🤖 AutoMod category — invite filter, anti-spam and a blocked-words list."""

import logging
import re
import time
from collections import deque
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.command_guards import ManagerGroup
from core.loop_guard import keep_running
from core.automod_settings import is_automod_exempt, resolve_automod
from core.storage import get_guild_settings, update_guild_settings
from core.theme import Palette, brand_footer, make_embed
from core.utils import respond, truncate

log = logging.getLogger(__name__)


INVITE_PATTERN = re.compile(r"(?:discord\.gg|discord(?:app)?\.com/invite)/[\w-]+", re.IGNORECASE)
SPAM_BUCKET_TTL_SECONDS = 300
# Compiled blocked-word patterns, keyed by the word list they came from.
#
# These used to be rebuilt with re.compile inside the message loop: up to a
# hundred patterns per message, per guild. The re module caches 512 compiled
# patterns, so a handful of servers with full lists evicted each other's and
# every message paid the compile again. Keyed on the tuple of words so a
# /badword change produces a new key and the old entry simply falls out.
_BADWORD_CACHE: dict[tuple[str, ...], list[re.Pattern[str]]] = {}
_BADWORD_CACHE_LIMIT = 200


def compile_badwords(words):
    """Whole-word patterns for a guild's blocked list, compiled once.

    `\\b` is an ASCII word boundary: it sits between a word character and a
    non-word one, and Python's `\\w` under re.UNICODE counts accented letters as
    word characters. That is right for "ăsta" but wrong at the edges - a
    blocked word ending in a letter followed by an accented letter is not a
    boundary at all, so `\\bcur\\b` never matched inside "curând". The lookarounds
    below ask the question the filter actually means: not preceded or followed
    by another letter or digit, in any alphabet.
    """
    key = tuple(words)
    cached = _BADWORD_CACHE.get(key)
    if cached is not None:
        return cached
    if len(_BADWORD_CACHE) >= _BADWORD_CACHE_LIMIT:
        _BADWORD_CACHE.clear()
    compiled = [
        re.compile(rf"(?<![^\W\d_]){re.escape(word)}(?![^\W\d_])", re.IGNORECASE | re.UNICODE)
        for word in words
    ]
    _BADWORD_CACHE[key] = compiled
    return compiled


def get_automod_config(guild_id):
    return resolve_automod(get_guild_settings(guild_id))


def save_automod_config(guild_id, config):
    update_guild_settings(guild_id, automod=config)


class AutoMod(commands.Cog):
    """Automatic moderation: invites, spam and blocked words."""

    EMOJI = "🤖"
    COLOR = Palette.ORANGE
    DESCRIPTION = "Auto-moderation: invite filter, anti-spam and blocked words."

    automod = ManagerGroup(
        name="automod",
        description="Auto-moderation settings",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )
    badword = ManagerGroup(
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
    @keep_running(log, "spam bucket cleanup")
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

    async def punish(self, message, title, reason, timeout_seconds=0):
        try:
            await message.delete()
        except discord.HTTPException:
            pass

        if timeout_seconds and isinstance(message.author, discord.Member):
            try:
                await message.author.timeout(
                    timedelta(seconds=timeout_seconds), reason=f"AutoMod: {reason}"
                )
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
        channel_ids = {str(message.channel.id)}
        parent_id = getattr(message.channel, "parent_id", None)
        if parent_id:
            channel_ids.add(str(parent_id))
        role_ids = (
            (role.id for role in message.author.roles)
            if isinstance(message.author, discord.Member)
            else ()
        )
        if is_automod_exempt(config, channel_ids, role_ids):
            return

        if config["invites"] and INVITE_PATTERN.search(message.content):
            return await self.punish(message, "Invite link blocked", "posting invite links is not allowed here.")

        content_lower = message.content.lower()
        for pattern in compile_badwords(config["badwords"]):
            if pattern.search(content_lower):
                return await self.punish(message, "Blocked word", "that word is on this server's blocked list.")

        if config["spam"]:
            key = (message.guild.id, message.author.id)
            message_limit = config["spam_messages"]
            bucket = self.spam_buckets.get(key)
            if bucket is None or bucket.maxlen != message_limit:
                bucket = deque(tuple(bucket or ())[-message_limit:], maxlen=message_limit)
                self.spam_buckets[key] = bucket
            bucket.append(time.monotonic())
            if (
                len(bucket) >= message_limit
                and bucket[-1] - bucket[0] <= config["spam_window_seconds"]
            ):
                bucket.clear()
                await self.punish(
                    message,
                    "Spam detected",
                    f"slow down! Muted for `{config['spam_timeout_seconds']}s`.",
                    timeout_seconds=config["spam_timeout_seconds"],
                )

    @automod.command(name="status", description="See the current AutoMod configuration")
    async def automod_status(self, interaction: discord.Interaction):
        config = get_automod_config(interaction.guild_id)
        embed = make_embed("🤖 AutoMod status", color=Palette.ORANGE)
        embed.add_field(name="🔗 Invite filter", value="`On`" if config["invites"] else "`Off`", inline=True)
        embed.add_field(name="⚡ Anti-spam", value="`On`" if config["spam"] else "`Off`", inline=True)
        embed.add_field(name="🚫 Blocked words", value=f"`{len(config['badwords'])}`", inline=True)
        embed.add_field(
            name="⚙️ Anti-spam threshold",
            value=(
                f"`{config['spam_messages']}` messages / `{config['spam_window_seconds']}s`"
                f" → `{config['spam_timeout_seconds']}s` timeout"
            ),
            inline=False,
        )
        embed.add_field(
            name="🕊️ Exemptions",
            value=(
                f"`{len(config['ignored_channels'])}` channels • "
                f"`{len(config['ignored_roles'])}` roles"
            ),
            inline=True,
        )
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
            f"`{config['spam_messages']}` messages in `{config['spam_window_seconds']}s` earns a `{config['spam_timeout_seconds']}s` timeout."
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

    # discord.py's _invoke_autocomplete never calls _check_can_run, so a
    # group's interaction_check does not run here. Without this, an
    # Integrations override that opens the command to @everyone still
    # leaks the suggestions even though the command itself is refused.
    @app_commands.checks.has_permissions(manage_guild=True)
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
