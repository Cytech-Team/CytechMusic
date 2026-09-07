# CytechMusic

Open-source Discord music bot powered by `discord.py`, Lavalink, MongoDB, and the bundled CytechLink audio client.

> [!IMPORTANT]
> **Project status: Revived / Maintenance Mode**
>
> CytechMusic has been reopened to keep the public release installable, compatible, secure, and maintainable. The revival focuses on bug fixes, dependency updates, code quality, documentation, and compatibility patches. Major new features are not planned here.
>
> **Cyori remains the active next-generation project.** CytechMusic is the public community edition and maintenance line.

[![Quality](https://github.com/Cytech-Team/CytechMusic/actions/workflows/quality.yml/badge.svg)](https://github.com/Cytech-Team/CytechMusic/actions/workflows/quality.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)

## Revival goals

- Keep the existing feature set working on supported Python and Discord/Lavalink stacks.
- Patch bugs, compatibility problems, and security issues.
- Clean technical debt where it can be done without changing expected behaviour.
- Improve automated checks and documentation.
- Keep self-hosting straightforward.
- Avoid feature creep and large rewrites; new product development belongs in Cyori.

## Features

### Music playback
- Lavalink-backed playback.
- YouTube, Spotify, SoundCloud, and other sources supported by the configured Lavalink node.
- Play, pause, skip, stop, seek, volume, loop, shuffle, and queue controls.
- Queue pagination, removal, and ordering tools.

### Audio filters
- Nightcore, Vaporwave, and 8D presets.
- Speed, karaoke, tremolo, vibrato, rotation, distortion, low-pass, and channel-mix controls.

### Server controls
- English and Thai language support.
- DJ role and DJ mode.
- Vote-gated features.
- 24/7 mode and autoplay.
- Dedicated music channel/controller setup.

### Dashboard and utilities
- Embedded web dashboard/API.
- Uptime, CPU/RAM, latency, and Lavalink status information.
- Dynamic help and bot information commands.

## Requirements

- Python 3.10+
- MongoDB
- Lavalink v3 or v4 compatible with the bundled CytechLink implementation
- FFmpeg where required by your deployment

## Installation

```bash
git clone https://github.com/Cytech-Team/CytechMusic.git
cd CytechMusic
python -m venv .venv
```

Activate the virtual environment and install dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Copy the environment template:

```bash
cp .env.example .env
```

Fill in at minimum your Discord bot token, MongoDB connection, and Lavalink connection details, then start the bot:

```bash
python main.py
```

> [!CAUTION]
> Never commit `.env`, bot tokens, API keys, database credentials, or webhook secrets. The provided `.gitignore` excludes common local environment files.

## Configuration

The complete public configuration template is in [`.env.example`](.env.example). Optional integrations such as Spotify, Top.gg, Stripe, remote logging, and cross-server role synchronisation can be left unset when unused.

For cross-server role synchronisation, configure `SOURCE_GUILD_ID` and `SYNC_ROLE_ID` only if you intentionally use that feature. The public template leaves both disabled by default.

## Tech stack

- `discord.py`
- MongoDB / Motor / PyMongo
- Lavalink + bundled CytechLink
- `aiohttp` web API/dashboard
- Optional Stripe, Spotify, Top.gg, and lyrics integrations

## Commands

| Command | Description |
| --- | --- |
| `/play [query]` | Play a song or playlist from a URL or search. |
| `/stop` | Stop playback and clear the queue. |
| `/skip` | Skip the current song. |
| `/pause` | Pause or resume playback. |
| `/volume [1-200]` | Adjust playback volume. |
| `/queue` | Show the current queue. |
| `/loop` | Toggle track/queue looping. |
| `/seek [time]` | Seek to a timestamp such as `1:30`. |
| `/nowplaying` | Show current track information and controls. |

## Maintenance policy

Accepted changes are primarily:

- bug fixes;
- compatibility patches;
- dependency/security updates;
- reliability and performance fixes;
- tests, CI, documentation, and safe refactors.

Large new features should target Cyori instead of expanding CytechMusic's scope again.

## Contributing

Pull requests are welcome. Please keep changes focused and preserve existing behaviour unless the change fixes a documented bug or compatibility issue.

## License

Distributed under the [MIT License](LICENSE).

---

Developed and maintained by **Cytech Team Development**.
