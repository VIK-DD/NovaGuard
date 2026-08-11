"""Global maintenance-mode helpers."""

from __future__ import annotations

import json
import os
import secrets
from datetime import UTC, datetime

import discord

from .admin_auth import hash_key, verify_key
from .config import BASE_DIR

MAINTENANCE_STATE_FILE = BASE_DIR / "data" / "maintenance.json"
DEFAULT_MAINTENANCE_MESSAGE = "Working Mode Active"
PREVIEW_PREFIX = "ng_preview_"
PREVIEW_BYTES = 24


def _default_state():
    return {
        "enabled": False,
        "message": DEFAULT_MAINTENANCE_MESSAGE,
        "updated_at": None,
        "updated_by": None,
        # Only ever the hash. The code itself is shown once, in Discord.
        "preview_hash": None,
        "preview_salt": None,
    }


def generate_preview_code():
    """A fresh preview code. Returned in plaintext once, never stored."""
    return f"{PREVIEW_PREFIX}{secrets.token_urlsafe(PREVIEW_BYTES)}"


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
    previous = load_maintenance_state()
    state = _default_state()
    state["enabled"] = bool(enabled)
    state["message"] = normalize_maintenance_message(message)
    state["updated_at"] = datetime.now(UTC).isoformat()
    state["updated_by"] = updated_by

    code = None
    if state["enabled"]:
        if previous.get("enabled") and previous.get("preview_hash"):
            # Already on — this is a wording fix, not a new maintenance window.
            # Keeping the hash and the timestamp keeps the operator's own open
            # preview session alive; rotating here would lock them out for
            # correcting a typo.
            state["preview_hash"] = previous.get("preview_hash")
            state["preview_salt"] = previous.get("preview_salt")
            state["updated_at"] = previous.get("updated_at") or state["updated_at"]
        else:
            code = generate_preview_code()
            state["preview_hash"], state["preview_salt"] = hash_key(code)

    MAINTENANCE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path = MAINTENANCE_STATE_FILE.with_name(MAINTENANCE_STATE_FILE.name + ".tmp")
    temp_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(temp_path, MAINTENANCE_STATE_FILE)

    # Added after the write, so the plaintext reaches the caller and nothing else.
    return {**state, "preview_code": code}


def verify_preview_code(code):
    """The activation's timestamp when the code opens the site, else None."""
    state = load_maintenance_state()
    if not state.get("enabled"):
        return None
    if not verify_key(code, state.get("preview_hash"), state.get("preview_salt")):
        return None
    return state.get("updated_at")


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
