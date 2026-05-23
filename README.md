# songs.ai

A Discord music bot designed from the ground up for **public deployment with zero takedown risk.** Built around legally-clean audio sources only: Creative Commons (Jamendo), the Internet Archive, self-hosted personal libraries (Navidrome / Subsonic), and licensed internet radio (radio-browser.info).

There is no YouTube fallback, no Spotify integration, and no audio from major-label streaming services.

## Why this design

Most "Spotify Discord bots" stream audio from YouTube under the hood, which violates YouTube's ToS, sometimes Spotify's, and the labels' streaming licenses. That's why Groovy and Rythm were shut down in 2021. This bot does not take that path. The trade-off is real: you don't get current chart pop. What you get instead is:

- Full Creative Commons indie catalog via Jamendo (~600k tracks across rock, electronic, jazz, ambient, instrumental, world)
- Your own music library, played from a self-hosted Navidrome server (you can rip your CDs, buy on Bandcamp, etc.)
- The Internet Archive's Live Music Archive (concerts artists explicitly allow distribution of — Grateful Dead, Phish, Smashing Pumpkins, and thousands more)
- Tens of thousands of internet radio stations (all already licensed by the broadcasters in their jurisdictions)

If you want chart music for a friend group, the right answer is **Spotify Jam** — every friend pays for Premium and you all listen together in sync. That's outside this bot's scope.

## Architecture

```
Discord user
   |
   v
 Discord --slash command--> songs.ai (Python, discord.py)
                                |
                                |--- Jamendo API      (CC track URLs)
                                |--- Navidrome API    (your library)
                                |--- Archive.org API  (live + PD music)
                                |--- radio-browser    (radio stream URLs)
                                |--- LRCLIB           (CC0 lyrics)
                                |--- Last.fm          (similar-artist metadata)
                                |
                                `--- Lavalink (audio engine, HTTP source only)
                                         |
                                         `-> Discord voice channel
```

Every source resolves to an HTTP audio URL that Lavalink plays directly. Lavalink's YouTube, SoundCloud, and Bandcamp sources are all **disabled** by config to prevent accidental gray-area use.

## Project layout

```
songs.ai/
├── main.py                  Bot entrypoint (sharded, slash-only)
├── cogs/
│   ├── music.py             /play (Jamendo), queue, /pause /resume /stop /loop /volume,
│   │                         /jamendo search|popular|tag
│   ├── library.py           /library setup|disconnect|status|play|random  (Navidrome)
│   ├── archive.py           /archive search|play|sample  (Internet Archive)
│   ├── radio.py             /radio search|tag|top|play|stop  (radio-browser)
│   ├── discover.py          /discover similar|mood  (Last.fm + Jamendo)
│   └── ux.py                /nowplaying /lyrics /skip /forceskip /credits
├── utils/
│   ├── jamendo_client.py    Async Jamendo API client
│   ├── navidrome_client.py  Subsonic-spec client (Navidrome/Airsonic/Gonic compatible)
│   ├── archive_client.py    Internet Archive search + metadata
│   ├── radio_browser.py     radio-browser.info mirror-aware client
│   ├── lrclib.py            Openly-licensed lyrics (LRCLIB)
│   ├── lastfm_client.py     Similar-artist metadata only
│   ├── crypto.py            Fernet wrapper for encrypting library credentials
│   └── queue.py             Per-guild queue + loop modes
├── lavalink/
│   └── application.yml      Lavalink v4: HTTP source only, no YouTube/SC/BC
├── docker-compose.yml       Local Lavalink
├── requirements.txt
└── .env.example
```

## Setup

### 1. Discord application

Create an application at <https://discord.com/developers/applications>, add a Bot, copy the token into `DISCORD_TOKEN` in your `.env`. Do **not** enable any Privileged Gateway Intents — slash commands don't need them, and this keeps Discord verification simpler.

For the invite URL go to OAuth2 → URL Generator and pick scopes `bot` + `applications.commands`, plus permissions: View Channels, Send Messages, Embed Links, Connect, Speak, Use Voice Activity.

### 2. Jamendo API key (required)

Sign up at <https://devportal.jamendo.com/> and create an app. Copy the Client ID into `JAMENDO_CLIENT_ID`. Free tier is 35,000 requests/month.

### 3. Bot secret key (required)

Generate a Fernet key for encrypting per-guild Navidrome credentials:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Paste the output into `BOT_SECRET_KEY` in `.env`.

### 4. Last.fm API key (optional, enables `/discover similar`)

Free key at <https://www.last.fm/api/account/create>. If you skip this, the rest of the bot still works — only the similar-artist discovery command is disabled.

### 5. Lavalink

```bash
docker compose up -d
```

Brings up Lavalink v4 on port 2333 with the legal-sources-only config. If you'd rather run Lavalink directly, copy `lavalink/application.yml` next to the JAR and `java -jar Lavalink.jar` (requires Java 17+).

### 6. Bot

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # then fill in real values
python main.py
```

Set `DEV_GUILD_ID` to your test server's ID while iterating — slash commands sync in seconds rather than up to an hour.

### 7. (Optional) Connect a Navidrome library

Once the bot is in your server, an admin runs:

```
/library setup
  url: https://music.your-domain.com
  username: yourname
  password: yourpassword
```

The password is encrypted with `BOT_SECRET_KEY` before storage. The bot pings the server to validate before saving.

## Slash commands

### Default playback (Jamendo, CC music — no setup for users)

| Command | What it does |
|---|---|
| `/play <query>` | Search Jamendo and queue the top hit |
| `/jamendo search <query>` | Show top 5 results with a dropdown |
| `/jamendo popular [count]` | Queue this week's most-played CC tracks |
| `/jamendo tag <tag> [count]` | Queue tracks by mood/genre (chill, rock, electronic, jazz, ambient…) |

### Personal library (Navidrome)

| Command | What it does |
|---|---|
| `/library setup <url> <user> <pass>` | Admin: connect this server's Navidrome |
| `/library disconnect` | Admin: forget the connection |
| `/library status` | Is the library reachable? |
| `/library play <query>` | Search and queue from your library |
| `/library random [count] [genre]` | Queue random tracks from your library |

### Internet Archive

| Command | What it does |
|---|---|
| `/archive search <query> [collection]` | Find items in etree / opensource_audio / audio_music / netlabels |
| `/archive play <identifier>` | Queue every track from an Archive item |
| `/archive sample` | Random Live Music Archive concert |

### Radio

| Command | What it does |
|---|---|
| `/radio search <name>` | Find stations by name |
| `/radio tag <tag>` | Find stations by tag (jazz, news, lofi, classical…) |
| `/radio top` | Most-clicked stations right now |
| `/radio play <uuid>` | Tune in |
| `/radio stop` | Stop the radio and disconnect |

### Discovery

| Command | What it does |
|---|---|
| `/discover similar [artist]` | Last.fm similar artists → Jamendo tracks |
| `/discover mood <tag> [count]` | Queue Jamendo tracks for a mood/genre |

### Playback control & UX

| Command | What it does |
|---|---|
| `/pause`, `/resume`, `/stop`, `/clear` | Standard controls |
| `/queue` | Show next 15 tracks |
| `/loop <off\|track\|queue>` | Loop mode |
| `/volume <0-150>` | Set volume |
| `/skip` | Vote-based skip |
| `/forceskip` | Admin instant skip |
| `/nowplaying` | Embed with progress bar |
| `/lyrics` | LRCLIB lookup |
| `/credits` | Show music sources and licensing |

## Publishing checklist

Before listing this bot publicly:

- [ ] **Privacy policy & ToS pages.** Required for Discord verification once you cross 75 servers. Cover: what you store (encrypted Navidrome credentials per guild), how to delete (`/library disconnect`), the third-party services you call.
- [ ] **`/credits` command stays.** Don't strip it — it's how listeners know what license the audio is under.
- [ ] **Swap SQLite for Postgres.** SQLite locks under concurrent writes; bad past ~50 active guilds.
- [ ] **Run 2+ Lavalink nodes** behind Wavelink's node pool, on separate hosts.
- [ ] **Discord verification application** at ~75 guilds. They'll review your bot, your privacy policy, and your data-handling practices.
- [ ] **Don't monetize specific features.** Selling "premium" tiers on a music bot draws regulator attention. Donations toward server costs are fine; "pay to unlock /library" is not.
- [ ] **Attribution.** Last.fm's free API requires you to display attribution. The `/credits` command satisfies this.
- [ ] **Rate-limit handling.** Wrap every external API call with a circuit breaker so one slow source doesn't take down your shard.
- [ ] **Global error handler** that swallows stack traces in user-facing responses.

## Legal posture (read this before forking)

This bot is designed so the *only* audio that reaches Discord is from sources that explicitly authorize streaming:

- **Jamendo** tracks carry per-track Creative Commons licenses. Their developer terms permit API consumers to stream the returned audio URLs.
- **Internet Archive** items in `etree` and `opensource_audio` are uploaded by rights-holders (or for public-domain works); the Archive permits redistribution.
- **Navidrome libraries** are your own files. Your responsibility is making sure you legally own them (ripped CDs, Bandcamp purchases, etc.).
- **Radio stations** in radio-browser.info publish public Icecast/Shoutcast streams; their broadcast licenses cover this. We are not transcoding or modifying — we relay.
- **LRCLIB** lyrics are contributed under CC0.
- **Last.fm** is used for metadata only (similar-artist lists). We don't stream from Last.fm.

The Lavalink config explicitly **disables** YouTube, SoundCloud, and Bandcamp sources to make accidental misuse impossible. If you re-enable them, you've opted into gray-area territory and this README's promises no longer apply.
