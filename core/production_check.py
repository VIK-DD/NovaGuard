"""Fail-closed launch checks for the NovaGuard production host."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from . import backups
from .config import BASE_DIR
from .config_check import CRITICAL, OK, WARN, Finding, check_config
from .database import DB_PATH
from .privacy_ledger import PrivacyLedgerError, load_deletion_ledger
from .secure_files import SecureFileError


LEGAL_FIELDS = (
    "LEGAL_OPERATOR_NAME",
    "LEGAL_OPERATOR_ADDRESS",
    "LEGAL_OPERATOR_COUNTRY",
    "PRIVACY_CONTACT_EMAIL",
    "LEGAL_HOSTING_PROVIDER",
    "LEGAL_HOSTING_REGION",
    "LEGAL_BACKUP_PROVIDER",
    "LEGAL_BACKUP_LOCATION",
    "LEGAL_SUPERVISORY_AUTHORITY_URL",
)
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_HTTPS_URL = re.compile(r"^https://[^\s/]+(?:/[^\s]*)?$")
_TRUE_VALUES = {"1", "true", "yes", "on"}


def _operator_attestation_finding(env, name, requirement):
    confirmed = str(env.get(name) or "").strip().lower() in _TRUE_VALUES
    if confirmed:
        return Finding(
            OK,
            name,
            "operator attestation is present; retain the supporting configuration evidence.",
        )
    return Finding(
        CRITICAL,
        name,
        f"not attested - retain {requirement}, then set this variable to true.",
    )


def _mode_is_private(path):
    try:
        return path.stat().st_mode & 0o077 == 0
    except OSError:
        return False


def _database_findings(db_path):
    db_path = Path(db_path)
    if not db_path.is_file():
        return [Finding(CRITICAL, "database", "missing - production state is unavailable.")]
    findings = []
    try:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        finally:
            connection.close()
    except sqlite3.Error as error:
        return [Finding(CRITICAL, "database", f"cannot be validated: {error}")]
    if not integrity or integrity[0] != "ok":
        findings.append(Finding(CRITICAL, "database", "SQLite integrity check failed."))
    elif foreign_keys:
        findings.append(
            Finding(CRITICAL, "database", f"contains {len(foreign_keys)} foreign-key violation(s).")
        )
    else:
        findings.append(Finding(OK, "database", "SQLite integrity and foreign keys are clean."))
    if not _mode_is_private(db_path):
        findings.append(Finding(CRITICAL, "database permissions", "must be owner-only (chmod 600)."))
    return findings


def _backup_findings(backup_dir, *, now=None):
    backup_dir = Path(backup_dir)
    candidates = []
    for pattern in backups.BACKUP_PATTERNS:
        candidates.extend(backup_dir.glob(pattern) if backup_dir.is_dir() else ())
    candidates = sorted(
        {path.resolve() for path in candidates if path.is_file()},
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return [Finding(CRITICAL, "latest backup", "missing - create and verify one before launch.")], None

    latest = candidates[0]
    report = backups.inspect_backup(latest)
    findings = []
    if not report.get("encrypted"):
        findings.append(Finding(CRITICAL, "latest backup", "is legacy plaintext."))
    elif not report.get("ok"):
        findings.append(Finding(CRITICAL, "latest backup", "failed authentication or integrity checks."))
    else:
        findings.append(Finding(OK, "latest backup", "encrypted and verified."))
    now = now or datetime.now(UTC)
    modified = datetime.fromtimestamp(latest.stat().st_mtime, tz=UTC)
    age_seconds = max(0, (now - modified).total_seconds())
    if age_seconds > backups.backup_max_expected_age_seconds():
        findings.append(Finding(CRITICAL, "backup freshness", "latest archive is older than its schedule allows."))
    else:
        findings.append(Finding(OK, "backup freshness", "latest archive is within the expected window."))
    if not _mode_is_private(latest):
        findings.append(Finding(CRITICAL, "backup permissions", "must be owner-only (chmod 600)."))
    return findings, latest


def _remote_findings(env, backup_dir, latest):
    if not (env.get("BACKUP_REMOTE_DEST") or "").strip():
        return [Finding(CRITICAL, "off-site backup", "destination is not configured.")]
    state_path = Path(backup_dir) / backups.OFFSITE_STATE_FILENAME
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return [Finding(CRITICAL, "off-site backup", "no valid upload verification state exists.")]
    remote = state.get("latest") if isinstance(state.get("latest"), dict) else {}
    check = remote.get("check") if isinstance(remote.get("check"), dict) else {}
    expected_name = latest.name if latest else None
    if not remote.get("ok") or not check.get("ok") or remote.get("backup_name") != expected_name:
        return [
            Finding(
                CRITICAL,
                "off-site backup",
                "latest local archive is not confirmed in remote storage.",
            )
        ]
    return [Finding(OK, "off-site backup", "latest archive is confirmed remotely.")]


def production_findings(
    env=None,
    *,
    base_dir=BASE_DIR,
    db_path=DB_PATH,
    backup_dir=None,
    now=None,
):
    env = os.environ if env is None else env
    base_dir = Path(base_dir)
    backup_dir = Path(backup_dir or (base_dir / "backups"))
    findings = list(check_config(env))

    if str(env.get("WEB_ENABLED") or "").strip().lower() not in {"1", "true", "yes", "on"}:
        findings.append(Finding(CRITICAL, "WEB_ENABLED", "dashboard API is disabled."))

    for name in LEGAL_FIELDS:
        if not (env.get(name) or "").strip():
            findings.append(Finding(CRITICAL, name, "missing - public legal notices are incomplete."))
    email = (env.get("PRIVACY_CONTACT_EMAIL") or "").strip()
    if email and not _EMAIL.fullmatch(email):
        findings.append(Finding(CRITICAL, "PRIVACY_CONTACT_EMAIL", "is not a valid contact email."))
    authority_url = (env.get("LEGAL_SUPERVISORY_AUTHORITY_URL") or "").strip()
    if authority_url and not _HTTPS_URL.fullmatch(authority_url):
        findings.append(
            Finding(
                CRITICAL,
                "LEGAL_SUPERVISORY_AUTHORITY_URL",
                "must be an absolute HTTPS URL.",
            )
        )

    findings.append(
        _operator_attestation_finding(
            env,
            "HOST_STORAGE_ENCRYPTION_CONFIRMED",
            "current provider/volume encryption evidence",
        )
    )
    findings.append(
        _operator_attestation_finding(
            env,
            "API_EDGE_RATE_LIMIT_CONFIRMED",
            "a current Cloudflare WAF/rate-limit rule or equivalent edge configuration "
            "covering the public dashboard API",
        )
    )

    env_path = base_dir / ".env"
    if not env_path.is_file():
        findings.append(Finding(WARN, ".env", "not present; verify PM2 supplies every required variable."))
    elif not _mode_is_private(env_path):
        findings.append(Finding(CRITICAL, ".env permissions", "must be owner-only (chmod 600)."))
    else:
        findings.append(Finding(OK, ".env permissions", "owner-only."))

    findings.extend(_database_findings(db_path))

    ledger_path = base_dir / ".privacy_deletions.json"
    try:
        load_deletion_ledger(ledger_path, require=True)
    except (OSError, PrivacyLedgerError, SecureFileError):
        findings.append(
            Finding(
                CRITICAL,
                "deletion ledger",
                "cannot be authenticated with the configured backup key.",
            )
        )
    else:
        if _mode_is_private(ledger_path):
            findings.append(Finding(OK, "deletion ledger", "authenticated and owner-only."))
        else:
            findings.append(Finding(CRITICAL, "deletion ledger", "must be owner-only (chmod 600)."))

    backup_findings, latest = _backup_findings(backup_dir, now=now)
    findings.extend(backup_findings)
    findings.extend(_remote_findings(env, backup_dir, latest))
    return findings
