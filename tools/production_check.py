#!/usr/bin/env python3
"""Audit launch-critical configuration and private state on the live host."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config_check import CRITICAL, OK, WARN  # noqa: E402
from core.production_check import production_findings  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="also return failure when warnings remain",
    )
    args = parser.parse_args()
    findings = production_findings()
    order = {CRITICAL: 0, WARN: 1, OK: 2}
    icons = {CRITICAL: "FAIL", WARN: "WARN", OK: " OK "}
    for finding in sorted(findings, key=lambda item: (order[item.level], item.name)):
        print(f"[{icons[finding.level]}] {finding.name}: {finding.detail}")
    critical = sum(item.level == CRITICAL for item in findings)
    warnings = sum(item.level == WARN for item in findings)
    if critical or (args.strict and warnings):
        print(f"NOT READY: {critical} critical, {warnings} warning(s)")
        return 1
    print(f"READY: no critical findings ({warnings} warning(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
