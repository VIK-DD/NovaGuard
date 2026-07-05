"""🎫 Tickets category — private support threads opened with one button."""

import discord
from discord import app_commands
from discord.ext import commands

from core.storage import get_guild_settings, update_guild_settings
from core.theme import Palette, brand_footer, make_embed
from core.utils import respond


class TicketOpenButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"ticket:open",
):
    def __init__(self):
        super().__init__(
            discord.ui.Button(
                emoji="🎫",
                label="Open a ticket",
                style=discord.ButtonStyle.primary,
                custom_id="ticket:open",
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls()

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        parent = interaction.channel
        if guild is None or not isinstance(parent, discord.TextChannel):
            return

        settings = get_guild_settings(guild.id)
        staff_role_id = settings.get("ticket_staff_role")

        try:
            thread = await parent.create_thread(
                name=f"🎫-{interaction.user.name}"[:100],
                type=discord.ChannelType.private_thread,
                invitable=False,
                reason=f"Ticket opened by {interaction.user}",
            )
        except discord.Forbidden:
            return await interaction.response.send_message(
                "I need the **Create Private Threads** permission in this channel.", ephemeral=True
            )
        except discord.HTTPException:
            return await interaction.response.send_message(
                "Could not create the ticket thread — try again in a moment.", ephemeral=True
            )

        try:
            await thread.add_user(interaction.user)
        except discord.HTTPException:
            pass

        embed = make_embed(
            "🎫 Ticket opened",
            (
                f"Hey {interaction.user.mention}! Describe your issue here and the staff will be with you shortly.\n\n"
                f"Press 🔒 **Close ticket** when everything is resolved."
            ),
            color=Palette.INFO,
        )
        brand_footer(embed, "Ticket system")

        view = discord.ui.View(timeout=None)
        view.add_item(TicketCloseButton())

        content = f"<@&{staff_role_id}>" if staff_role_id else None
        try:
            await thread.send(
                content=content,
                embed=embed,
                view=view,
                allowed_mentions=discord.AllowedMentions(roles=True, users=True),
            )
        except discord.HTTPException:
            pass

        await interaction.response.send_message(
            f"✅ Your ticket is ready: {thread.mention}", ephemeral=True
        )


class TicketCloseButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"ticket:close",
):
    def __init__(self):
        super().__init__(
            discord.ui.Button(
                emoji="🔒",
                label="Close ticket",
                style=discord.ButtonStyle.danger,
                custom_id="ticket:close",
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls()

    async def callback(self, interaction: discord.Interaction):
        thread = interaction.channel
        if not isinstance(thread, discord.Thread):
            return

        embed = make_embed(
            "🔒 Ticket closed",
            f"Closed by {interaction.user.mention}. Thanks for reaching out!",
            color=Palette.DARK,
        )
        brand_footer(embed, "Ticket system")
        await interaction.response.send_message(embed=embed)

        try:
            await thread.edit(archived=True, locked=True, reason=f"Ticket closed by {interaction.user}")
        except discord.HTTPException:
            pass


class Tickets(commands.Cog):
    """One-click private support threads."""

    EMOJI = "🎫"
    COLOR = Palette.INFO
    DESCRIPTION = "Support tickets: one button opens a private thread with the staff."

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_dynamic_items(TicketOpenButton, TicketCloseButton)

    @app_commands.command(name="ticketpanel", description="Post the ticket panel in a channel")
    @app_commands.describe(
        channel="Where members will open tickets",
        staff_role="Role pinged inside every new ticket",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.bot_has_permissions(create_private_threads=True, send_messages_in_threads=True)
    @app_commands.guild_only()
    async def ticketpanel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        staff_role: discord.Role,
    ):
        update_guild_settings(interaction.guild_id, ticket_staff_role=staff_role.id)

        embed = make_embed(
            "🎫 Need help?",
            (
                "Click the button below to open a **private ticket** with the staff.\n\n"
                "• Only you and the team can see it\n"
                "• Describe your problem and we'll take it from there\n"
                "• Close it anytime with the 🔒 button"
            ),
            color=Palette.INFO,
        )
        brand_footer(embed, "Ticket system")

        view = discord.ui.View(timeout=None)
        view.add_item(TicketOpenButton())

        try:
            await channel.send(embed=embed, view=view)
        except discord.Forbidden:
            error_embed = make_embed("🔒 No access", f"I cannot post in {channel.mention}.", color=Palette.DANGER)
            brand_footer(error_embed)
            return await respond(interaction, error_embed, ephemeral=True)

        confirm = make_embed(
            "✅ Ticket panel posted",
            f"Panel live in {channel.mention} — staff pings go to {staff_role.mention}.",
            color=Palette.SUCCESS,
        )
        brand_footer(confirm)
        await respond(interaction, confirm, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Tickets(bot))
