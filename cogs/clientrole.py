"""🤝 A role for people who run NovaGuard on a server of their own.

Granted when someone holding Manage Server on another guild NovaGuard is in
joins this one, and taken back when that stops being true. Both moves are
explained to the member in a DM, because a role appearing or vanishing with
no reason given is unsettling — and because the grant is an inference about
where else they are, which they deserve to be told about rather than notice.

Nothing happens at all until an operator names the role.
"""

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.client_role import ADMIN, NOT_ADMIN, client_status
from core.loop_guard import keep_running
from core.storage import get_guild_settings, update_guild_settings
from core.theme import Palette, brand_footer, make_embed
from core.utils import respond

log = logging.getLogger(__name__)

CLIENT_ROLE_KEY = "client_role"
SWEEP_HOURS = 24


def configured_role(guild):
    """The role this guild uses, if it is set and the bot can actually assign it."""
    role_id = get_guild_settings(guild.id).get(CLIENT_ROLE_KEY)
    if not role_id:
        return None
    try:
        role = guild.get_role(int(role_id))
    except (TypeError, ValueError):
        return None
    if role is None or role >= guild.me.top_role:
        return None
    return role


class ClientRole(commands.Cog):
    """Keeps the NovaGuard client role matching who actually runs NovaGuard."""

    EMOJI = "🤝"
    COLOR = Palette.INFO
    DESCRIPTION = "Recognises members who run NovaGuard on their own server."

    clientrole = app_commands.Group(
        name="clientrole",
        description="Recognise members who run NovaGuard elsewhere",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.sweep_loop.start()

    async def cog_unload(self):
        self.sweep_loop.cancel()

    # ── telling the member ────────────────────────────────────────────

    async def _notify(self, member, embed):
        """DMs are a courtesy, not a requirement.

        Plenty of people keep them closed, and a role explanation is not worth
        posting in public after they chose not to receive it.
        """
        try:
            await member.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

    def _granted_embed(self, guild, role):
        embed = make_embed(
            "🤝 You have been recognised as a NovaGuard client",
            f"Welcome to **{guild.name}**. You have been given the **{role.name}** role, "
            "because you manage a server where NovaGuard is set up.\n\n"
            "NovaGuard noticed this from the servers it is already on — it did not look "
            "anywhere else, and it shares nothing about you with anyone.",
            color=Palette.SUCCESS,
        )
        brand_footer(embed, "Client recognition")
        return embed

    def _revoked_embed(self, guild, role):
        embed = make_embed(
            "🤝 Your client role has been removed",
            f"The **{role.name}** role in **{guild.name}** has been removed, because "
            "NovaGuard can no longer see a server you manage where it is set up.\n\n"
            "This is automatic and says nothing about you. If you still run NovaGuard "
            "somewhere, the role returns on its own within a day.",
            color=Palette.INFO,
        )
        brand_footer(embed, "Client recognition")
        return embed

    # ── the two moves ─────────────────────────────────────────────────

    async def grant(self, member, role):
        if role in member.roles:
            return False
        try:
            await member.add_roles(role, reason="Administers another server running NovaGuard")
        except discord.HTTPException:
            log.warning("Could not grant the client role in %s", member.guild.id, exc_info=True)
            return False
        await self._notify(member, self._granted_embed(member.guild, role))
        return True

    async def revoke(self, member, role):
        if role not in member.roles:
            return False
        try:
            await member.remove_roles(
                role, reason="No longer administers a server running NovaGuard"
            )
        except discord.HTTPException:
            log.warning("Could not remove the client role in %s", member.guild.id, exc_info=True)
            return False
        await self._notify(member, self._revoked_embed(member.guild, role))
        return True

    async def reconcile(self, member, role):
        """Bring one member's role in line with what can actually be seen.

        UNKNOWN deliberately does nothing: it means the member cache could not
        answer, and taking a role away on missing information is how a real
        client loses it after a reconnect.
        """
        status = client_status(self.bot.guilds, member.id, home_guild_id=member.guild.id)
        if status == ADMIN:
            return await self.grant(member, role)
        if status == NOT_ADMIN:
            return await self.revoke(member, role)
        return False

    # ── when it runs ──────────────────────────────────────────────────

    async def recheck_everywhere(self, user_id):
        """Re-read one person wherever this feature is switched on.

        Called when something changed on another server. Waiting for the daily
        sweep left someone who had just lost their admin rights wearing the
        role for up to a day, which is the opposite of what the role claims.
        """
        for guild in list(self.bot.guilds):
            role = configured_role(guild)
            if role is None:
                continue
            member = guild.get_member(user_id)
            if member is None or getattr(member, "bot", False):
                continue
            await self.reconcile(member, role)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.bot:
            return
        role = configured_role(member.guild)
        if role is None:
            return
        await self.reconcile(member, role)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        # They left, or were removed from, a server NovaGuard is on. That may
        # have been the only one making them a client.
        if getattr(member, "bot", False):
            return
        await self.recheck_everywhere(member.id)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        # Nicknames and ordinary roles change constantly. Only a change to the
        # permission this feature actually reads is worth a pass.
        if getattr(after, "bot", False):
            return
        if before.guild_permissions.manage_guild == after.guild_permissions.manage_guild:
            return
        await self.recheck_everywhere(after.id)

    @tasks.loop(hours=SWEEP_HOURS)
    @keep_running(log, "client role sweep")
    async def sweep_loop(self):
        for guild in list(self.bot.guilds):
            role = configured_role(guild)
            if role is None:
                continue
            # Everyone holding it, plus everyone who might have earned it since.
            for member in list(guild.members):
                if member.bot:
                    continue
                await self.reconcile(member, role)
                await asyncio.sleep(0)

    @sweep_loop.before_loop
    async def before_sweep_loop(self):
        await self.bot.wait_until_ready()

    # ── configuration ─────────────────────────────────────────────────

    @clientrole.command(name="set", description="Choose the role given to NovaGuard clients")
    @app_commands.describe(role="The role to grant")
    async def clientrole_set(self, interaction: discord.Interaction, role: discord.Role):
        if role >= interaction.guild.me.top_role:
            embed = make_embed(
                "🔒 That role is above mine",
                f"Move **{role.name}** below my highest role so I can assign it.",
                color=Palette.DANGER,
            )
            brand_footer(embed, "Client recognition")
            return await respond(interaction, embed, ephemeral=True)

        update_guild_settings(interaction.guild_id, **{CLIENT_ROLE_KEY: str(role.id)})
        embed = make_embed(
            "🤝 Client role set",
            f"Members who manage another server running NovaGuard will receive {role.mention}.\n\n"
            "They are told why in a DM, and the role is removed again if that stops being true. "
            "Everyone already here is checked within a day.",
            color=Palette.SUCCESS,
        )
        brand_footer(embed, "Client recognition")
        await respond(interaction, embed, ephemeral=True)

    @clientrole.command(name="off", description="Stop granting the NovaGuard client role")
    async def clientrole_off(self, interaction: discord.Interaction):
        update_guild_settings(interaction.guild_id, **{CLIENT_ROLE_KEY: None})
        embed = make_embed(
            "🤝 Client role turned off",
            "No new roles will be granted. Roles already given stay where they are — "
            "remove them yourself if you want them gone.",
            color=Palette.INFO,
        )
        brand_footer(embed, "Client recognition")
        await respond(interaction, embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(ClientRole(bot))
