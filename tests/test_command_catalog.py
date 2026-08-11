import json
from pathlib import Path

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


def test_public_command_catalog_matches_every_supported_bot_command():
    _, commands = _catalog_commands()

    assert len(commands) == len(set(commands)), "The public command catalog contains duplicates"
    assert {command.removeprefix("/") for command in commands} == _bot_commands()


def test_public_command_catalog_has_valid_access_metadata():
    categories, commands = _catalog_commands()

    assert categories
    assert all(category["audience"] in {"everyone", "server-admin", "owner"} for category in categories)
    assert all(category["commands"] for category in categories)
    assert all(command.startswith("/") and "|" not in command for command in commands)
