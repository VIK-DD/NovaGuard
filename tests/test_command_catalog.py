"""The public catalog against the bot it claims to describe.

Two ways to be wrong, and both matter. Listing a command that does not exist
sends people to type something the bot will not answer. Shipping a command
nobody catalogued leaves it undiscoverable outside Discord. So the catalog
plus the deliberate omissions must account for every command exactly — a new
command belongs in one list or the other, and never in neither.
"""

import json
from pathlib import Path

from core.command_visibility import UNLISTED_COMMANDS
from core.updates import extract_all_commands


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "website-3" / "src" / "data" / "commands.json"


def _bot_commands():
    sources = {
        str(path.relative_to(ROOT)): path.read_text(encoding="utf-8")
        for path in (ROOT / "cogs").glob("*.py")
    }
    return set(extract_all_commands(sources))


def _catalog_commands():
    categories = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    commands = [
        command
        for category in categories
        for command in category["commands"]
    ]
    return categories, commands


def test_public_command_catalog_accounts_for_every_supported_bot_command():
    _, commands = _catalog_commands()
    listed = {command.removeprefix("/") for command in commands}

    assert len(commands) == len(set(commands)), "The public command catalog contains duplicates"
    assert listed | UNLISTED_COMMANDS == _bot_commands()


def test_nothing_deliberately_unlisted_is_published_anyway():
    # Both lists are edited by hand, so the only thing stopping a command from
    # drifting into both is a test that says it cannot.
    _, commands = _catalog_commands()
    listed = {command.removeprefix("/") for command in commands}

    assert not (listed & UNLISTED_COMMANDS)


def test_the_unlisted_set_names_only_commands_that_exist():
    # A command renamed in a cog would otherwise sit here forever, silently
    # excusing the new name from ever being catalogued.
    assert UNLISTED_COMMANDS <= _bot_commands()


def test_public_command_catalog_has_valid_access_metadata():
    categories, commands = _catalog_commands()

    assert categories
    assert all(category["audience"] in {"everyone", "server-admin", "owner"} for category in categories)
    assert all(category["commands"] for category in categories)
    assert all(command.startswith("/") and "|" not in command for command in commands)
