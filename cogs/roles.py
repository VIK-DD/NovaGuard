"""🎭 Roles category — self-service role panels with persistent buttons."""

import asyncio
import time

import discord
from discord import app_commands
from discord.ext import commands

from core.database import save_role_panel_record
from core.role_safety import bot_cannot_manage_reason, role_assignment_error
from core.theme import Palette, brand_footer, make_embed
from core.utils import respond


def validate_role_panel_input(title, description, role_ids):
    errors = []
    clean_title = " ".join(str(title or "").split())
    clean_description = " ".join(str(description or "").split())
    clean_role_ids = []
    for role_id in role_ids if isinstance(role_ids, (list, tuple)) else ():
        value = str(role_id)
        if value not in clean_role_ids:
            clean_role_ids.append(value)

    if not clean_title or len(clean_title) > 80:
        errors.append("title must contain 1–80 characters")
    if not clean_description or len(clean_description) > 1000:
        errors.append("description must contain 1–1000 characters")
    if not 1 <= len(clean_role_ids) <= 5:
        errors.append("choose between 1 and 5 unique roles")
    if any(not role_id.isdigit() for role_id in clean_role_ids):
        errors.append("every role id must be a Discord snowflake")
    return clean_title, clean_description, clean_role_ids, errors


def build_role_panel(title, description, roles):
    view = discord.ui.View(timeout=None)
    for role in roles:
        view.add_item(RoleButton(role.id, label=role.name))

    embed = make_embed(
        f"🎭 {title}",
        f"{description}\n\n" + "\n".join(f"• {role.mention}" for role in roles),
        color=Palette.PURPLE,
    )
    brand_footer(embed, "Click a button to toggle a role")
    return embed, view


async def publish_role_panel(channel, title, description, roles, previous_message_id=None):
    """Publish a new role panel, or update its tracked Discord message in place."""
    embed, view = build_role_panel(title, description, roles)
    if previous_message_id:
        try:
            message = await channel.fetch_message(int(previous_message_id))
            await message.edit(embed=embed, view=view)
            return message, False
        except (discord.NotFound, ValueError, TypeError):
            pass
    return await channel.send(embed=embed, view=view), True


class RoleButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"rolebtn:(?P<role_id>\d+)",
):
    """A persistent role toggle button — survives bot restarts via its custom_id."""

    _cooldown: dict[int, float] = {}  # user_id -> last click, anti-spam
    _COOLDOWN = 2.0

    def __init__(self, role_id: int, label: str | None = None):
        super().__init__(
            discord.ui.Button(
                label=label or "Role",
                style=discord.ButtonStyle.secondary,
                custom_id=f"rolebtn:{role_id}",
            )
        )
        self.role_id = role_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["role_id"]))

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            return

        now = time.monotonic()
        if now - self._cooldown.get(interaction.user.id, 0.0) < self._COOLDOWN:
            return await interaction.response.send_message("⏳ Slow down a moment.", ephemeral=True)
        self._cooldown[interaction.user.id] = now
        if len(self._cooldown) > 4000:
            for uid in [u for u, t in self._cooldown.items() if now - t > 60]:
                self._cooldown.pop(uid, None)

        role = guild.get_role(self.role_id)
        if role is None:
            return await interaction.response.send_message(
                "That role no longer exists — ask an admin to rebuild the panel.", ephemeral=True
            )

        member = interaction.user
        already_held = role in getattr(member, "roles", ())

        # Nothing can be done with a role NovaGuard cannot manage - Discord
        # refuses the removal as readily as the grant - so say which it is
        # rather than letting the call fail into a generic error.
        blocked = bot_cannot_manage_reason(role, guild)
        if blocked:
            return await interaction.response.send_message(
                f"I cannot manage that role anymore ({blocked}) — ask an admin to rebuild the panel.",
                ephemeral=True,
            )

        # Re-checked here, not only where the panel was published. A panel
        # outlives the state it was built from: a role that was harmless in
        # March can be granted Manage Roles in April, and this button would
        # otherwise keep handing it out. No actor is passed - the person
        # pressing the button is not the one who configured the panel, and
        # holding no roles must not disqualify them from an ordinary one.
        #
        # Removal stays allowed. Refusing to take a now-privileged role back
        # off someone would strand them holding exactly the thing the check
        # exists to keep them from having.
        refusal = role_assignment_error(role, guild)
        if refusal and not already_held:
            embed = make_embed(
                "🔒 That role is not self-assignable",
                f"NovaGuard will not hand out {role.mention} because {refusal}.\n\n"
                "Ask a server manager to rebuild this panel.",
                color=Palette.DANGER,
            )
            brand_footer(embed, "Role panel")
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        try:
            if already_held:
                await member.remove_roles(role, reason="Role panel: self-removed")
                embed = make_embed("➖ Role removed", f"You no longer have {role.mention}.", color=Palette.ORANGE)
            else:
                await member.add_roles(role, reason="Role panel: self-assigned")
                embed = make_embed("➕ Role added", f"You now have {role.mention}!", color=Palette.SUCCESS)
        except discord.HTTPException:
            embed = make_embed("💥 Could not update roles", "Check my permissions and try again.", color=Palette.DANGER)

        brand_footer(embed, "Role panel")
        await interaction.response.send_message(embed=embed, ephemeral=True)


class Roles(commands.Cog):
    """Self-service role panels."""

    EMOJI = "🎭"
    COLOR = Palette.PURPLE
    DESCRIPTION = "Role panels with buttons — members pick their own roles."

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_dynamic_items(RoleButton)

    @app_commands.command(name="rolepanel", description="Post a role panel with self-assign buttons")
    @app_commands.describe(
        title="Panel title",
        description="What is this panel about?",
        role1="First role",
        role2="Second role (optional)",
        role3="Third role (optional)",
        role4="Fourth role (optional)",
        role5="Fifth role (optional)",
    )
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def rolepanel(
        self,
        interaction: discord.Interaction,
        title: str,
        description: str,
        role1: discord.Role,
        role2: discord.Role | None = None,
        role3: discord.Role | None = None,
        role4: discord.Role | None = None,
        role5: discord.Role | None = None,
    ):
        roles = []
        seen_role_ids = set()
        for role in (role1, role2, role3, role4, role5):
            if role is not None and role.id not in seen_role_ids:
                roles.append(role)
                seen_role_ids.add(role.id)
        title, description, _, text_errors = validate_role_panel_input(
            title, description, [role.id for role in roles]
        )
        if text_errors:
            embed = make_embed(
                "⚠️ Invalid role panel",
                "\n".join(f"• {error}" for error in text_errors),
                color=Palette.DANGER,
            )
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        # interaction.user is the configurer, so their own position is part of
        # the check: Manage Roles lets you assign roles below yourself, and a
        # panel must not become a way around that.
        blocked = [
            (role, reason)
            for role in roles
            if (reason := role_assignment_error(role, interaction.guild, interaction.user))
        ]
        if blocked:
            lines = "\n".join(f"• {role.mention} — {reason}" for role, reason in blocked)
            embed = make_embed(
                "🔒 Cannot use these roles",
                f"{lines}\n\nA panel hands its roles to anyone who presses the button, "
                "so staff roles and roles above your own position are never eligible.",
                color=Palette.DANGER,
            )
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        embed, view = build_role_panel(title, description, roles)
        message = await respond(interaction, embed, view=view)
        if message is None:
            try:
                message = await interaction.original_response()
            except discord.HTTPException:
                return
        await asyncio.to_thread(
            save_role_panel_record,
            interaction.guild_id,
            message.id,
            interaction.channel_id,
            title,
            description,
            [role.id for role in roles],
            created_by=interaction.user.id,
        )


async def setup(bot):
    await bot.add_cog(Roles(bot))
