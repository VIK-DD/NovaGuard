"""Which commands the public website deliberately does not list.

The command catalog on the website is checked against the bot itself, so a
command added to a cog and forgotten everywhere else fails the build. That
check is only worth having if "missing" and "left out on purpose" are told
apart — otherwise the first deliberate omission forces the check to be
loosened into one that catches nothing.

Everything here runs host-wide rather than per-server: archives covering every
guild, the maintenance switch, the admin key, the guild list. A server owner
reading the catalog cannot use any of it, and naming the host's tooling in
public only tells a stranger which doors exist.

Adding a command to a cog without deciding where it belongs breaks the catalog
test, which is the point: the choice gets made once, here or on the website,
and never by accident.
"""

UNLISTED_COMMANDS = frozenset(
    {
        # Whole-host archives. A server takes its own data out with /config export.
        "config backup",
        "backup create",
        "backup status",
        "backup remote",
        "backup list",
        "backup inspect",
        "backup test",
        "backup restore",
        # Host operations.
        "levels backfill run",
        "maintenance",
        "resync",
        "grant",
        # The admin key and its audit trail.
        "admin unlock",
        "admin lock",
        "admin status",
        "admin audit",
        # Where the bot is, and leaving it.
        "guilds",
        "leaveguild",
    }
)
