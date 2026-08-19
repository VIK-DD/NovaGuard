"""👋 The public introduction NovaGuard posts when it joins a server.

This replaces what used to happen on arrival: the /setup panel, posted in the
open. That panel is an administrator's control surface, and posting it
publicly showed everyone a set of menus that refuse them the moment they are
touched. The people in the channel wanted to know what had just joined, which
is a different message — so they get that one, and the administrator reaches
setup through a button that answers only them.

The card is static. It says nothing that changes hour to hour, so there is no
loop here to fall over quietly and no state to keep in step.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.info_panel import (
    COMMANDS_URL,
    PRIVACY_URL,
    WEBSITE_URL,
    build_info_embed,
)
from core.theme import Palette, brand_footer, make_embed
from core.utils import defer_interaction, respond

log = logging.getLogger(__name__)


def can_post_in(channel, me):
    perms = channel.permissions_for(me)
    return perms.send_messages and perms.embed_links


def first_writable_channel(guild):
    """Where to introduce ourselves when nobody has told us.

    Preferring the server's system channel matters: that is the one an owner
    already nominated for arrivals, so it is far likelier to be the right room
    than whichever channel happens to sort first.
    """
    system = guild.system_channel
    if system is not None and can_post_in(system, guild.me):
        return system
    for channel in guild.text_channels:
        if can_post_in(channel, guild.me):
            return channel
    return None


class InfoPanelView(discord.ui.View):
    """Buttons that answer privately, so the channel stays as it was.

    timeout=None because the message is meant to stay useful for as long as
    the bot is on the server. Nothing here holds per-interaction state, so
    surviving a restart costs nothing — the view is re-registered on load.
    """

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Website", url=WEBSITE_URL, row=1))
        self.add_item(discord.ui.Button(label="All commands", url=COMMANDS_URL, row=1))
        self.add_item(discord.ui.Button(label="Privacy", url=PRIVACY_URL, row=1))

    @discord.ui.button(
        label="Open setup",
        emoji="🚀",
        style=discord.ButtonStyle.primary,
        custom_id="novaguard:infopanel:setup",
        row=0,
    )
    async def open_setup(self, interaction, button):
        # Imported here rather than at module scope: cogs.setup pulls in the
        # whole backup stack, and importing that at load time would tie this
        # cog's startup to a subsystem it has no other business with.
        from cogs.setup import SetupView, build_setup_embed

        if not interaction.user.guild_permissions.manage_guild:
            embed = make_embed(
                "🔒 That one is for server managers",
                "You need **Manage Server** to change NovaGuard's settings.\n\n"
                "Everything else on this card is yours to use — start with `/help`.",
                color=Palette.INFO,
            )
            brand_footer(embed, "Welcome")
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        await interaction.response.send_message(
            embed=build_setup_embed(interaction.guild),
            view=SetupView(),
            ephemeral=True,
        )


class InfoPanel(commands.Cog):
    """Introduces NovaGuard to a server, once, in public."""

    EMOJI = "👋"
    COLOR = Palette.PRIMARY
    DESCRIPTION = "The public introduction card posted when NovaGuard joins."

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        # Without this the Open setup button stops answering after a restart:
        # Discord keeps the message, but the process has forgotten how to
        # handle its custom_id.
        self.bot.add_view(InfoPanelView())

    async def post_to(self, channel):
        return await channel.send(embed=build_info_embed(channel.guild), view=InfoPanelView())

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        channel = first_writable_channel(guild)
        if channel is None:
            log.info("Joined %s with nowhere to introduce myself", guild.id)
            return
        try:
            await self.post_to(channel)
        except discord.HTTPException:
            log.warning("Could not post the welcome card in %s", guild.id, exc_info=True)

    @app_commands.command(
        name="infopanel",
        description="Post the NovaGuard introduction card in a channel",
    )
    @app_commands.describe(channel="Where to post it; defaults to here")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def infopanel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ):
        await defer_interaction(interaction, ephemeral=True)
        target = channel or interaction.guild.get_channel(interaction.channel_id)

        # get_channel returns guild channels only, so a thread or a DM cannot
        # be handed a permanent panel the bot will not find its way back to.
        if target is None:
            embed = make_embed(
                "📍 Not a server channel",
                "Run this in a normal text channel, or name one with `channel:`.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "Welcome")
            return await respond(interaction, embed, ephemeral=True)

        try:
            message = await self.post_to(target)
        except discord.Forbidden:
            embed = make_embed(
                "🔒 I cannot post there",
                f"Grant me **Send Messages** and **Embed Links** in {target.mention}.",
                color=Palette.DANGER,
            )
            brand_footer(embed, "Welcome")
            return await respond(interaction, embed, ephemeral=True)

        confirm = make_embed(
            "👋 Introduction posted",
            f"Published in {target.mention}.",
            color=Palette.SUCCESS,
        )
        confirm.add_field(name="Message", value=message.jump_url, inline=False)
        brand_footer(confirm, "Welcome")
        await respond(interaction, confirm, ephemeral=True)


async def setup(bot):
    await bot.add_cog(InfoPanel(bot))
