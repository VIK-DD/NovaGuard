"""The shop catalogue, and what buying something actually does.

The old shop sold five strings. You paid, the key landed in a list, and the
list was printed back at you - nothing in the bot ever read it again. This
module is the part that was missing: items that expire, perks the rest of the
bot has to check, and a purchase path that can refuse.

Everything here is a plain function over a wallet dict. The Economy cog owns
the wallet and the saving; this owns the rules, which is what makes them
testable without a Discord connection or a database.
"""

import secrets

# Crates cost coins and pay out items, so the draw is a wager like the
# economy games. The `rng` parameter below stays injectable for tests;
# only the default changes.
_rng = secrets.SystemRandom()
from datetime import UTC, datetime, timedelta

TROPHY = "trophy"
BOOSTER = "booster"
PERK = "perk"
TITLE = "title"
CRATE = "crate"

# Effect keys. The rest of the bot asks for these by name - levels asks for
# XP_BOOST, economy asks for WORK_RUSH - so they are constants rather than
# strings scattered across cogs.
XP_BOOST = "xp_boost"
WORK_RUSH = "work_rush"

# Deliberately mild. A booster that outruns showing up every day would turn
# the level board into a record of who spent the most, which is the one thing
# it must not become.
XP_BOOST_MULTIPLIER = 1.5
XP_BOOST_HOURS = 6
WORK_RUSH_FACTOR = 0.5
WORK_RUSH_HOURS = 24

SHOP_ITEMS = {
    # Trophies keep their original keys so wallets bought under the old shop
    # keep what they paid for.
    "star": {"label": "Star", "price": 1000, "kind": TROPHY, "icon": "⭐"},
    "rocket": {"label": "Rocket", "price": 2500, "kind": TROPHY, "icon": "🚀"},
    "gem": {"label": "Gem", "price": 5000, "kind": TROPHY, "icon": "💎"},
    "crown": {"label": "Crown", "price": 10000, "kind": TROPHY, "icon": "👑"},
    "trophy": {"label": "Golden Trophy", "price": 25000, "kind": TROPHY, "icon": "🏆"},
    XP_BOOST: {
        "label": "XP Boost",
        "price": 1200,
        "kind": BOOSTER,
        "icon": "⚡",
        "effect": XP_BOOST,
        "value": XP_BOOST_MULTIPLIER,
        "hours": XP_BOOST_HOURS,
        "description": f"{XP_BOOST_MULTIPLIER}x XP from messages for {XP_BOOST_HOURS} hours.",
    },
    WORK_RUSH: {
        "label": "Work Rush",
        "price": 900,
        "kind": PERK,
        "icon": "🛠️",
        "effect": WORK_RUSH,
        "value": WORK_RUSH_FACTOR,
        "hours": WORK_RUSH_HOURS,
        "description": f"/work cooldown cut in half for {WORK_RUSH_HOURS} hours.",
    },
    "streak_shield": {
        "label": "Streak Shield",
        "price": 1500,
        "kind": PERK,
        "icon": "🛡️",
        "stackable": True,
        "description": "Protects your /daily streak the next time you miss a day.",
    },
    "title_night_owl": {
        "label": "Night Owl",
        "price": 750,
        "kind": TITLE,
        "icon": "🦉",
        "title": "Night Owl",
    },
    "title_grinder": {
        "label": "The Grinder",
        "price": 750,
        "kind": TITLE,
        "icon": "⛏️",
        "title": "The Grinder",
    },
    "title_veteran": {
        "label": "Veteran",
        "price": 2000,
        "kind": TITLE,
        "icon": "🎖️",
        "title": "Veteran",
    },
    "title_legend": {
        "label": "Legend",
        "price": 6000,
        "kind": TITLE,
        "icon": "🌟",
        "title": "Legend",
    },
    CRATE: {
        "label": "Mystery Crate",
        "price": 500,
        "kind": CRATE,
        "icon": "📦",
        "description": "Coins, a booster, or - rarely - something better.",
    },
}

# What a crate can hold, and how often. Weights are relative, so the table can
# be rebalanced without recomputing percentages by hand.
CRATE_TABLE = (
    {"weight": 40, "kind": "coins", "amount": 250, "label": "250 coins"},
    {"weight": 25, "kind": "coins", "amount": 600, "label": "600 coins"},
    {"weight": 15, "kind": "item", "item": WORK_RUSH, "label": "Work Rush"},
    {"weight": 12, "kind": "item", "item": XP_BOOST, "label": "XP Boost"},
    {"weight": 6, "kind": "item", "item": "streak_shield", "label": "Streak Shield"},
    {"weight": 2, "kind": "coins", "amount": 3000, "label": "3,000 coins"},
)


def now_utc() -> datetime:
    return datetime.now(UTC)


def parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def item(key):
    return SHOP_ITEMS.get(str(key))


def catalog(kind=None):
    """The shop, optionally narrowed to one kind, cheapest first."""
    entries = [
        {"key": key, **spec}
        for key, spec in SHOP_ITEMS.items()
        if kind is None or spec["kind"] == kind
    ]
    return sorted(entries, key=lambda entry: (entry["price"], entry["label"]))


def label_for(key):
    spec = item(key)
    if not spec:
        return str(key)
    icon = spec.get("icon")
    return f"{icon} {spec['label']}" if icon else spec["label"]


def owned_keys(wallet) -> list[str]:
    """Everything one-off the wallet holds: trophies and titles alike.

    Trophies stay in their own list because that is where the old shop put
    them and where /balance still reads them from.
    """
    return list(wallet.get("trophies") or []) + list(wallet.get("titles") or [])


def owns(wallet, key) -> bool:
    return str(key) in owned_keys(wallet)


def active_effects(wallet, moment=None) -> dict:
    """The effects that are live right now.

    Expiry is checked on read rather than swept on a schedule: an expired
    effect nobody has looked at has no way to affect anything, and a sweep
    would be one more loop to keep alive for no gain.
    """
    moment = moment or now_utc()
    live = {}
    for name, record in (wallet.get("effects") or {}).items():
        expires_at = parse_time((record or {}).get("expires_at"))
        if expires_at and expires_at > moment:
            live[name] = record
    return live


def effect_value(wallet, effect, moment=None, default=1.0) -> float:
    record = active_effects(wallet, moment).get(effect)
    if not record:
        return default
    try:
        return float(record.get("value", default))
    except (TypeError, ValueError):
        return default


def effect_expiry(wallet, effect, moment=None):
    record = active_effects(wallet, moment).get(effect)
    return parse_time(record.get("expires_at")) if record else None


def prune_effects(wallet, moment=None) -> bool:
    """Drop expired effects from storage. Returns whether anything changed."""
    effects = wallet.get("effects") or {}
    if not effects:
        return False
    live = active_effects(wallet, moment)
    if len(live) == len(effects):
        return False
    wallet["effects"] = live
    return True


def shields(wallet) -> int:
    try:
        return max(0, int(wallet.get("streak_shields", 0) or 0))
    except (TypeError, ValueError):
        return 0


def use_shield(wallet) -> bool:
    """Spend one streak shield. Returns whether there was one to spend."""
    count = shields(wallet)
    if count <= 0:
        return False
    wallet["streak_shields"] = count - 1
    return True


def work_cooldown(wallet, base: timedelta, moment=None) -> timedelta:
    """How long this member waits between shifts, perk included.

    Returned as a duration rather than applied by the caller so the perk
    cannot be forgotten in one of the two places /work checks the clock.
    """
    factor = effect_value(wallet, WORK_RUSH, moment, default=1.0)
    return timedelta(seconds=max(0.0, base.total_seconds() * factor))


class PurchaseResult:
    """Why a purchase worked, or why it did not.

    A tuple would be shorter and would make every caller remember which
    position meant what.
    """

    def __init__(self, ok, *, error=None, key=None, spent=0, expires_at=None, granted=None):
        self.ok = ok
        self.error = error
        self.key = key
        self.spent = spent
        self.expires_at = expires_at
        self.granted = granted or []

    def __repr__(self):
        return f"<PurchaseResult ok={self.ok} error={self.error!r} key={self.key!r}>"


def grant(wallet, key, moment=None) -> list[str]:
    """Put an item in a wallet without charging for it.

    Crates and the owner's /grant both need this, and neither is a purchase.
    Returns readable notes about what changed.
    """
    spec = item(key)
    if not spec:
        return []

    moment = moment or now_utc()
    kind = spec["kind"]
    notes = []

    if kind == TROPHY:
        wallet.setdefault("trophies", [])
        if key not in wallet["trophies"]:
            wallet["trophies"].append(key)
            notes.append(label_for(key))
    elif kind == TITLE:
        wallet.setdefault("titles", [])
        if key not in wallet["titles"]:
            wallet["titles"].append(key)
            notes.append(label_for(key))
    elif spec.get("stackable"):
        wallet["streak_shields"] = shields(wallet) + 1
        notes.append(label_for(key))
    elif spec.get("effect"):
        effects = wallet.setdefault("effects", {})
        current = parse_time((effects.get(spec["effect"]) or {}).get("expires_at"))
        # Buying a second one while the first is running extends it rather
        # than throwing the remaining hours away.
        base = current if current and current > moment else moment
        effects[spec["effect"]] = {
            "item": key,
            "value": spec.get("value", 1.0),
            "expires_at": (base + timedelta(hours=spec.get("hours", 1))).isoformat(),
        }
        notes.append(label_for(key))

    return notes


def purchase(wallet, key, moment=None) -> PurchaseResult:
    """Charge the wallet and hand over the item, or explain the refusal.

    The wallet is only touched once the purchase is certain to succeed, so a
    refusal can never leave a member charged for nothing.
    """
    spec = item(key)
    if not spec:
        return PurchaseResult(False, error="unknown")
    if spec["kind"] == CRATE:
        # Crates are opened, not owned. /crate handles them, so the reward
        # roll and the charge stay in one place.
        return PurchaseResult(False, error="crate")

    moment = moment or now_utc()
    price = int(spec["price"])

    if spec["kind"] in (TROPHY, TITLE) and owns(wallet, key):
        return PurchaseResult(False, error="owned", key=key)

    coins = int(wallet.get("coins", 0) or 0)
    if coins < price:
        return PurchaseResult(False, error="poor", key=key, spent=price - coins)

    wallet["coins"] = coins - price
    granted = grant(wallet, key, moment)

    return PurchaseResult(
        True,
        key=key,
        spent=price,
        expires_at=effect_expiry(wallet, spec["effect"], moment) if spec.get("effect") else None,
        granted=granted,
    )


def open_crate(wallet, moment=None, rng=None) -> PurchaseResult:
    """Charge for a crate and roll its contents.

    ``rng`` is injectable so the reward table can be tested without waiting
    for the right outcome to show up.
    """
    price = int(SHOP_ITEMS[CRATE]["price"])
    coins = int(wallet.get("coins", 0) or 0)
    if coins < price:
        return PurchaseResult(False, error="poor", key=CRATE, spent=price - coins)

    moment = moment or now_utc()
    rng = rng or _rng
    reward = rng.choices(CRATE_TABLE, weights=[row["weight"] for row in CRATE_TABLE], k=1)[0]

    wallet["coins"] = coins - price
    if reward["kind"] == "coins":
        wallet["coins"] += int(reward["amount"])
        granted = [reward["label"]]
    else:
        # A duplicate one-off grants nothing, so the label stands in rather
        # than the crate appearing to have been empty.
        granted = grant(wallet, reward["item"], moment) or [reward["label"]]

    return PurchaseResult(True, key=CRATE, spent=price, granted=granted)


def equip_title(wallet, key) -> bool:
    """Wear a title you own. Returns whether it took."""
    if key is None:
        wallet["title"] = None
        return True
    spec = item(key)
    if not spec or spec["kind"] != TITLE or key not in (wallet.get("titles") or []):
        return False
    wallet["title"] = key
    return True


def worn_title(wallet) -> str | None:
    """The title to print next to a name, if one is worn and still owned."""
    key = wallet.get("title")
    if not key or key not in (wallet.get("titles") or []):
        return None
    spec = item(key)
    return spec.get("title") if spec else None
