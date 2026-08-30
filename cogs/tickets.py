"""🎫 Tickets category — private support threads opened with one button."""

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from core.database import (
    close_ticket_record,
    create_ticket_record,
    get_ticket_record,
    open_ticket_for_member,
)
from core.storage import get_guild_settings, update_guild_settings
from core.theme import Palette, brand_footer, make_embed
from core.utils import defer_interaction, respond


def role_can_manage_tickets(channel, role):
    """Private ticket threads are useful only when the chosen staff can see them."""
    if channel is None or role is None:
        return False
    permissions = channel.permissions_for(role)
    return bool(permissions.view_channel and permissions.manage_threads)


def member_can_close_ticket(member, record, *, staff_role_id=None):
    """Whether this member may close this ticket.

    The opener always can - it is their thread, and a support ticket nobody
    can end is worse than one closed early. Staff can, by the permission that
    actually governs threads rather than by a role name: Manage Threads is
    what the ticket panel already requires of the staff role, and an
    administrator holds it implicitly.

    `staff_role_id` is accepted so a guild that grants the staff role without
    Manage Threads still works; it is checked in addition, never instead.
    """
    if record is None:
        return False
    if str(getattr(member, "id", "")) == str(record.get("opener_id")):
        return True

    permissions = getattr(member, "guild_permissions", None)
    if permissions is not None and (
        getattr(permissions, "administrator", False)
        or getattr(permissions, "manage_threads", False)
        or getattr(permissions, "manage_guild", False)
    ):
        return True

    if staff_role_id:
        role_ids = {str(role.id) for role in getattr(member, "roles", ())}
        if str(staff_role_id) in role_ids:
            return True
    return False


def build_ticket_panel():
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
    return embed, view


async def publish_ticket_panel(channel, previous_message_id=None):
    """Create the panel once, then edit that message on later publishes."""
    embed, view = build_ticket_panel()
    if previous_message_id:
        try:
            message = await channel.fetch_message(int(previous_message_id))
            await message.edit(embed=embed, view=view)
            return message, False
        # Only a genuinely deleted message justifies creating a replacement.
        # Permission errors and temporary Discord failures must bubble up;
        # treating them as "not found" creates duplicate live panels.
        except (discord.NotFound, ValueError, TypeError):
            pass
    return await channel.send(embed=embed, view=view), True


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

        existing = await asyncio.to_thread(open_ticket_for_member, guild.id, interaction.user.id)
        if existing:
            thread = guild.get_thread(int(existing["thread_id"]))
            if thread is not None and not thread.archived:
                return await interaction.response.send_message(
                    f"You already have an open ticket: {thread.mention}", ephemeral=True
                )
            await asyncio.to_thread(close_ticket_record, existing["thread_id"], "stale")

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

        await asyncio.to_thread(
            create_ticket_record,
            guild.id,
            thread.id,
            parent.id,
            interaction.user.id,
            interaction.user.display_name,
        )

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

        await defer_interaction(interaction, ephemeral=True)

        # This button carries a fixed custom_id and fires on whatever thread it
        # was pressed in, so it asked no questions before archiving and locking
        # one. Membership of a private thread was the only thing standing in
        # front of it - real protection, but not a check, and not one the code
        # made. Two questions now, both cheap:
        #
        #   is this thread actually a ticket, and
        #   is the person closing it the member who opened it, or staff?
        record = await asyncio.to_thread(get_ticket_record, thread.id)
        if record is None:
            embed = make_embed(
                "Not a ticket",
                "This thread is not a NovaGuard ticket, so there is nothing to close here.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "Ticket system")
            return await respond(interaction, embed, ephemeral=True)

        settings = await asyncio.to_thread(get_guild_settings, thread.guild.id)
        if not member_can_close_ticket(
            interaction.user, record, staff_role_id=settings.get("ticket_staff_role")
        ):
            embed = make_embed(
                "That ticket is not yours to close",
                "Only the member who opened this ticket, or staff, can close it.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "Ticket system")
            return await respond(interaction, embed, ephemeral=True)

        embed = make_embed(
            "🔒 Ticket closed",
            f"Closed by {interaction.user.mention}. Thanks for reaching out!",
            color=Palette.DARK,
        )
        brand_footer(embed, "Ticket system")

        try:
            await thread.edit(archived=True, locked=True, reason=f"Ticket closed by {interaction.user}")
        except discord.HTTPException:
            error_embed = make_embed(
                "⚠️ Ticket still open",
                "Discord did not let me archive this thread. Check my **Manage Threads** permission and try again.",
                color=Palette.DANGER,
            )
            brand_footer(error_embed, "Ticket system")
            return await respond(interaction, error_embed, ephemeral=True)

        await asyncio.to_thread(close_ticket_record, thread.id, interaction.user.id)
        await respond(interaction, embed, ephemeral=True)


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
        await defer_interaction(interaction, ephemeral=True)
        if not role_can_manage_tickets(channel, staff_role):
            error_embed = make_embed(
                "🔒 Staff cannot access tickets",
                (
                    f"Give {staff_role.mention} **View Channel** and **Manage Threads** "
                    f"in {channel.mention}, then try again."
                ),
                color=Palette.DANGER,
            )
            brand_footer(error_embed, "Ticket system")
            return await respond(interaction, error_embed, ephemeral=True)

        settings = get_guild_settings(interaction.guild_id)

        try:
            message, created = await publish_ticket_panel(
                channel,
                settings.get("ticket_panel_message")
                if str(settings.get("ticket_panel_channel")) == str(channel.id)
                else None,
            )
        except discord.Forbidden:
            error_embed = make_embed("🔒 No access", f"I cannot post in {channel.mention}.", color=Palette.DANGER)
            brand_footer(error_embed)
            return await respond(interaction, error_embed, ephemeral=True)
        except discord.HTTPException:
            error_embed = make_embed(
                "⚠️ Discord rejected the panel",
                "Try again in a moment. No ticket settings were changed.",
                color=Palette.DANGER,
            )
            brand_footer(error_embed)
            return await respond(interaction, error_embed, ephemeral=True)

        update_guild_settings(
            interaction.guild_id,
            ticket_staff_role=staff_role.id,
            ticket_panel_channel=channel.id,
            ticket_panel_message=message.id,
        )

        confirm = make_embed(
            "✅ Ticket panel posted",
            f"Panel {'posted' if created else 'updated'} in {channel.mention} — staff pings go to {staff_role.mention}.",
            color=Palette.SUCCESS,
        )
        brand_footer(confirm)
        await respond(interaction, confirm, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Tickets(bot))
