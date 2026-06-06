# TheAtheneumSnitch — Guill the Intern

> *"Hi!! I'm Guill, your friendly (and honestly quite underappreciated) guild intern."*

A Discord bot for **The Atheneum** guild in Realm of the Mad God. Guill watches the guild graveyard, scrapes live player data from RealmScope and RealmEye, and posts fame leaderboards, player profiles, build guides, and realm event trackers — all with the personality of an eager (if slightly dramatic) guild intern.

Deployed on a **Raspberry Pi 3** via Docker.

---

## Features

### Death Announcer
Automatically monitors the guild graveyard and posts a styled death card to Discord whenever a guild member dies. Runs every 60 seconds.

### Player Lookup
| Command | Description |
|---|---|
| `!player <name>` | Full scroll-style profile (total fame, seasonal fame, account fame, skins, shinies, exaltations) |
| `!search <name>` | Recruitment card — great for evaluating applicants |
| `!characters <name>` | All characters with class sprites, equipment images, level, fame |
| `!shinies <name>` | Full shiny item collection across all seasons |
| `!gstats <name>` | Live stat deltas — today's and this week's seasonal fame gains, stars, exaltations |

### Guild Roster
| Command | Description |
|---|---|
| `!groster` | Full guild roster list |
| `!online` | Members currently online |
| `!afk` | Members offline for 30+ days |
| `!gdiscord` | Compares guild roster against Discord server members |
| `!gparty` | Members in active parties |
| `!parties` | Top 5 public parties |

### Fame & Leaderboards
All leaderboard commands pull **live data** from RealmScope — no `!snapshot` required.

| Command | Description |
|---|---|
| `!gseason [n]` | Seasonal fame leaderboard (default top 15) |
| `!gtop [n]` | Top N members by seasonal fame |
| `!gdaily` | Fame gained today by each member |
| `!gweekly` | Fame gained in the last 7 days |
| `!gshinies [item]` | Guild shiny leaderboard; with item name, finds who has that specific shiny |
| `!seasonrace` | Seasonal fame gained since `!newseason` was called |

### Build & Item Lookup
| Command | Description |
|---|---|
| `!build <class>` | Lists available stat options for that class |
| `!build <class> <stat>` | Top DPS builds from the RealmShark leaderboard |
| `!item <name>` | Item stats, drop sources, and images from the RealmEye wiki |

### Realm Event Finder
| Command | Description |
|---|---|
| `!find <event>` | Scans all active realms for a named event, dungeon portal, or white bag item |
| `!find o3` | Top 7 realms closest to spawning Oryx 3, ranked by **score × population** — low-pop realms are automatically ranked lower |
| `!find alien` | Shows which Alien Invasion events to specify (UFO, Reactor, etc.) |

The `!find` command supports fuzzy matching and "did you mean?" suggestions when you type a partial name.

### Trivia
| Command | Description |
|---|---|
| `!trivia start [diff] [n]` | Start a trivia round (default: 5 mixed questions) |
| `!trivia quick [diff]` | One quick question |
| `!trivia stop` | Stop the active round |
| `!trivia scores` | All-time leaderboard |
| `!trivia stats <name>` | One player's trivia stats |
| `!trivia add diff\|category\|question\|answer\|[hint]` | Submit a question |
| `!trivia list` | Browse the question bank |

### Admin & Utilities
| Command | Description |
|---|---|
| `!snapshot [--shinies]` | Saves a baseline snapshot — only needed for `!seasonrace` |
| `!newseason` | Marks the season start for `!seasonrace` tracking |
| `!refresh` | Clears the 30-minute live data cache |
| `!leaderboards` | Posts a pinnable embed overview of all commands |
| `!gannounce` | Manually triggers the daily leaderboard announcement |
| `!testdeath` | Posts a test death card |
| `!help [command]` | Overview embed, or detailed help for a specific command |
| `!commands` | Full paginated command list |

---

## Architecture

### Live data (no snapshot needed)
`!gseason`, `!gtop`, `!gdaily`, `!gweekly`, `!gshinies`, `!gstats` — all pull directly from RealmScope on every call, with a 30-minute in-memory cache (`_get_roster()` / `_fame_cache`).

### Snapshot-based commands
`!snapshot` saves a JSON baseline of the guild. Only `!seasonrace` uses it currently.

### Scrapers
- **RealmScope** — guild roster, online status, seasonal fame, party data, shiny counts
- **RealmEye** — item wiki, graveyard / deaths, player profiles
- **RealmShark** — DPS leaderboard builds
- **Realmstock** — live realm event data for `!find`

### Selenium
Headless Chromium (`/usr/bin/chromedriver`) is used for JavaScript-heavy pages. Serialized via `asyncio.Lock()` to prevent concurrent browser crashes on the Pi.

---

## Deployment (Raspberry Pi 3 via Docker)

### Prerequisites
- Docker installed on the Pi
- A `keys.env` file in the project directory

### `keys.env`
```
DISCORD_KEY=your_bot_token
GUILD_NAME=TheAtheneum
CHANNEL_ID=your_channel_id
```

### Build and run
```bash
./run.sh
```
This builds the Docker image, removes any existing container, and starts a new one with `--restart unless-stopped`.

### Manual Docker commands
```bash
docker build -t realmdeathsnitch .
docker run -d --name realmdeathsnitch_container --restart unless-stopped realmdeathsnitch
docker logs -f realmdeathsnitch_container
```

### Updating on the Pi
```bash
git pull
./run.sh
```

### Running without Docker
```bash
pip install -r requirements.txt
python snitch_bot.py
```

---

## Bot Setup (Discord Developer Portal)

1. Go to [Discord Developer Portal](https://discord.com/developers/applications) → New Application
2. **Bot** tab → Reset Token → copy it into `keys.env` as `DISCORD_KEY`
3. **OAuth2** → OAuth2 URL Generator → select **bot** scope → select **Send Messages** + **Attach Files** + **Read Message History**
4. Use the generated URL to invite the bot to your server

---

## Project Structure

```
TheAtheneumSnitch/
├── snitch_bot.py           Main bot — all Discord commands
├── realmscope_scraper.py   Live guild/player data from RealmScope
├── guild_graveyard.py      Death detection and announcements
├── death_card.py           Styled death card image generator
├── player_characters.py    Character + gear display
├── shiny_image_builder.py  Shiny collection card generator
├── build_scraper.py        RealmShark DPS build fetcher
├── build_image.py          Build card image generator
├── event_tracker.py        Realmstock live event scraper + fuzzy search
├── event_image.py          Event result image generator (with O3 banner)
├── guild_stats.py          Snapshot storage and delta calculations
├── trivia_system.py        Trivia question bank and game logic
├── image_downloader.py     Sprite/avatar download utilities
├── Realm_image_parser.py   RealmEye wiki image parser
├── event_drops.json        Cached event to drop mappings
├── Dockerfile              Python 3.9 + Chromium for ARM (Pi)
├── run.sh                  Docker build + restart script
├── requirements.txt        Python dependencies
└── images/
    ├── o3.png              Oryx 3 banner (shown on !find o3 results)
    └── classes/            Class sprite assets
```

---

## License

MIT
