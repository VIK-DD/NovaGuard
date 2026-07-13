"""🎭 Roles category — self-service role panels with persistent buttons."""

import time

import discord
from discord import app_commands
from discord.ext import commands

from core.theme import Palette, brand_footer, make_embed
from core.utils import respond


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
        if role >= guild.me.top_role:
            return await interaction.response.send_message(
                "I cannot manage that role anymore (it moved above my top role).", ephemeral=True
            )

        member = interaction.user
        try:
            if role in member.roles:
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
        roles = [role for role in (role1, role2, role3, role4, role5) if role]

        blocked = [
            role for role in roles
            if role >= interaction.guild.me.top_role or role.managed or role.is_default()
        ]
        if blocked:
            names = ", ".join(role.mention for role in blocked)
            embed = make_embed(
                "🔒 Cannot use these roles",
                f"{names}\n\nRoles must be **below my top role** and not managed by an integration.",
                color=Palette.DANGER,
            )
            brand_footer(embed)
            return await respond(interaction, embed, ephemeral=True)

        view = discord.ui.View(timeout=None)
        for role in roles:
            view.add_item(RoleButton(role.id, label=role.name))

        embed = make_embed(
            f"🎭 {title}",
            f"{description}\n\n" + "\n".join(f"• {role.mention}" for role in roles),
            color=Palette.PURPLE,
        )
        brand_footer(embed, "Click a button to toggle a role")
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(Roles(bot))
