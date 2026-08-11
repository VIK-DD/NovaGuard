"""Shared per-guild settings for the optional /ask assistant."""

AI_DEFAULTS = {
    "enabled": True,
    "answer_mode": "public",
    "channel_id": None,
    "max_question_chars": 2000,
}


def resolve_ai(settings):
    saved = settings.get("ai") if isinstance(settings, dict) else None
    saved = saved if isinstance(saved, dict) else {}
    resolved = dict(AI_DEFAULTS)
    if isinstance(saved.get("enabled"), bool):
        resolved["enabled"] = saved["enabled"]
    if saved.get("answer_mode") in {"public", "private"}:
        resolved["answer_mode"] = saved["answer_mode"]
    channel_id = saved.get("channel_id")
    resolved["channel_id"] = str(channel_id) if channel_id else None
    max_chars = saved.get("max_question_chars")
    if isinstance(max_chars, int) and not isinstance(max_chars, bool):
        resolved["max_question_chars"] = min(max(max_chars, 100), 2000)
    return resolved


def validate_ai(patch, current, channel_ids):
    if not isinstance(patch, dict):
        return None, ["ai: must be an object"]

    unknown = sorted(set(patch) - set(AI_DEFAULTS))
    errors = [f"ai.{key}: unknown setting" for key in unknown]
    merged = {**resolve_ai({"ai": current}), **patch}

    if not isinstance(merged.get("enabled"), bool):
        errors.append("ai.enabled: must be true or false")
    if merged.get("answer_mode") not in {"public", "private"}:
        errors.append("ai.answer_mode: must be public or private")

    channel_id = merged.get("channel_id")
    if channel_id in (None, "", 0):
        merged["channel_id"] = None
    elif str(channel_id) not in {str(value) for value in channel_ids}:
        errors.append("ai.channel_id: not a text channel in this guild")
    else:
        merged["channel_id"] = str(channel_id)

    max_chars = merged.get("max_question_chars")
    if (
        isinstance(max_chars, bool)
        or not isinstance(max_chars, int)
        or not 100 <= max_chars <= 2000
    ):
        errors.append("ai.max_question_chars: must be a whole number from 100 to 2000")

    return (resolve_ai({"ai": merged}) if not errors else None), errors
