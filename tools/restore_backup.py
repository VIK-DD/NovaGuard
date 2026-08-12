#!/usr/bin/env python3
"""Authenticate, decrypt and safely extract a NovaGuard backup."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.backups import extract_backup, inspect_backup  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="encrypted .ngbackup archive")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("backups/restore-check"),
        help="directory that will receive the decrypted archive contents",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="replace an existing non-empty output directory",
    )
    parser.add_argument(
        "--allow-plaintext",
        action="store_true",
        help="explicitly allow a legacy, unencrypted ZIP during migration",
    )
    args = parser.parse_args()

    report = inspect_backup(args.archive)
    if not report["ok"]:
        for error in report["errors"]:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if not report["encrypted"] and not args.allow_plaintext:
        print(
            "ERROR: legacy plaintext archive refused; use --allow-plaintext only for a trusted migration",
            file=sys.stderr,
        )
        return 1

    extract_backup(args.archive, args.output, replace=args.replace)
    print(f"Verified and extracted {args.archive.name} to {args.output}")
    print(f"Encryption: {'authenticated' if report['encrypted'] else 'legacy plaintext'}")
    print(f"SQLite integrity: {report.get('sqlite') or 'not included'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
