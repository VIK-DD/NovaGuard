#!/usr/bin/env python3
"""Export, verify or import a portable NovaGuard host migration."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.host_migration import (  # noqa: E402
    HostMigrationError,
    export_host_sql,
    import_host_sql,
    verify_host_sql,
)


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NovaGuard single-file host migration")
    commands = parser.add_subparsers(dest="command", required=True)

    export_parser = commands.add_parser("export", help="create one portable .sql file")
    export_parser.add_argument("--output", type=Path, help="custom output .sql path")

    verify_parser = commands.add_parser("verify", help="validate a .sql migration without importing it")
    verify_parser.add_argument("file", type=Path)

    import_parser = commands.add_parser("import", help="replace local state from a .sql migration")
    import_parser.add_argument("file", type=Path)
    import_parser.add_argument(
        "--confirm-replace",
        action="store_true",
        help="confirm that the current database may be replaced",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "export":
            result = export_host_sql(args.output)
            print(f"OK: {result['path']}")
            print(
                f"Size: {human_size(result['size'])} | "
                f"tables: {result['tables']} | auxiliary JSON: {result['auxiliary_files']}"
            )
            print("Secrets are not included: copy/configure .env separately.")
        elif args.command == "verify":
            result = verify_host_sql(args.file)
            print(f"OK: migration is valid ({result['path']})")
            print(
                f"Exported: {result['exported_at']} | "
                f"tables: {result['tables']} | rows: {result['rows']} | "
                f"auxiliary JSON: {result['auxiliary_files']} | size: {human_size(result['size'])}"
            )
        else:
            result = import_host_sql(args.file, confirm_replace=args.confirm_replace)
            print(f"OK: imported into {result['database']}")
            print(
                f"Restored: {result['tables']} tables | {result['rows']} rows | "
                f"{result['auxiliary_files']} auxiliary JSON"
            )
            if result["safety_backup"]:
                print(f"Previous state safety backup: {result['safety_backup']}")
            print("Start NovaGuard and run /doctor to finish the check.")
    except HostMigrationError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
