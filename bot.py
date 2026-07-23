"""Developed by VIK & CloudMediaSRL — modern, slash-command Discord bot.

Entry point: loads the category cogs and keeps startup responsive even when
Discord's command-sync API is slow.
"""

import asyncio
import logging
import os
import socket
import sys
import time
from datetime import UTC, datetime

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from core.config import BOT_CODENAME, BOT_VERSION
from core.error_digest import send_error_digest
from core.github_api import github_api
from core.maintenance import load_maintenance_state, user_can_bypass_maintenance
from core.theme import Palette, brand_footer, make_embed

COGS = (
    "setup",
    "system",
    "developer",
    "utility",
    "fun",
    "moderation",
    "levels",
    "welcome",
    "logs",
    "roles",
    "giveaways",
    "tickets",
    "automod",
    "economy",
    "ai",
)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)-8s] %(name)s: %(message)s",
    stream=sys.stdout,
)

NETWORK_CHECK_PORT = 443
NETWORK_CHECK_SECONDS = 10
NETWORK_CHECK_HOSTS = ("discord.com", "gateway.discord.gg")
RECONNECT_RETRY_SECONDS = 15


class DiscordNoiseFilter(logging.Filter):
    """Hide noisy discord.py reconnect/voice logs we already handle ourselves."""

    SUPPRESSED_SNIPPETS = (
        "PyNaCl is not installed, voice will NOT be supported",
        "davey is not installed, voice will NOT be supported",
        "Attempting a reconnect in ",
    )

    def filter(self, record):
        message = record.getMessage()
        return not any(snippet in message for snippet in self.SUPPRESSED_SNIPPETS)


discord_client_logger = logging.getLogger("discord.client")
discord_client_logger.addFilter(DiscordNoiseFilter())


class NovaCommandTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction, /):
        command = interaction.command
        if command is None:
            return True

        qualified_name = getattr(command, "qualified_name", command.name)
        if qualified_name == "maintenance":
            return True

        maintenance_state = load_maintenance_state()
        if not maintenance_state.get("enabled"):
            return True

        if await user_can_bypass_maintenance(interaction.client, interaction.user):
            return True

        interaction.extras["maintenance_blocked"] = True
        embed = make_embed(
            "🛠️ Maintenance Mode",
            "NovaGuard is temporarily under maintenance.\nPlease try again in a little while.",
            color=Palette.WARNING,
        )
        embed.add_field(
            name="Current Status",
            value=f"`{maintenance_state.get('message', 'Working Mode Active')}`",
            inline=False,
        )
        embed.add_field(
            name="Access",
            value="Commands are temporarily limited while updates or fixes are being applied.",
            inline=False,
        )
        brand_footer(embed, "Maintenance notice")

        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.HTTPException:
            pass
        return False


class DevBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True  # required for welcome/goodbye + join/leave logs
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
            tree_cls=NovaCommandTree,
            # Safe default: never let echoed user content trigger @everyone/@here
            # or role pings. Specific user pings (welcome, replies) stay allowed;
            # commands that must ping a role (e.g. tickets) opt in per-message.
            allowed_mentions=discord.AllowedMentions(
                everyone=False, roles=False, users=True, replied_user=True
            ),
        )
        self.launched_at = datetime.now(UTC)
        self.startup_update_announced = False
        self.command_sync_task = None

    async def setup_hook(self):
        for name in COGS:
            await self.load_extension(f"cogs.{name}")

        from core.webserver import WebServer

        self.webserver = WebServer(self)
        await self.webserver.start()

        self.command_sync_task = asyncio.create_task(self.sync_commands_later())
        print(f"v{BOT_VERSION} \"{BOT_CODENAME}\" • loaded {len(COGS)} cogs • command sync scheduled")

    async def sync_commands_later(self):
        await self.wait_until_ready()

        # Sync GLOBALLY so every server the bot is in receives every command.
        # Global commands can take up to ~1h to propagate (usually minutes).
        # We deliberately do NOT also guild-sync: mixing global commands with
        # guild-scoped copies makes Discord show every command twice in that
        # guild. Use /resync (owner only) to force a re-push without a restart.
        scope = "global (up to ~1h to appear on all servers)"
        try:
            synced = await asyncio.wait_for(self.tree.sync(), timeout=30)
        except asyncio.TimeoutError:
            print(f"Command sync skipped: Discord did not respond within 30s • {scope}")
            return
        except discord.HTTPException as error:
            print(f"Command sync skipped: Discord API issue ({error}) • {scope}")
            return

        print(f"v{BOT_VERSION} \"{BOT_CODENAME}\" • synced {len(synced)} slash commands • {scope}")

    async def close(self):
        if self.command_sync_task and not self.command_sync_task.done():
            self.command_sync_task.cancel()
        webserver = getattr(self, "webserver", None)
        if webserver:
            await webserver.stop()
        await github_api.close()
        await super().close()

def create_bot():
    bot = DevBot()

    @bot.tree.error
    async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
        if interaction.extras.get("maintenance_blocked"):
            return

        original = getattr(error, "original", error)
        if isinstance(original, discord.NotFound) and getattr(original, "code", None) == 10062:
            print("Interaction expired before the bot could respond. This is usually network/Discord latency.")
            return

        if isinstance(error, app_commands.CommandOnCooldown):
            embed = make_embed("🧊 Slow down", f"Try again in `{error.retry_after:.1f}s`.", color=Palette.WARNING)
        elif isinstance(error, app_commands.MissingPermissions):
            missing = ", ".join(f"`{perm}`" for perm in error.missing_permissions)
            embed = make_embed("🔒 Missing permissions", f"You need {missing} to use this.", color=Palette.DANGER)
        elif isinstance(error, app_commands.BotMissingPermissions):
            missing = ", ".join(f"`{perm}`" for perm in error.missing_permissions)
            embed = make_embed("🤖 I need more power", f"Grant me {missing} first.", color=Palette.DANGER)
        elif isinstance(error, app_commands.CheckFailure):
            embed = make_embed("🔒 Not allowed", "You cannot use this command here.", color=Palette.DANGER)
        else:
            print(f"Command error: {original!r}")
            current_bot = interaction.client
            current_bot.loop.create_task(
                send_error_digest(current_bot, "Slash Command Error", original, interaction=interaction)
            )
            embed = make_embed(
                "💥 Something hiccuped",
                "An unexpected error occurred. The team has been notified — please try again in a moment.",
                color=Palette.DANGER,
            )
        brand_footer(embed)

        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.HTTPException:
            pass

    @bot.event
    async def on_error(event_method, *args, **kwargs):
        error = sys.exc_info()[1]
        if error is None:
            return
        print(f"Unhandled event error in {event_method}: {error!r}")
        await send_error_digest(bot, "Unhandled Event Error", error, context=f"Event: `{event_method}`")

    return bot


def is_transient_startup_error(error):
    if isinstance(
        error,
        (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            OSError,
            discord.ConnectionClosed,
            discord.GatewayNotFound,
        ),
    ):
        return True
    return isinstance(error, AttributeError) and "'NoneType' object has no attribute 'sequence'" in str(error)


def main():
    token = os.getenv("TOKEN")
    if not token:
        raise ValueError("TOKEN nu este setat.")
    attempt = 1
    while True:
        wait_for_startup_network()
        bot = create_bot()
        try:
            bot.run(token, log_handler=None)
            return
        except discord.PrivilegedIntentsRequired:
            raise SystemExit(
                "\n[!] SERVER MEMBERS INTENT is not enabled.\n"
                "    Fix: https://discord.com/developers/applications -> your app -> Bot ->\n"
                "    Privileged Gateway Intents -> enable 'SERVER MEMBERS INTENT', then restart.\n"
            )
        except KeyboardInterrupt:
            return
        except Exception as error:
            if not is_transient_startup_error(error):
                raise
            print(
                f"Bot connection failed temporarily ({error!r}). "
                f"Retrying in {RECONNECT_RETRY_SECONDS}s... attempt {attempt}"
            )
            attempt += 1
            time.sleep(RECONNECT_RETRY_SECONDS)


def wait_for_startup_network():
    """Keep pm2 process alive while the Pi/network/DNS warms up."""
    attempt = 1
    while True:
        try:
            for host in NETWORK_CHECK_HOSTS:
                with socket.create_connection((host, NETWORK_CHECK_PORT), timeout=5):
                    pass
            if attempt > 1:
                print("Startup network check passed. Connecting to Discord...")
            return
        except OSError as error:
            print(
                f"Startup network check failed ({error}). "
                f"Retrying in {NETWORK_CHECK_SECONDS}s... attempt {attempt}"
            )
            attempt += 1
            time.sleep(NETWORK_CHECK_SECONDS)


if __name__ == "__main__":
    main()
