<div align="center">

<img src="docs/assets/logo.png" alt="NovaGuard logo" width="170"/>

# NovaGuard

### A premium, self-hosted Discord bot for communities that want style, automation and real control.

Beautiful slash commands, streaming presence, setup wizard, GitHub intelligence,
automatic changelogs, moderation, economy, tickets, giveaways, role panels, health
checks and Raspberry Pi-friendly deployment in one polished Python bot.

<br/>

[![Version](https://img.shields.io/badge/version-3.0.0-0f766e)](https://github.com/VIK-DD/NovaGuard/releases/latest)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![discord.py](https://img.shields.io/badge/discord.py-2.6+-5865F2)](https://discordpy.readthedocs.io/)
[![SQLite](https://img.shields.io/badge/SQLite-config%20%2B%20state-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![PM2](https://img.shields.io/badge/PM2-keep%20alive-2B037A?logo=pm2&logoColor=white)](https://pm2.keymetrics.io/)
[![Runs on Raspberry Pi](https://img.shields.io/badge/runs%20on-Raspberry%20Pi-A22846?logo=raspberrypi&logoColor=white)](#-running-on-a-raspberry-pi)
[![CI](https://img.shields.io/github/actions/workflow/status/VIK-DD/NovaGuard/ci.yml?branch=main&label=CI)](https://github.com/VIK-DD/NovaGuard/actions/workflows/ci.yml)

[![Slash commands](https://img.shields.io/badge/slash%20commands-62+-5865F2)](#-command-categories)
[![GitHub feed](https://img.shields.io/badge/GitHub-feed%20%2B%20cards-181717?logo=github&logoColor=white)](#-github-intelligence)
[![Auto updates](https://img.shields.io/badge/auto-changelogs-live-0891B2)](#-automatic-updates)
[![Health checks](https://img.shields.io/badge/doctor-health%20alerts-DC2626)](#-health-monitoring--backups)
[![AI](https://img.shields.io/badge/AI-Claude%20optional-D97706)](#-ai-assistant-optional)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

<br/>

</div>

---

> [!NOTE]
> **Language.** The bot codebase and slash commands are written in **English** for a clean public repository, but the bot was built with a real Romanian community workflow in mind and runs perfectly on lightweight home-hosted setups.

## Table of contents

- [Features](#-features)
- [Tech stack](#-tech-stack)
- [Quick start (local)](#-quick-start-local)
- [Running on a Raspberry Pi](#-running-on-a-raspberry-pi)
- [Environment configuration](#-environment-configuration)
- [Setup flow](#-setup-flow)
- [Command categories](#-command-categories)
- [GitHub intelligence](#-github-intelligence)
- [Automatic updates](#-automatic-updates)
- [Health, monitoring & backups](#-health-monitoring--backups)
- [AI assistant (optional)](#-ai-assistant-optional)
- [Project structure](#-project-structure)
- [Roadmap](#-roadmap)
- [Contributing](#-contributing)
- [License](#-license)

---

## Features

#### Community management
- Slash-native moderation with `/purge`, `/kick`, `/ban`, `/timeout`, `/warn`.
- Welcome/goodbye cards, auto-role support and server log channels.
- Tickets, giveaways and self-role panels with persistent views where it matters.

#### Setup that feels modern
- `/setup` opens a real setup wizard with select menus, channel picker and quick buttons.
- `/config view`, `/config export`, `/config backup`, `/config reset` keep admin work clean and centralized.
- Per-server settings live in SQLite, not in a pile of fragile environment variables.

#### Rich server experience
- Public `/status`, private `/doctor`, polished `/help`, rotating streaming presence.
- Fun, utility, economy and level systems built to feel playful without becoming messy.
- Auto-generated update embeds so every deploy can announce itself professionally.

#### GitHub-aware developer layer
- `/github`, `/repo`, `/dev`, `/health`, `/commits`, `/release`, `/ghwatch`.
- GitHub feed posts pushes, pull requests, issues and releases to Discord.
- Startup changelogs detect real code changes and generate release notes automatically.

#### Raspberry Pi friendly
- Python + SQLite + PM2 deployment that works well on a Pi without needing heavyweight services.
- Automatic backups, health alerts and event-loop monitoring.
- Built around real home-server usage, not cloud-only assumptions.

---

## Tech stack

| Layer | Choice |
| --- | --- |
| Runtime | Python 3.11+ |
| Discord library | `discord.py` 2.6+ |
| HTTP | `aiohttp` |
| State | SQLite + JSON for selected feature data |
| Hosting | Raspberry Pi, VPS, or any Linux box |
| Process manager | PM2 |
| Optional AI | Anthropic Claude |

#### Why SQLite here?

NovaGuard is meant to be **easy to run and easy to keep alive**. SQLite removes the
need for a separate database server while still giving us structured persistence for:

- guild setup/config
- levels
- economy wallets
- future migrations

That makes the bot especially comfortable on a Raspberry Pi.

---

## Quick start (local)

Requires **Python 3.11+**.

```bash
# 1. Install dependencies
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env

# 3. Run the bot
python bot.py
```

If you set `GUILD_ID`, slash commands sync instantly to that one server.

---

## Running on a Raspberry Pi

Tested around the workflow of a real Raspberry Pi deployment with PM2.

<details>
<summary><b>1. Install Python tools</b></summary>

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
```
</details>

<details>
<summary><b>2. Create the virtual environment</b></summary>

```bash
cd ~/pythonbot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
```
</details>

<details>
<summary><b>3. Start with PM2</b></summary>

```bash
pm2 start /home/pi/pythonbot/bot.py --name pythonbot --interpreter /home/pi/pythonbot/.venv/bin/python
pm2 save
pm2 startup
```
</details>

<details>
<summary><b>4. Read fresh logs</b></summary>

```bash
pm2 logs pythonbot --lines 80
```
</details>

> Tip: never upload `.venv` from macOS to a Raspberry Pi. Rebuild the virtualenv on the Pi itself.

---

## Environment configuration

NovaGuard loads `.env` automatically at startup.

| Variable | Required | Purpose |
| --- | --- | --- |
| `TOKEN` | Yes | Discord bot token |
| `GUILD_ID` | Recommended | Instant slash-command sync in one server |
| `GITHUB_USERNAME` | Optional | GitHub profile used by GitHub commands |
| `GITHUB_PRIMARY_REPO` | Optional | Main repository used by repo/dev/health cards |
| `GITHUB_WATCH_REPOS` | Optional | Comma-separated repo list for GitHub feed |
| `GITHUB_TOKEN` | Optional | Better GitHub API limits and reliability |
| `UPDATE_CHANNEL_ID` | Optional | Fallback update channel for the main guild |
| `GITHUB_EVENT_CHANNEL_ID` | Optional | Fallback GitHub feed channel |
| `ERROR_LOG_CHANNEL_ID` | Optional | Fallback admin error digest channel |
| `UPTIME_URL` | Optional | Link used in status/developer cards |
| `BOT_BRAND` | Optional | Embed footer branding |
| `STREAM_STATUSES` | Optional | Pipe-separated rotating streaming texts |
| `ANTHROPIC_API_KEY` | Optional | Enables `/ask` |
| `ANTHROPIC_MODEL` | Optional | Claude model override |

See [.env.example](.env.example) for a clean starter file.

---

## Setup flow

NovaGuard is designed so admins can do most setup **inside Discord**, not by editing files forever.

1. Run `/setup`
2. Pick what you want to configure
3. Choose the right channel from the dropdown
4. Use `/config view` to review everything
5. Use `/doctor` to verify health, permissions and integrations

The bot stores server config in `data/novaguard.sqlite3`, while keeping optional
`.env` fallback values for your main server.

---

## Command categories

| Category | Highlights |
| --- | --- |
| Setup | `/setup`, `/config view`, `/config export`, `/config backup`, `/config reset` |
| System | `/ping`, `/uptime`, `/status`, `/botinfo`, `/doctor`, `/help`, `/latest`, `/updates`, `/forceupdate` |
| Developer | `/github`, `/repo`, `/dev`, `/health`, `/commits`, `/release`, `/ghwatch` |
| Utility | `/userinfo`, `/serverinfo`, `/avatar`, `/roleinfo`, `/poll`, `/remind`, `/reminders`, `/timestamp`, `/choose`, `/color` |
| Fun | `/8ball`, `/coinflip`, `/dice`, `/rps`, `/trivia`, `/joke`, `/ship`, `/vibecheck` |
| Moderation | `/purge`, `/kick`, `/ban`, `/timeout`, `/untimeout`, `/slowmode`, `/announce`, `/warn add`, `/warn list`, `/warn clear` |
| Levels | `/rank`, `/leaderboard` |
| Welcome | `/welcome set`, `/welcome off`, `/welcome test` |
| Logs | `/logs set`, `/logs off` |
| Roles | `/rolepanel` |
| Giveaways | `/giveaway start`, `/giveaway end`, `/giveaway reroll` |
| Tickets | `/ticketpanel` |
| AutoMod | `/automod status`, `/automod invites`, `/automod spam`, `/automod badword add`, `/automod badword remove`, `/automod badword list` |
| Economy | `/balance`, `/daily`, `/work`, `/pay`, `/gamble`, `/slots`, `/richest`, `/shop`, `/buy` |
| AI | `/ask` |

`/help` opens an interactive command hub with categories and polished embed pages.

---

## GitHub intelligence

NovaGuard treats GitHub as part of the bot experience, not an afterthought.

- GitHub profile cards for your public identity
- Repository cards with stars, workflow status, language mix and health signals
- Live event watcher for pushes, PRs, issues and releases
- Auto-generated update posts when the bot code changes
- Release timeline browsing with `/updates`

This makes it especially nice for dev communities, personal brands and project servers.

---

## Automatic updates

NovaGuard keeps a fingerprint of tracked files and can announce a real deploy with:

- release highlights
- command changes
- file-change stats
- build history
- restart summary embeds

The changelog system watches:

- `bot.py`
- `SETUP.md`
- `.env.example`
- every Python file in `core/`
- every Python file in `cogs/`

That means the bot can tell your server what changed without you writing a manual update post every single time.

---

## Health monitoring & backups

- `/doctor` checks latency, event-loop lag, config, permissions, JSON state, SQLite status and GitHub reachability.
- `/status` gives members a clean public summary without exposing admin details.
- Admin error digests can be routed into a private channel.
- Automatic backups run every 6 hours and keep the newest 10 archives in `backups/`.
- `/config backup` creates an immediate manual archive.

If the Raspberry Pi stalls briefly, NovaGuard can detect that and report it without falling apart.

---

## AI assistant (optional)

If `ANTHROPIC_API_KEY` is present, `/ask` lets members interact with Claude directly from Discord.

This is entirely optional:

- no key = bot still works normally
- key present = AI category becomes useful immediately

---

## Project structure

```text
bot.py                  entry point, startup checks, command sync
cogs/                   slash-command categories and event listeners
core/                   config, GitHub client, theme, storage, updates, backups
assets/                 local image assets used by the bot
docs/assets/            repository visuals for GitHub
data/                   SQLite DB + remaining feature JSON
backups/                scheduled and manual backup archives
SETUP.md                operational setup guide
requirements.txt        Python dependencies
```

---

## Roadmap

- [ ] Add a complete first-run onboarding embed for brand-new guilds
- [ ] Add richer repo analytics cards for `/dev`
- [ ] Add a clean deploy checklist command for Pi admins
- [ ] Add export/import utilities for more bot state
- [ ] Add optional web dashboard later if the project grows into it

---

## Contributing

Issues and pull requests are welcome. If you want to extend NovaGuard, keep the
same spirit as the current project:

- polished UX
- practical hosting
- elegant embeds
- real operational usefulness

Run the bot locally, verify the slash-command flow, and keep changes friendly to Raspberry Pi deployments.

---

<a id="-license"></a>

<h2 align="center">License</h2>

<p align="center">
  Licensed under the <strong>Apache License 2.0</strong> — see <a href="LICENSE"><strong>LICENSE</strong></a> for details.
</p>

<p align="center">
  <strong>Copyright © 2026 VIK-DD</strong>
</p>

<p align="center">
  <strong>Made to be calm, fast, and yours</strong> · Made in Moldova 🇲🇩
</p>
