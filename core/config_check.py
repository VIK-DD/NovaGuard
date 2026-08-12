"""Startup sanity checks for the environment NovaGuard was handed.

Every check here exists because the setting fails *quietly*. A missing token
stops the bot immediately and needs no help; an empty backup destination lets
the bot run happily for months and only reveals itself the day a host is lost
and the archives everyone assumed were in the cloud turn out to be on the
disk that just died.

The checks are pure functions over a mapping so the whole report can be
tested without a bot, a network or a filesystem. Only setting *names* are
ever printed, never their values.
"""

import os
from pathlib import Path

CRITICAL = "CRITICAL"
WARN = "WARN"
OK = "OK"

LAVALINK_BACKENDS = {"lavalink", "lava", "ll"}
KNOWN_BACKENDS = LAVALINK_BACKENDS | {"yt-dlp", "ytdlp", "yt_dlp", ""}
DEFAULT_LAVALINK_PASSWORD = "youshallnotpass"


class Finding:
    """One check result. ``detail`` says what to do, not just what is wrong."""

    __slots__ = ("level", "name", "detail")

    def __init__(self, level, name, detail):
        self.level = level
        self.name = name
        self.detail = detail

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"Finding({self.level}, {self.name}, {self.detail!r})"

    def __eq__(self, other):
        return (
            isinstance(other, Finding)
            and (self.level, self.name, self.detail) == (other.level, other.name, other.detail)
        )


def _value(env, name):
    return (env.get(name) or "").strip()


def _enabled(env, name, default=False):
    raw = _value(env, name).lower()
    if not raw:
        return bool(default)
    return raw not in {"0", "false", "no", "off"}


def check_config(env=None, *, file_exists=None):
    """Inspect the environment and return findings worth printing.

    ``file_exists`` is injected so path checks stay testable.
    """
    env = os.environ if env is None else env
    exists = file_exists if file_exists is not None else (lambda path: Path(path).expanduser().exists())
    findings = []

    if not _value(env, "TOKEN"):
        findings.append(Finding(CRITICAL, "TOKEN", "not set - the bot cannot log in to Discord."))
    else:
        findings.append(Finding(OK, "TOKEN", "present."))

    if not _value(env, "GUILD_ID"):
        findings.append(
            Finding(
                WARN,
                "GUILD_ID",
                "not set - new slash commands sync globally and can take up to an hour to appear.",
            )
        )

    # The one that turns a recoverable outage into data loss.
    if not _value(env, "BACKUP_REMOTE_DEST"):
        findings.append(
            Finding(
                WARN,
                "BACKUP_REMOTE_DEST",
                "empty - backups stay on this host only. Losing the host loses every backup with it. "
                "See docs/DISASTER-RECOVERY.md.",
            )
        )
    else:
        findings.append(Finding(OK, "BACKUP_REMOTE_DEST", "off-site backup destination configured."))

    backup_key = _value(env, "BACKUP_ENCRYPTION_KEY")
    if len(backup_key.encode("utf-8")) < 32:
        findings.append(
            Finding(
                CRITICAL,
                "BACKUP_ENCRYPTION_KEY",
                "missing or shorter than 32 characters - private backups cannot be created or restored.",
            )
        )
    else:
        findings.append(Finding(OK, "BACKUP_ENCRYPTION_KEY", "configured for encrypted archives."))

    backend = _value(env, "MUSIC_BACKEND").lower()
    if backend and backend not in KNOWN_BACKENDS:
        findings.append(
            Finding(
                WARN,
                "MUSIC_BACKEND",
                f"unknown value {backend!r} - falling back to the in-process yt-dlp player.",
            )
        )

    if backend in LAVALINK_BACKENDS:
        password = _value(env, "LAVALINK_PASSWORD")
        if not password or password == DEFAULT_LAVALINK_PASSWORD:
            findings.append(
                Finding(
                    WARN,
                    "LAVALINK_PASSWORD",
                    "still the documented default - anyone who can reach the node port can drive playback.",
                )
            )
        try:
            import wavelink  # noqa: F401
        except ModuleNotFoundError:
            findings.append(
                Finding(
                    CRITICAL,
                    "wavelink",
                    "MUSIC_BACKEND=lavalink but wavelink is not installed. "
                    "Run: venv/bin/pip install -r requirements.txt",
                )
            )

    cookies_file = _value(env, "MUSIC_YTDLP_COOKIES_FILE")
    if cookies_file and not exists(cookies_file):
        findings.append(
            Finding(
                WARN,
                "MUSIC_YTDLP_COOKIES_FILE",
                f"points at {cookies_file} which does not exist - yt-dlp runs without cookies.",
            )
        )

    proxy = _value(env, "MUSIC_YTDLP_PROXY")
    if proxy and not proxy.lower().startswith(("http://", "https://")):
        findings.append(
            Finding(
                WARN,
                "MUSIC_YTDLP_PROXY",
                "is not an http(s) URL - FFmpeg cannot stream YouTube through it and playback will 403.",
            )
        )

    if _enabled(env, "WEB_ENABLED"):
        if not _value(env, "WEB_TOKEN_KEY") and not _value(env, "DISCORD_CLIENT_SECRET"):
            findings.append(
                Finding(
                    WARN,
                    "WEB_TOKEN_KEY",
                    "empty while the web server is on - dashboard sessions cannot be signed.",
                )
            )
        if not _enabled(env, "WEB_COOKIE_SECURE"):
            findings.append(
                Finding(
                    WARN,
                    "WEB_COOKIE_SECURE",
                    "off while the web server is on - dashboard cookies travel unprotected over plain HTTP.",
                )
            )

    return findings


def problems(findings):
    return [finding for finding in findings if finding.level != OK]


def format_report(findings):
    """Render findings for the startup log, worst first, OK lines last."""
    order = {CRITICAL: 0, WARN: 1, OK: 2}
    ranked = sorted(findings, key=lambda finding: order.get(finding.level, 1))
    return [f"[config] {finding.level:<8} {finding.name}: {finding.detail}" for finding in ranked]


def report_config(env=None, printer=print):
    """Print the startup report. Returns the findings for callers that care."""
    findings = check_config(env)
    for line in format_report(findings):
        printer(line)
    trouble = problems(findings)
    if trouble:
        printer(
            f"[config] {len(trouble)} item(s) need attention. "
            "The bot still starts; see docs/DISASTER-RECOVERY.md and SETUP.md."
        )
    return findings
