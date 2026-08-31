"""Refuse to ship a credential that was committed by accident.

The repository's history is clean today - 464 commits, no `.env` ever tracked,
no token in a diff. Nothing was keeping it that way. Every other class of
regression here has a test or a CI gate behind it; this one had the fact that
nobody had made the mistake yet.

Why this and not an off-the-shelf scanner: the general ones match on entropy,
and this tree is full of high-entropy strings that are not secrets - Fernet
tokens in test fixtures, SHA-256 CSP hashes in `worker/inline-hashes.js`,
`--generate-hashes` lines in `requirements.lock`. A scanner that flags those
gets an exclusion list, then a bigger one, then it gets switched off. The
project already wrote that lesson down in deploy-website.yml: a gate that
cries wolf does not survive.

So these patterns are shape-based, not entropy-based. Every one of them
matches a credential format that a specific provider issues and nothing else
looks like. A real hit is a real secret, which is what makes it worth failing
a build over.

Usage:
    python scripts/scan_secrets.py            # working tree (tracked files)
    python scripts/scan_secrets.py --history  # every line ever added, too
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# (name, pattern). Anchored on the issuer's own prefix and length wherever the
# provider publishes one, so a match is a credential rather than a coincidence.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Discord bot token: base64 user id "." timestamp "." hmac
    ("Discord bot token", re.compile(r"\b[MNO][A-Za-z0-9_-]{23,25}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,40}\b")),
    ("Discord webhook", re.compile(r"https://(?:\w+\.)?discord(?:app)?\.com/api/webhooks/\d{17,20}/[\w-]{60,}")),
    ("GitHub personal access token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{70,}\b")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("OpenAI API key", re.compile(r"\bsk-proj-[A-Za-z0-9_-]{20,}")),
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}")),
    ("Cloudflare API token", re.compile(r"\bv1\.0-[A-Za-z0-9_-]{30,}")),
    ("Private key block", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----")),
    # Publishing credentials. Neither ecosystem is published to from here
    # today, which is exactly when a token gets pasted somewhere to try it.
    ("npm access token", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    ("PyPI API token", re.compile(r"\bpypi-AgEIcHlwaS5vcmc[A-Za-z0-9_-]{50,}")),
    # A webhook URL is a credential: anyone holding it can post as the app.
    # Distinct from the xox* bot tokens above, which this used to be alone in
    # covering.
    ("Slack webhook", re.compile(r"https://hooks\.slack\.com/services/T[A-Za-z0-9_]+/B[A-Za-z0-9_]+/[A-Za-z0-9]{20,}")),
    ("Stripe secret key", re.compile(r"\b[sr]k_live_[A-Za-z0-9]{20,}\b")),
    ("SendGrid API key", re.compile(r"\bSG\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}")),
    # A signed JWT carries its own header, so the shape is unambiguous: the
    # first segment always decodes from {"alg": ... and starts eyJ.
    ("JSON Web Token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{20,}")),
    # A connection string with the password inline. `//user:pass@host` is
    # unambiguous enough to match on, and it is how a database credential
    # usually escapes: not as a token, as a URL in a config file.
    (
        "Database URL with credentials",
        re.compile(
            r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|rediss|amqps?|mssql)://"
            r"[^\s:/@]+:[^\s:/@]{6,}@"
        ),
    ),
)

# NovaGuard's own secrets are random bytes with no issuer prefix - nothing
# about `WEB_TOKEN_KEY`'s value distinguishes it from any other base64 string,
# so no shape rule can find it. They are also the highest-value secrets in the
# system: the key that decrypts OAuth tokens at rest, the one that signs gate
# cookies, the one that encrypts backups.
#
# What is recognisable is the *name* next to the value. A scanner keyed on the
# variable name catches the way these actually leak - a real `.env` pasted into
# a doc, a debug line, a config example filled in with live values - without
# the entropy heuristics this file argues against, because the name makes the
# match specific rather than statistical.
OWN_SECRET_NAMES = (
    "TOKEN",
    "DISCORD_CLIENT_SECRET",
    "WEB_TOKEN_KEY",
    "GATE_SIGNING_KEY",
    "AUTH_PASSWORD",
    "BACKUP_ENCRYPTION_KEY",
    "LITESTREAM_SECRET_ACCESS_KEY",
    "ADMIN_KEY",
    "ADMIN_KEY_HASH",
    "GITHUB_TOKEN",
    "ANTHROPIC_API_KEY",
)

ASSIGNED_SECRET = re.compile(
    r"\b(" + "|".join(OWN_SECRET_NAMES) + r")\s*[:=]\s*[\"']?([^\s\"'#,)]{16,})"
)

# Values that are obviously not a live credential. Kept deliberately short:
# every entry here is a hole, so each one has to earn its place.
_PLACEHOLDER_HINTS = (
    "your_", "_here", "example", "changeme", "change-me", "placeholder", "redacted",
    "xxxxx", "...", "<", "${", "$(", "openssl", "secrets.", "env.", "os.getenv",
    "getenv", "sha256", "base64", "random", "generate", "dummy", "fake", "test",
)


def _is_placeholder(value):
    # Hyphens and underscores are interchangeable in the wild: `your-key-here`
    # and `your_key_here` are the same placeholder written by two people.
    lowered = value.lower().replace("-", "_")
    if any(hint.replace("-", "_") in lowered for hint in _PLACEHOLDER_HINTS):
        return True
    # "aaaaaaaaaaaaaaaa" and friends: a filler, not a key.
    return len(set(value)) <= 4


def _assigned_secret_kind(line):
    match = ASSIGNED_SECRET.search(line)
    if not match:
        return None
    name, value = match.group(1), match.group(2)
    if _is_placeholder(value):
        return None
    return f"{name} assigned a literal value"

# Paths whose whole job is to contain credential-shaped strings.
EXCLUDED_PATHS = frozenset({
    "scripts/scan_secrets.py",
    "tests/test_scan_secrets.py",
})

# Binary and generated files that cannot usefully be read as source lines.
EXCLUDED_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".pdf", ".bundle")


class Finding:
    def __init__(self, kind, location, line_number, line):
        self.kind = kind
        self.location = location
        self.line_number = line_number
        # Never print the match itself: a scanner that echoes the secret into
        # a public CI log has leaked it a second time.
        self.line = line

    def __str__(self):
        return f"{self.location}:{self.line_number}: possible {self.kind}"


def scan_text(text, location, *, start_line=1, added_only=False):
    """Scan lines for credential shapes.

    In `added_only` mode the text is a git diff and only added lines count. The
    `+++ b/<path>` headers are tracked as they go past so EXCLUDED_PATHS means
    the same thing here as in the working tree - without that, the scanner
    reports its own test fixtures on every run, the job goes permanently red,
    and a permanently red job is one somebody turns off.
    """
    findings = []
    current_path = None
    for offset, line in enumerate(text.splitlines()):
        if added_only:
            if line.startswith("+++"):
                target = line[4:].strip()
                current_path = None if target == "/dev/null" else target.removeprefix("b/")
                continue
            if not line.startswith("+"):
                continue
            if current_path in EXCLUDED_PATHS:
                continue
            line = line[1:]
        where = f"{location}:{current_path}" if current_path else location
        for kind, pattern in PATTERNS:
            if pattern.search(line):
                findings.append(Finding(kind, where, start_line + offset, line))
        assigned = _assigned_secret_kind(line)
        if assigned:
            findings.append(Finding(assigned, where, start_line + offset, line))
    return findings


def tracked_files(root=REPO_ROOT):
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [name for name in listed.split("\0") if name]


def scan_working_tree(root=REPO_ROOT):
    findings = []
    for name in tracked_files(root):
        if name in EXCLUDED_PATHS or name.endswith(EXCLUDED_SUFFIXES):
            continue
        path = root / name
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # binary or unreadable: nothing a line scanner can say
        findings.extend(scan_text(text, name))
    return findings


def scan_history(root=REPO_ROOT):
    """Every line ever added on any branch.

    A secret removed in a later commit is still a secret: the object stays in
    the history and anyone who clones gets it. Rotating is the only real fix,
    so the point of this pass is to find out that rotation is needed.
    """
    diff = subprocess.run(
        ["git", "-C", str(root), "log", "--all", "-p", "--no-color", "--", "."],
        capture_output=True, text=True, check=True, errors="replace",
    ).stdout
    return scan_text(diff, "history", added_only=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true", help="also scan every commit")
    args = parser.parse_args(argv)

    findings = scan_working_tree()
    if args.history:
        findings.extend(scan_history())

    if not findings:
        scope = "working tree and full history" if args.history else "working tree"
        print(f"scan_secrets: no credentials found in the {scope}.")
        return 0

    print("scan_secrets: possible credentials found.\n", file=sys.stderr)
    for finding in findings:
        print(f"  {finding}", file=sys.stderr)
    print(
        "\nIf any of these is real, rotating it is the fix - removing the line is not."
        "\nA committed secret stays reachable in the history of every clone.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
