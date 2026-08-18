"""Second-factor authentication for privileged bot commands.

Being the Discord application owner is the first gate, but a weak one on its
own: Discord token stealers are common, and a stolen session would otherwise
hand an attacker the backup archives and the global kill switch. This module
adds a key the operator keeps in a password manager, so an attacker needs
both the account and something the account never contains.

Three rules shape everything here:

* The key is stored only as a salted scrypt hash. A leaked database must not
  reveal it, so the plaintext exists exactly twice - once when generated, and
  once in the operator's password manager.
* Unlocks are per-user, time limited, and held in memory only. A restart
  relocks everything, which is the safe default after a crash or a redeploy.
* Wrong keys are rate limited. The key is the only thing between an attacker
  with a stolen account and the whole database, so guessing must be slow.

Clock and storage are injectable so the whole flow is testable without a
database or real time passing.
"""

import hashlib
import hmac
import logging
import os
import secrets
import time

log = logging.getLogger(__name__)

KEY_PREFIX = "ng_admin_"
KEY_BYTES = 24
SALT_BYTES = 16

# scrypt cost. 2**14 needs ~16 MB per verification, slow enough to make
# guessing painful and small enough for a 1 GB host to survive.
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32

UNLOCK_TTL_SECONDS = 15 * 60
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 15 * 60
FAILURE_WINDOW_SECONDS = 15 * 60


def generate_key():
    """A fresh admin key. Returned in plaintext exactly once, never stored."""
    return f"{KEY_PREFIX}{secrets.token_urlsafe(KEY_BYTES)}"


def looks_like_key(candidate):
    """Cheap shape check so obvious typos never reach the hash comparison."""
    return bool(candidate) and candidate.strip().startswith(KEY_PREFIX)


def hash_key(plaintext, salt=None):
    """Hash a key for storage. Returns ``(key_hash_hex, salt_hex)``."""
    salt_bytes = secrets.token_bytes(SALT_BYTES) if salt is None else bytes.fromhex(salt)
    digest = hashlib.scrypt(
        (plaintext or "").encode("utf-8"),
        salt=salt_bytes,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return digest.hex(), salt_bytes.hex()


def verify_key(plaintext, key_hash, salt):
    """Constant-time check of a candidate key against the stored hash."""
    if not plaintext or not key_hash or not salt:
        return False
    try:
        candidate, _ = hash_key(plaintext, salt=salt)
    except (ValueError, TypeError):
        return False
    # compare_digest, not ==, so a wrong key cannot be found one byte at a
    # time by measuring how long the comparison takes.
    return hmac.compare_digest(candidate, key_hash)


class AdminSessions:
    """Who is currently unlocked, and who is locked out for guessing.

    Deliberately in memory: an unlock must not outlive the process, so a
    restart means everyone starts locked again.
    """

    def __init__(self, *, ttl_seconds=UNLOCK_TTL_SECONDS, clock=time.monotonic):
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._unlocked = {}
        self._failures = {}

    # ── unlocking ────────────────────────────────────────────────────

    def unlock(self, user_id):
        """Open a session. Returns how long it lasts, in seconds."""
        key = str(user_id)
        self._unlocked[key] = self._clock() + self.ttl_seconds
        self._failures.pop(key, None)
        return self.ttl_seconds

    def lock(self, user_id):
        """Close a session early. True when one was actually open."""
        return self._unlocked.pop(str(user_id), None) is not None

    def lock_all(self):
        count = len(self._unlocked)
        self._unlocked.clear()
        return count

    def is_unlocked(self, user_id):
        key = str(user_id)
        expires_at = self._unlocked.get(key)
        if expires_at is None:
            return False
        if self._clock() >= expires_at:
            # Expired sessions are dropped on read; there is no sweeper and
            # none is needed for a handful of operators.
            self._unlocked.pop(key, None)
            return False
        return True

    def seconds_left(self, user_id):
        """Remaining unlock time in whole seconds, 0 when locked."""
        if not self.is_unlocked(user_id):
            return 0
        return max(0, int(self._unlocked[str(user_id)] - self._clock()))

    # ── guess throttling ─────────────────────────────────────────────

    def record_failure(self, user_id):
        """Note a wrong key. Returns attempts remaining before lockout."""
        key = str(user_id)
        now = self._clock()
        recent = [at for at in self._failures.get(key, []) if now - at < FAILURE_WINDOW_SECONDS]
        recent.append(now)
        self._failures[key] = recent
        return max(0, MAX_FAILED_ATTEMPTS - len(recent))

    def lockout_seconds_left(self, user_id):
        """How long this user must wait before trying again. 0 when free."""
        key = str(user_id)
        now = self._clock()
        recent = [at for at in self._failures.get(key, []) if now - at < FAILURE_WINDOW_SECONDS]
        self._failures[key] = recent
        if len(recent) < MAX_FAILED_ATTEMPTS:
            return 0
        return max(0, int(LOCKOUT_SECONDS - (now - recent[-1])))

    def is_locked_out(self, user_id):
        return self.lockout_seconds_left(user_id) > 0

    def clear_failures(self, user_id):
        self._failures.pop(str(user_id), None)


# ── storage ──────────────────────────────────────────────────────────


def store_key(plaintext, created_by=None):
    """Replace the stored key with the hash of ``plaintext``."""
    from .database import connect, init_database, utc_now

    init_database()
    key_hash, salt = hash_key(plaintext)
    with connect() as connection:
        connection.execute("DELETE FROM admin_key")
        connection.execute(
            "INSERT INTO admin_key (id, key_hash, salt, created_at, created_by)"
            " VALUES (1, ?, ?, ?, ?)",
            (key_hash, salt, utc_now(), str(created_by) if created_by else None),
        )
        connection.commit()
    return True


def stored_key_record():
    """The stored key row as a dict, or None when no key was ever set."""
    from .database import connect, init_database

    init_database()
    with connect() as connection:
        row = connection.execute(
            "SELECT key_hash, salt, created_at, created_by FROM admin_key WHERE id = 1"
        ).fetchone()
    return dict(row) if row else None


def key_is_configured():
    return stored_key_record() is not None


def check_key(plaintext):
    """True when ``plaintext`` matches the stored key."""
    record = stored_key_record()
    if not record:
        return False
    return verify_key(plaintext, record["key_hash"], record["salt"])


# ── audit ────────────────────────────────────────────────────────────


def record_audit(actor_id, action, *, actor_name=None, target=None, outcome="ok", detail=None):
    """Append one privileged action to the audit trail.

    Never raises: a failed audit write must not abort the action the operator
    asked for, but it must be visible in the logs.
    """
    from .database import connect, init_database, utc_now

    try:
        init_database()
        with connect() as connection:
            connection.execute(
                "INSERT INTO admin_audit"
                " (created_at, actor_id, actor_name, action, target, outcome, detail)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    utc_now(),
                    str(actor_id),
                    str(actor_name) if actor_name else None,
                    str(action),
                    str(target) if target else None,
                    str(outcome),
                    str(detail) if detail else None,
                ),
            )
            connection.commit()
        return True
    except Exception as error:  # pragma: no cover - defensive
        log.warning(f"Admin audit write failed for {action!r}: {error!r}", exc_info=True)
        return False


def recent_audit(limit=20):
    """Newest privileged actions first."""
    from .database import connect, init_database

    init_database()
    limit = max(1, min(int(limit or 20), 100))
    with connect() as connection:
        rows = connection.execute(
            "SELECT created_at, actor_id, actor_name, action, target, outcome, detail"
            " FROM admin_audit ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


# ── policy ───────────────────────────────────────────────────────────


# One set of unlocks for the whole process, so /admin unlock in the admin cog
# also opens the /backup group that lives in the setup cog.
SESSIONS = AdminSessions()

# Why a privileged command was refused. The cog turns these into messages;
# keeping the decision here makes it testable without Discord.
GATE_OK = "ok"
GATE_NOT_OWNER = "not_owner"
GATE_NO_KEY = "no_key"
GATE_LOCKED_OUT = "locked_out"
GATE_LOCKED = "locked"


def gate_state(is_owner, user_id, *, sessions=None, key_configured=None):
    """Decide whether a privileged command may run.

    Owner first, then the key. A non-owner is never told whether a key
    exists, and never learns that the key is the second factor at all.
    """
    sessions = SESSIONS if sessions is None else sessions
    if not is_owner:
        return GATE_NOT_OWNER
    configured = key_is_configured() if key_configured is None else key_configured
    if not configured:
        return GATE_NO_KEY
    if sessions.is_locked_out(user_id):
        return GATE_LOCKED_OUT
    if not sessions.is_unlocked(user_id):
        return GATE_LOCKED
    return GATE_OK


def env_owner_ids():
    """Extra owner ids from BOT_OWNER_IDS, for team setups or break-glass.

    The Discord application owner is still the primary check; this only adds
    to it, and an empty or malformed value simply adds nobody.
    """
    raw = os.getenv("BOT_OWNER_IDS", "")
    ids = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(part)
    return ids
