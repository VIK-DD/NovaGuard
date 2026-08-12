#!/usr/bin/env python3
"""Authenticate, decrypt and safely extract a NovaGuard backup."""

import argparse
import json
import shutil
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.backups import BACKUP_DIR, extract_backup, inspect_backup  # noqa: E402
from core.config import BASE_DIR  # noqa: E402
from core.privacy_ledger import (  # noqa: E402
    PrivacyLedgerError,
    apply_deletion_ledger,
    load_deletion_ledger,
)
from core.secure_files import SecureFileError, decrypt_file  # noqa: E402


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
    ledger_group = parser.add_mutually_exclusive_group()
    ledger_group.add_argument(
        "--ledger",
        type=Path,
        help="local plaintext deletion ledger (defaults to .privacy_deletions.json)",
    )
    ledger_group.add_argument(
        "--encrypted-ledger",
        type=Path,
        help="encrypted off-site deletion-ledger.json.ngbackup file",
    )
    parser.add_argument(
        "--allow-missing-deletion-ledger",
        action="store_true",
        help="dangerous: restore without protection against resurrection of erased data",
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

    extracted = False
    try:
        with ExitStack() as stack:
            ledger_path = args.ledger or (BASE_DIR / ".privacy_deletions.json")
            if args.encrypted_ledger:
                BACKUP_DIR.mkdir(parents=True, exist_ok=True)
                temp_dir = Path(
                    stack.enter_context(
                        tempfile.TemporaryDirectory(
                            prefix="novaguard-ledger-decrypt-", dir=BACKUP_DIR
                        )
                    )
                )
                ledger_path = temp_dir / "deletion-ledger.json"
                decrypt_file(args.encrypted_ledger, ledger_path)

            apply_ledger = ledger_path.is_file()
            if apply_ledger:
                load_deletion_ledger(ledger_path, require=True)
            elif not args.allow_missing_deletion_ledger:
                raise PrivacyLedgerError(
                    "deletion ledger is missing; restore refused to prevent erased data resurrection"
                )

            extract_backup(args.archive, args.output, replace=args.replace)
            extracted = True
            privacy_report = None
            if apply_ledger:
                manifest_path = args.output / ".backup_manifest.json"
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    manifest = {}
                privacy_report = apply_deletion_ledger(
                    args.output,
                    ledger_path=ledger_path,
                    snapshot_created_at=manifest.get("created_at"),
                )

        print(f"Verified and extracted {args.archive.name} to {args.output}")
        print(f"Encryption: {'authenticated' if report['encrypted'] else 'legacy plaintext'}")
        print(f"SQLite integrity: {report.get('sqlite') or 'not included'}")
        if privacy_report:
            print(
                "Privacy ledger: enforced "
                f"({privacy_report['removed_or_anonymised']} restored record reference(s) scrubbed)"
            )
        else:
            print("WARNING: deletion ledger was not applied")
        return 0
    except (OSError, SecureFileError, PrivacyLedgerError, ValueError) as error:
        if extracted:
            shutil.rmtree(args.output.resolve(), ignore_errors=True)
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
