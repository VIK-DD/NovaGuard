"""VIK-DD Dev System — modern, slash-command Discord bot.

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

import discord
from discord import app_commands
from discord.ext import commands

from core.config import BOT_CODENAME, BOT_VERSION, GUILD_ID
from core.error_digest import send_error_digest
from core.github_api import github_api
from core.theme import Palette, brand_footer, make_embed
from core.utils import truncate

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


class DevBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True  # required for welcome/goodbye + join/leave logs
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
        )
        self.launched_at = datetime.now(UTC)
        self.startup_update_announced = False
        self.command_sync_task = None

    async def setup_hook(self):
        for name in COGS:
            await self.load_extension(f"cogs.{name}")

        self.command_sync_task = asyncio.create_task(self.sync_commands_later())
        print(f"v{BOT_VERSION} \"{BOT_CODENAME}\" • loaded {len(COGS)} cogs • command sync scheduled")

    async def sync_commands_later(self):
        await self.wait_until_ready()

        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            scope = f"guild {GUILD_ID} (instant)"
        else:
            guild = None
            scope = "global (may take up to 1 hour to appear)"

        try:
            synced = await asyncio.wait_for(self.tree.sync(guild=guild), timeout=30)
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
        await github_api.close()
        await super().close()


bot = DevBot()


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
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
        bot.loop.create_task(send_error_digest(bot, "Slash Command Error", original, interaction=interaction))
        embed = make_embed("💥 Something hiccuped", f"`{truncate(str(original), 180)}`", color=Palette.DANGER)
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


def main():
    token = os.getenv("TOKEN")
    if not token:
        raise ValueError("TOKEN nu este setat.")
    wait_for_startup_network()
    try:
        bot.run(token, log_handler=None)
    except discord.PrivilegedIntentsRequired:
        raise SystemExit(
            "\n[!] SERVER MEMBERS INTENT is not enabled.\n"
            "    Fix: https://discord.com/developers/applications -> your app -> Bot ->\n"
            "    Privileged Gateway Intents -> enable 'SERVER MEMBERS INTENT', then restart.\n"
        )


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
