"""Validation and cryptographically secure winner selection for giveaways."""

import re
import secrets
from datetime import timedelta

from .utils import parse_duration


def draw_winners(entrants, count, *, exclude=()):
    """Draw unique winners while preferring entrants not picked previously."""
    unique = list(dict.fromkeys(entrants))
    excluded = set(exclude)
    fresh = [entrant for entrant in unique if entrant not in excluded]
    fallback = [entrant for entrant in unique if entrant in excluded]
    wanted = min(max(int(count), 0), len(unique))
    selected = secrets.SystemRandom().sample(fresh, min(wanted, len(fresh)))
    if len(selected) < wanted:
        selected.extend(secrets.SystemRandom().sample(fallback, wanted - len(selected)))
    return selected


def validate_giveaway_input(duration, prize, winners):
    """Normalize dashboard or slash-command input before creating a message."""
    errors = []
    duration_text = str(duration or "").strip().lower()
    if not re.fullmatch(r"(?:\d+\s*[smhdw]\s*)+", duration_text):
        delta = None
    else:
        delta = parse_duration(duration_text)
    if not delta or delta < timedelta(minutes=1) or delta > timedelta(days=30):
        errors.append("duration must be between 1 minute and 30 days, for example 30m, 1h or 2d")

    clean_prize = " ".join(str(prize or "").split())
    if not clean_prize or len(clean_prize) > 200:
        errors.append("prize must contain 1–200 characters")

    if isinstance(winners, bool) or not isinstance(winners, int) or not 1 <= winners <= 10:
        errors.append("winners must be a whole number between 1 and 10")
    return delta, clean_prize, winners, errors
