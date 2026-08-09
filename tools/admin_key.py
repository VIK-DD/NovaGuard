"""Generate or rotate the NovaGuard admin key.

Run on the host, as the user that owns the database:

    venv/bin/python -m tools.admin_key

The key is printed once and never again - only its hash reaches the
database. Put it in a password manager before closing the terminal. Losing it
costs nothing but a rotation; leaking it costs an attacker's worth of access,
which is why generating happens here on the host rather than through Discord,
where the value would pass through chat.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.admin_auth import generate_key, key_is_configured, store_key  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate or rotate the admin key.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing key (every open unlock is invalidated)",
    )
    parser.add_argument(
        "--note",
        default=None,
        help="optional label stored with the key, e.g. who generated it",
    )
    args = parser.parse_args(argv)

    if key_is_configured() and not args.force:
        print("An admin key already exists.")
        print("Rotate it with:  venv/bin/python -m tools.admin_key --force")
        print("Rotating invalidates the old key immediately.")
        return 1

    key = generate_key()
    store_key(key, created_by=args.note)

    print()
    print("=" * 66)
    print("  ADMIN KEY - shown once, never recoverable")
    print("=" * 66)
    print()
    print(f"  {key}")
    print()
    print("=" * 66)
    print("  Save it in your password manager now.")
    print("  Unlock with /admin unlock in a DM to the bot - never in a")
    print("  server channel, where the command shows up in the audit log.")
    print("=" * 66)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
