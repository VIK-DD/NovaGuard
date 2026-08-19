"""The message a server sees when NovaGuard arrives.

Written for the people already in the channel, not for whoever installed the
bot: most of them did not choose it, will never open the dashboard, and want
one screen telling them what just joined and what it is allowed to do.

So it is short on purpose. Every command listed is one an ordinary member can
actually run; the administrator's work lives behind a button rather than in
the text, because a wall of commands nobody present can use reads as noise
and gets scrolled past.

No Discord calls here — the cog does the posting. This half is a function of
a guild, which is what lets the wording be read in a test instead of by
joining a server twice to see it.
"""

from core.theme import Palette, brand_footer, make_embed

WEBSITE_URL = "https://novaguard.fun"
COMMANDS_URL = "https://novaguard.fun/commands"
PRIVACY_URL = "https://novaguard.fun/privacy"

# Kept deliberately short. These are the ones worth knowing on day one; the
# button and the website carry the other ninety.
EVERYONE_COMMANDS = (
    ("/help", "Browse every command, by category"),
    ("/rank", "Your level and XP on this server"),
    ("/leaderboard", "Who is ahead this month"),
    # No /privacy here on purpose: it has a section of its own below, and
    # naming it twice in one card made both mentions read as filler.
    ("/serverinfo", "A quick portrait of this server"),
)

ADMIN_COMMANDS = (
    ("/setup", "Choose the channels NovaGuard posts in"),
    ("/welcome set", "Greet new members, and give them a role"),
    ("/automod status", "Review the moderation filters"),
    ("/statuspanel", "Publish a live service status card"),
)


def _command_lines(pairs):
    return "\n".join(f"• `{command}` — {blurb}" for command, blurb in pairs)


def build_info_embed(guild):
    """The public introduction card for one server."""
    embed = make_embed(
        "👋 NovaGuard is here",
        f"Hello, **{guild.name}**.\n\n"
        "NovaGuard handles the quiet work behind a server — welcomes, logging, "
        "levels, moderation filters and voice reports — from one place, so nobody "
        "has to remember which bot does what.",
        color=Palette.PRIMARY,
    )

    embed.add_field(
        name="Getting started",
        value=(
            "A server manager runs `/setup` and picks the channels NovaGuard may "
            "post in.\n\n"
            "**Nothing is switched on until someone chooses it.** Every channel is "
            "optional, and the bot stays quiet until then."
        ),
        inline=False,
    )

    embed.add_field(
        name="Worth knowing",
        value=_command_lines(EVERYONE_COMMANDS),
        inline=False,
    )

    embed.add_field(
        name="For server managers",
        value=_command_lines(ADMIN_COMMANDS),
        inline=False,
    )

    embed.add_field(
        name="Your data",
        value=(
            "`/privacy export` gives you a copy of everything held about you, and "
            "`/privacy delete` erases it — both without asking anyone's permission."
        ),
        inline=False,
    )

    brand_footer(embed, "Welcome")
    return embed
