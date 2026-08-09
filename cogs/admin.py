"""Owner-only controls behind the admin key.

Everything here needs two things: being the Discord application owner, and an
unlocked session from `/admin unlock`. The split matters because owning the
account is not proof the person at the keyboard is the owner - a stolen
Discord session passes the first check and fails the second.
"""

import discord
from discord import app_commands
from discord.ext import commands

from core.admin_auth import (
    GATE_LOCKED_OUT,
    GATE_NO_KEY,
    GATE_NOT_OWNER,
    GATE_OK,
    SESSIONS,
    check_key,
    gate_state,
    key_is_configured,
    looks_like_key,
    recent_audit,
    record_audit,
)
from core.maintenance import user_can_bypass_maintenance
from core.theme import Palette, brand_footer, make_embed
from core.utils import defer_interaction, respond

ADMIN_LABEL = "Admin"


def _embed(title, description, color=Palette.PRIMARY):
    embed = make_embed(title, description, color=color)
    brand_footer(embed, ADMIN_LABEL)
    return embed


def _minutes(seconds):
    minutes, secs = divmod(max(0, int(seconds)), 60)
    if minutes and secs:
        return f"{minutes}m {secs}s"
    return f"{minutes}m" if minutes else f"{secs}s"


async def is_bot_owner(bot, user):
    """The application owner, or a member of its team."""
    return await user_can_bypass_maintenance(bot, user)


def refusal_embed(state):
    """The message for a refused privileged command.

    A non-owner is told only that the command is not theirs. Revealing that a
    second factor exists tells an attacker what to go looking for.
    """
    if state == GATE_NOT_OWNER:
        return _embed(
            "Not available",
            "This command belongs to the bot owner.",
            color=Palette.WARNING,
        )
    if state == GATE_NO_KEY:
        return _embed(
            "No admin key yet",
            "Generate one on the host, then unlock:\n"
            "```bash\nvenv/bin/python -m tools.admin_key\n```",
            color=Palette.WARNING,
        )
    return _embed(
        "Locked",
        "Run `/admin unlock` in a DM with me first.",
        color=Palette.WARNING,
    )


async def require_admin(interaction, bot, *, action=None):
    """Gate a privileged command. True when it may proceed.

    Sends the refusal itself, and records refusals: a denied attempt on an
    owner command is exactly the event worth having a trail of.
    """
    owner = await is_bot_owner(bot, interaction.user)
    state = gate_state(owner, interaction.user.id)
    if state == GATE_OK:
        return True

    if state == GATE_LOCKED_OUT:
        wait = SESSIONS.lockout_seconds_left(interaction.user.id)
        embed = _embed(
            "Too many attempts",
            f"Locked for `{_minutes(wait)}` after repeated wrong keys.",
            color=Palette.DANGER,
        )
    else:
        embed = refusal_embed(state)

    record_audit(
        interaction.user.id,
        action or "admin.denied",
        actor_name=str(interaction.user),
        outcome="denied",
        detail=state,
    )
    await respond(interaction, embed, ephemeral=True)
    return False


class Admin(commands.Cog):
    """Owner controls, gated by the admin key."""

    EMOJI = "🔐"
    COLOR = Palette.PRIMARY
    DESCRIPTION = "Owner-only controls protected by a second factor."

    def __init__(self, bot):
        self.bot = bot

    admin = app_commands.Group(name="admin", description="Owner controls")

    @admin.command(name="unlock", description="Unlock owner commands with your admin key")
    @app_commands.describe(key="Your admin key. Run this in a DM, never in a server.")
    async def unlock(self, interaction: discord.Interaction, key: str):
        await defer_interaction(interaction, ephemeral=True)

        if not await is_bot_owner(self.bot, interaction.user):
            # The same message a non-owner gets everywhere else: no hint that
            # a key is the thing they are missing.
            record_audit(
                interaction.user.id,
                "admin.unlock",
                actor_name=str(interaction.user),
                outcome="denied",
                detail="not_owner",
            )
            return await respond(interaction, refusal_embed(GATE_NOT_OWNER), ephemeral=True)

        if interaction.guild is not None:
            return await respond(
                interaction,
                _embed(
                    "Use a DM",
                    "Unlocking in a server puts your key in Discord's audit log. "
                    "Send `/admin unlock` in a DM with me instead, and rotate the key "
                    "if you already typed it here:\n```bash\n"
                    "venv/bin/python -m tools.admin_key --force\n```",
                    color=Palette.DANGER,
                ),
                ephemeral=True,
            )

        if not key_is_configured():
            return await respond(interaction, refusal_embed(GATE_NO_KEY), ephemeral=True)

        if SESSIONS.is_locked_out(interaction.user.id):
            wait = SESSIONS.lockout_seconds_left(interaction.user.id)
            return await respond(
                interaction,
                _embed(
                    "Too many attempts",
                    f"Locked for `{_minutes(wait)}`. Wait it out, or rotate the key on the host.",
                    color=Palette.DANGER,
                ),
                ephemeral=True,
            )

        if not looks_like_key(key) or not check_key(key):
            remaining = SESSIONS.record_failure(interaction.user.id)
            record_audit(
                interaction.user.id,
                "admin.unlock",
                actor_name=str(interaction.user),
                outcome="failed",
                detail=f"{remaining} attempts left",
            )
            return await respond(
                interaction,
                _embed(
                    "Wrong key",
                    f"`{remaining}` attempt(s) left before a temporary lockout."
                    if remaining
                    else "Locked out. Wait, or rotate the key on the host.",
                    color=Palette.DANGER,
                ),
                ephemeral=True,
            )

        ttl = SESSIONS.unlock(interaction.user.id)
        record_audit(
            interaction.user.id, "admin.unlock", actor_name=str(interaction.user), outcome="ok"
        )
        await respond(
            interaction,
            _embed(
                "Unlocked",
                f"Owner commands are open for `{_minutes(ttl)}`.\n"
                "-# Locks again on expiry, on `/admin lock`, or when the bot restarts.",
                color=Palette.SUCCESS,
            ),
            ephemeral=True,
        )

    @admin.command(name="lock", description="Close your admin session now")
    async def lock(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        if not await is_bot_owner(self.bot, interaction.user):
            return await respond(interaction, refusal_embed(GATE_NOT_OWNER), ephemeral=True)

        closed = SESSIONS.lock(interaction.user.id)
        if closed:
            record_audit(
                interaction.user.id, "admin.lock", actor_name=str(interaction.user), outcome="ok"
            )
        await respond(
            interaction,
            _embed(
                "Locked" if closed else "Already locked",
                "Owner commands need `/admin unlock` again."
                if closed
                else "There was no open session.",
                color=Palette.SUCCESS if closed else Palette.DARK,
            ),
            ephemeral=True,
        )

    @admin.command(name="status", description="Whether a key exists and your session state")
    async def status(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        if not await is_bot_owner(self.bot, interaction.user):
            return await respond(interaction, refusal_embed(GATE_NOT_OWNER), ephemeral=True)

        configured = key_is_configured()
        unlocked = SESSIONS.is_unlocked(interaction.user.id)
        left = SESSIONS.seconds_left(interaction.user.id)

        lines = [
            f"{'✅' if configured else '❌'} **Admin key** — "
            + ("configured" if configured else "not generated yet"),
            f"{'🔓' if unlocked else '🔒'} **Your session** — "
            + (f"unlocked, `{_minutes(left)}` left" if unlocked else "locked"),
        ]
        if not configured:
            lines.append("\n```bash\nvenv/bin/python -m tools.admin_key\n```")

        await respond(
            interaction,
            _embed("Admin status", "\n".join(lines), color=Palette.INFO),
            ephemeral=True,
        )

    @admin.command(name="audit", description="Recent privileged actions")
    @app_commands.describe(limit="How many entries to show (1-25)")
    async def audit(
        self, interaction: discord.Interaction, limit: app_commands.Range[int, 1, 25] = 10
    ):
        await defer_interaction(interaction, ephemeral=True)
        if not await require_admin(interaction, self.bot, action="admin.audit"):
            return

        rows = recent_audit(limit)
        if not rows:
            return await respond(
                interaction,
                _embed("Audit trail", "Nothing recorded yet.", color=Palette.DARK),
                ephemeral=True,
            )

        icons = {"ok": "✅", "denied": "⛔", "failed": "❌"}
        lines = []
        for row in rows:
            icon = icons.get(row["outcome"], "•")
            when = (row["created_at"] or "")[:16].replace("T", " ")
            who = row["actor_name"] or row["actor_id"]
            detail = f" — {row['detail']}" if row["detail"] else ""
            target = f" `{row['target']}`" if row["target"] else ""
            lines.append(f"{icon} `{when}` **{row['action']}**{target}\n-# {who}{detail}")

        await respond(
            interaction,
            _embed("Audit trail", "\n".join(lines)[:4000], color=Palette.INFO),
            ephemeral=True,
        )

    @app_commands.command(name="guilds", description="Owner: every server this bot is in")
    async def guilds(self, interaction: discord.Interaction):
        await defer_interaction(interaction, ephemeral=True)
        if not await require_admin(interaction, self.bot, action="admin.guilds"):
            return

        guilds = sorted(self.bot.guilds, key=lambda g: g.member_count or 0, reverse=True)
        record_audit(
            interaction.user.id,
            "admin.guilds",
            actor_name=str(interaction.user),
            detail=f"{len(guilds)} servers",
        )
        if not guilds:
            return await respond(
                interaction,
                _embed("Servers", "The bot is not in any server.", color=Palette.DARK),
                ephemeral=True,
            )

        lines = [
            f"`{guild.id}` **{guild.name}** — `{guild.member_count or 0}` members"
            for guild in guilds[:25]
        ]
        if len(guilds) > 25:
            lines.append(f"-# and `{len(guilds) - 25}` more")

        await respond(
            interaction,
            _embed(f"Servers ({len(guilds)})", "\n".join(lines)[:4000], color=Palette.INFO),
            ephemeral=True,
        )

    @app_commands.command(name="leaveguild", description="Owner: make the bot leave a server")
    @app_commands.describe(guild_id="The server id, from /guilds")
    async def leaveguild(self, interaction: discord.Interaction, guild_id: str):
        await defer_interaction(interaction, ephemeral=True)
        if not await require_admin(interaction, self.bot, action="admin.leaveguild"):
            return

        target = self.bot.get_guild(int(guild_id)) if guild_id.strip().isdigit() else None
        if target is None:
            return await respond(
                interaction,
                _embed(
                    "Server not found",
                    f"No server with id `{guild_id[:32]}`. Check `/guilds`.",
                    color=Palette.WARNING,
                ),
                ephemeral=True,
            )

        name = target.name
        try:
            await target.leave()
        except discord.HTTPException as error:
            record_audit(
                interaction.user.id,
                "admin.leaveguild",
                actor_name=str(interaction.user),
                target=guild_id,
                outcome="failed",
                detail=str(error)[:120],
            )
            return await respond(
                interaction,
                _embed("Could not leave", f"Discord refused: `{error}`", color=Palette.DANGER),
                ephemeral=True,
            )

        record_audit(
            interaction.user.id,
            "admin.leaveguild",
            actor_name=str(interaction.user),
            target=f"{guild_id} ({name})",
        )
        await respond(
            interaction,
            _embed(
                "Left the server", f"No longer in **{name}** (`{guild_id}`).", color=Palette.SUCCESS
            ),
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(Admin(bot))
