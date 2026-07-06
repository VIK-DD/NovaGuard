"""Global maintenance-mode helpers."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import discord

from .config import BASE_DIR

MAINTENANCE_STATE_FILE = BASE_DIR / "data" / "maintenance.json"
DEFAULT_MAINTENANCE_MESSAGE = "Working Mode Active"


def _default_state():
    return {
        "enabled": False,
        "message": DEFAULT_MAINTENANCE_MESSAGE,
        "updated_at": None,
        "updated_by": None,
    }


def normalize_maintenance_message(message):
    cleaned = " ".join(str(message or "").split()).strip()
    if not cleaned:
        cleaned = DEFAULT_MAINTENANCE_MESSAGE
    return cleaned[:120]


def load_maintenance_state():
    state = _default_state()
    if not MAINTENANCE_STATE_FILE.exists():
        return state

    try:
        raw = json.loads(MAINTENANCE_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return state

    if isinstance(raw, dict):
        state.update(raw)
    state["enabled"] = bool(state.get("enabled"))
    state["message"] = normalize_maintenance_message(state.get("message"))
    return state


def save_maintenance_state(enabled, message=None, updated_by=None):
    state = _default_state()
    state["enabled"] = bool(enabled)
    state["message"] = normalize_maintenance_message(message)
    state["updated_at"] = datetime.now(UTC).isoformat()
    state["updated_by"] = updated_by

    MAINTENANCE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path = MAINTENANCE_STATE_FILE.with_name(MAINTENANCE_STATE_FILE.name + ".tmp")
    temp_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(temp_path, MAINTENANCE_STATE_FILE)
    return state


async def user_can_bypass_maintenance(bot, user):
    """Allow only the application owner or team members to bypass maintenance."""
    app_info = getattr(bot, "_maintenance_app_info", None)
    if app_info is None:
        try:
            app_info = await bot.application_info()
        except discord.HTTPException:
            return False
        bot._maintenance_app_info = app_info

    team = getattr(app_info, "team", None)
    if team:
        return any(member.id == user.id for member in team.members)

    owner = getattr(app_info, "owner", None)
    return bool(owner and owner.id == user.id)
