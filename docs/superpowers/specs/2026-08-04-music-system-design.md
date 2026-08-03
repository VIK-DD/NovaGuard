# Music system — design

**Date:** 2026-08-04
**Status:** approved, ready for an implementation plan

## What we are building

Music playback for NovaGuard: `/play` with a link or a search, a queue, and a
player card driven by buttons. Audio comes from YouTube and SoundCloud. Spotify
links are understood but never streamed from — see *Sources* below.

## Sources, and what each one can actually do

| Source | Search | Audio | Notes |
|---|---|---|---|
| YouTube | via `yt-dlp` | yes | Serves webm/opus, so FFmpeg copies the stream instead of re-encoding it. Cheapest source by far. |
| SoundCloud | via `yt-dlp` | yes | Usually mp3, so it has to be transcoded to Opus. Real CPU cost. |
| Spotify | Web API (optional) | **no** | Streaming to third-party apps is not permitted and there is no API for it. A Spotify link is resolved to title/artist, then that track is found on YouTube or SoundCloud. |

Spotify degrades gracefully. With no credentials, a single-track link still
works through the public oEmbed endpoint. Adding `SPOTIFY_CLIENT_ID` and
`SPOTIFY_CLIENT_SECRET` additionally unlocks playlists and albums. Nothing
breaks when they are absent.

### Terms-of-service position

Extracting a YouTube audio stream with `yt-dlp` violates YouTube's terms of
service; the official Data API exposes metadata only. The bots that were shut
down (Groovy, Rythm, 2021) were very large and sold premium tiers for the music
feature itself. NovaGuard is self-hosted, serves 6 guilds, and sells nothing —
the operator has accepted this risk knowingly. The practical cost is not legal:
it is periodic IP blocks and `yt-dlp` breaking whenever YouTube changes
something, which means keeping it updated is ongoing maintenance.

## Constraints that shaped the design

The bot runs on a 2 GB VPS with roughly 1.4 GB free and 1–2 vCPU, in the same
process that serves the dashboard API and the Discord gateway. It already
alerts on event-loop lag above 3 s.

- **Max 3 concurrent voice sessions** bot-wide, from `MUSIC_MAX_SESSIONS`. A
  fourth request gets a clear message, not an error. RAM is comfortable at
  three; CPU is the binding limit once SoundCloud transcoding is involved,
  which is why the number is configurable rather than fixed.
- **Extraction never runs on the event loop.** `yt-dlp` goes through
  `asyncio.to_thread`, like every other blocking call in this codebase.
- **Prefetch the next track** while the current one plays, hiding the 1–3 s
  extraction delay between tracks.
- **Disconnect after 5 minutes idle**, counted from whichever happens first:
  every human leaving the voice channel, or the queue running out with nothing
  playing. Either condition starts the same 5-minute timer; anything that
  resumes activity cancels it.
- **The queue is not persisted.** Deploys are frequent; a queue that resumes
  twenty minutes later is stranger than one that is simply gone.

## Architecture

Logic that can be tested without Discord is separated from the cog, matching
the existing split between `core/levels_settings.py` and `cogs/levels.py`.

| File | Responsibility |
|---|---|
| `core/music_queue.py` | Queue state: add, advance, shuffle, loop modes, remove, clear. Pure Python. |
| `core/music_sources.py` | `yt-dlp` wrapper, Spotify resolution, link parsing, cache lookups. |
| `core/database.py` (extended) | The `music_cache` table, alongside every other SQL access. |
| `cogs/music.py` | Commands, buttons, voice client lifecycle, the player loop. |

### Audio pipeline

`discord.FFmpegOpusAudio.from_probe()` detects the source codec and picks
stream-copy over re-encoding when it can. YouTube's webm/opus is copied
verbatim, costing almost no CPU. SoundCloud mp3 is transcoded.

### Cache

A `music_cache` table keyed by normalised query or URL, holding metadata as
JSON. Searches live 7 days; stream URLs live 6 hours, because YouTube expires
them anyway. This is what makes a repeated search feel instant.

Autocomplete reads **only** from this cache and from recent history. Discord
allows 3 s for an autocomplete response while `yt-dlp` needs 1–3 s per search,
so searching live would be both slow and a way to hammer the VPS on every
keystroke. With no cached match, autocomplete offers a single honest entry:
*"Press Enter to search «…»"*.

## Commands

`/play <query>` · `/skip` · `/queue` · `/nowplaying` · `/volume <0-100>` ·
`/remove <position>` · `/clear` · `/disconnect`

`/play` and `/remove` have autocomplete — `/remove` lists the current queue.
Volume is per-session and resets to 100 when the bot leaves; the buttons step
it by 10.

## Player card

Title, artist, thumbnail, progress bar, requester, source link, and what plays
next. Buttons in two rows:

- ⏯ pause/resume · ⏭ skip · ⏹ stop · 🔀 shuffle · 🔁 loop (off → track → queue)
- 🔉 volume down · 🔊 volume up · 📜 queue

Buttons use `DynamicItem`, as giveaways, roles and tickets already do, so a
card left over from before a restart answers *"This session has ended"* instead
of appearing broken.

The card is edited **on state change** — new track, pause, volume, loop — never
on a timer. A ticking progress bar would cost one edit every few seconds per
session, spending rate limit and CPU on nothing; the bar is computed at render
time and is correct whenever it is looked at.

**Control permissions:** anyone in the same voice channel. Not in the channel,
no skip. Manage Server overrides. No configuration.

## Failure handling

The player loop catches every exception and keeps going — the lesson from the
voice-report tasks, which used to die permanently on one unexpected error.

- Unavailable or geo-blocked track → skip with a note, queue continues
- `yt-dlp` failure → one retry, then skip
- Expired stream URL → re-extract automatically on playback failure
- Extraction over 20 s → skip
- Voice disconnect → attempt reconnect, otherwise clear the session

## Testing

Unit tests in the existing style: `unittest`, runnable standalone with a
`sys.path` insert.

- Queue: add, advance, shuffle, loop modes, remove, clear, size limits
- Link parsing: which platform, track vs playlist
- Spotify metadata → search terms
- Cache: hit, miss, expiry
- Duration formatting
- Regression: the bot joining a voice channel does not create phantom sessions
  in the voice attendance reports (`cogs/voice.py` ignores bots — pinned so it
  stays that way)

## Dependencies

New Python packages: `yt-dlp`, `PyNaCl`. System package: `ffmpeg`.

`yt-dlp` breaks periodically by nature and needs updating more often than the
rest; it is pinned like everything else, but expect to bump it.

## Delivery order

Each step is tested and committed before the next begins.

1. `core/music_queue.py` + tests
2. `music_cache` in `core/database.py` + tests
3. `core/music_sources.py` + tests
4. `cogs/music.py` — basic playback: `/play`, `/skip`, `/disconnect`
5. Player card and buttons
6. Full queue, playlists, volume, loop, shuffle, autocomplete
7. `requirements.txt`, `.env.example`, README and docs

## Explicitly out of scope

Saved user playlists, DJ roles, lyrics, autoplay/radio, playback history, and
dashboard integration on the website. All are natural extensions once the core
proves itself on this hardware.
