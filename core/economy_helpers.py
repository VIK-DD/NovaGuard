"""Deterministic wallet, dashboard and game helpers for the economy cog."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from core import shop


CURRENCY = "🪙"
SLOT_REELS = ("🍒", "🍋", "🍇", "💎", "7️⃣")


@dataclass(frozen=True)
class SlotOutcome:
    """The balance change and display category produced by one slot spin."""

    kind: str
    net: int
    multiplier: int | None = None


def parse_saved_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def get_wallet(data, guild_id, user_id):
    guild_data = data.setdefault(str(guild_id), {})
    return guild_data.setdefault(
        str(user_id),
        {"coins": 0, "daily_streak": 0, "last_daily": None, "last_work": None, "trophies": []},
    )


def wallet_snapshot(data, guild_id, user_id):
    """Read a wallet without creating an empty record as a side effect."""
    return data.get(str(guild_id), {}).get(str(user_id))


def _non_negative_integer(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def economy_status_payload(data, guild):
    """Build the public dashboard summary without mutating wallet storage."""
    guild_data = data.get(str(guild.id), {})
    wallets = [
        (user_id, wallet)
        for user_id, wallet in guild_data.items()
        if isinstance(wallet, dict)
    ]
    ordered = sorted(
        wallets,
        key=lambda item: _non_negative_integer(item[1].get("coins")),
        reverse=True,
    )
    leaderboard = []
    for position, (user_id, wallet) in enumerate(ordered[:10], 1):
        member = guild.get_member(int(user_id)) if str(user_id).isdigit() else None
        leaderboard.append(
            {
                "position": position,
                "user_id": str(user_id),
                "display_name": member.display_name if member else f"Member {user_id}",
                "coins": _non_negative_integer(wallet.get("coins")),
                "daily_streak": _non_negative_integer(wallet.get("daily_streak")),
            }
        )
    return {
        "tracked_wallets": len(wallets),
        "total_coins": sum(_non_negative_integer(wallet.get("coins")) for _, wallet in wallets),
        "leaderboard": leaderboard,
        "shop": [
            {
                "key": item["key"],
                "label": item["label"],
                "icon": item.get("icon") or "🪙",
                "price": int(item["price"]),
                "kind": item["kind"],
                "description": item.get("description"),
            }
            for item in shop.catalog()
        ],
    }


def ranked_wallets(data, guild_id, *, limit=10):
    """Return positive balances in descending order, ignoring malformed rows."""
    guild_data = data.get(str(guild_id), {})
    wallets = []
    for user_id, wallet in guild_data.items():
        if not isinstance(wallet, dict):
            continue
        coins = _non_negative_integer(wallet.get("coins"))
        if coins:
            wallets.append((str(user_id), coins))
    return sorted(wallets, key=lambda item: item[1], reverse=True)[:limit]


def slot_outcome(reels, amount):
    """Calculate a slot result independently from randomness and persistence."""
    if len(reels) != 3:
        raise ValueError("a slot spin must contain exactly three reels")
    stake = int(amount)
    if stake < 0:
        raise ValueError("a slot stake cannot be negative")

    if reels[0] == reels[1] == reels[2]:
        multiplier = 10 if reels[0] == "7️⃣" else 5
        return SlotOutcome("jackpot", stake * multiplier - stake, multiplier)
    if reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
        # A 1.5x payout preserves the intended long-run house edge.
        return SlotOutcome("pair", stake // 2)
    return SlotOutcome("loss", -stake)
