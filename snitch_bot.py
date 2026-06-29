import discord
import asyncio
import image_downloader as imd
import guild_graveyard as gg
import json
import os
import subprocess
from datetime import datetime, timezone
from dotenv import load_dotenv
from pathlib import Path
import Realm_image_parser as RIP
from discord.ext import commands
from discord.ext import tasks
import player_characters
import realmscope_scraper as rs
import shiny_image_builder as sib
import guild_stats as gs
import time as time_module
from player_tracker import get_online_status
import build_scraper as bs
import build_image as bi
import io
import re
import event_tracker as et
import event_image as ei
import pytz
import trivia_system as ts
import random


load_dotenv(Path('keys.env'))
# ── Cache system ──────────────────────────────────────────────────────────────
_roster_cache = {"data": None, "timestamp": 0, "last_failure": 0}
_fame_cache   = {"data": None, "timestamp": 0}
CACHE_TTL          = 1800   # 30 minutes
ROSTER_FAIL_BACKOFF = 300   # 5 minutes between failed Selenium attempts

def _cache_age_str(timestamp):
    if timestamp == 0:
        return "never"
    mins = int((time_module.time() - timestamp) / 60)
    if mins < 1:
        return "just now"
    return f"{mins}m ago"

async def _get_roster():
    """Returns cached roster or fetches fresh. Non-blocking."""
    now = time_module.time()
    if _roster_cache["data"] and (now - _roster_cache["timestamp"]) < CACHE_TTL:
        return _roster_cache["data"]
    # Don't hammer Selenium if it just failed — wait before retrying
    if (now - _roster_cache["last_failure"]) < ROSTER_FAIL_BACKOFF:
        print("_get_roster: in failure backoff, returning stale/None")
        return _roster_cache["data"]
    print("_get_roster: fetching live roster via Selenium...")
    async with selenium_lock:
        data = await asyncio.get_event_loop().run_in_executor(
            None, rs.get_guild_roster, "TheAtheneum"
        )
    if data:
        _roster_cache["data"]      = data
        _roster_cache["timestamp"] = time_module.time()
        print(f"_get_roster: got {len(data)} members")
    else:
        _roster_cache["last_failure"] = time_module.time()
        print("_get_roster: Selenium returned None — backoff 5 min before retry")
    return data

async def _get_fame(member_names):
    """Returns cached fame data or fetches fresh. Non-blocking."""
    now = time_module.time()
    if _fame_cache["data"] and (now - _fame_cache["timestamp"]) < CACHE_TTL:
        return _fame_cache["data"]
    data = await asyncio.get_event_loop().run_in_executor(
        None, rs.get_guild_seasonal_fame, member_names
    )
    if data:
        _fame_cache["data"]      = data
        _fame_cache["timestamp"] = time_module.time()
    return data
_guild_members_cache = set()
_guild_members_last_fetch = 0
selenium_lock = None



intents = discord.Intents.default()
# MESSAGE CONTENT is a privileged intent. Keep it opt-in so the bot can run
# in environments where that intent is not enabled in the Discord developer portal.
intents.message_content = os.getenv("ENABLE_MESSAGE_CONTENT", "false").lower() == "true"
bot = commands.Bot(command_prefix='!', intents=intents)
bot.remove_command("help")  # We have our own !help with Guill flair
channel_id = int(os.getenv("CHANNEL_ID"))
deaths_channel_id = int(os.getenv("DEATHS_CHANNEL_ID", "0")) or None
channel = None
guild = os.getenv("GUILD_NAME")

# ── Per-command usage strings (shown in error messages) ───────────────────────
COMMAND_USAGE = {
    "player":     "!player <player_name>",
    "search":     "!search <player_name>",
    "characters": "!characters <player_name>",
    "shinies":    "!shinies <player_name>",
    "gstats":     "!gstats <player_name>",
    "item":       "!item <item name>",
    "find":       "!find <event / dungeon / item>",
    "build":      "!build <class> [stat]",
    "gtop":       "!gtop [number]",
    "gseason":    "!gseason [top_n]",
    "trivia":     "!trivia <start|quick|stop|scores|stats|add|list>",
    "snapshot":   "!snapshot [--shinies]",
    "gshinies":   "!gshinies [item_name]",
}

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        usage = COMMAND_USAGE.get(ctx.command.name, f"!{ctx.command.name}")
        await ctx.send(
            f"Whoops!! Looks like you forgot something there 😅\n"
            f"**Usage:** `{usage}`\n"
            f"*(Try `!help {ctx.command.name}` for more details!)*"
        )
    elif isinstance(error, commands.CommandNotFound):
        cmd_tried = str(error).split('"')[1] if '"' in str(error) else "that"
        await ctx.send(
            f"Hmm... I don't know what `!{cmd_tried}` is 🤔\n"
            f"Type `!commands` to see everything I can do!"
        )
    elif isinstance(error, commands.BadArgument):
        usage = COMMAND_USAGE.get(ctx.command.name, f"!{ctx.command.name}")
        await ctx.send(
            f"Oof, that argument doesn't look right 😬\n"
            f"**Usage:** `{usage}`"
        )
    elif isinstance(error, commands.CheckFailure):
        await ctx.send("You don't have permission for that one! 🚫")
    else:
        raise error

_guild_online_state = {}  # player_lower -> "Online" | "Offline"

async def run_guild_online_tracker():
    last_seen_online = set()
    while True:
        try:
            snap = gs.get_latest_snapshot()
            if not snap:
                await asyncio.sleep(120)
                continue

            member_names = [v["name"] for v in snap["members"].values()]
            now = int(time_module.time())

            currently_online = set()
            for name in member_names:
                status = await asyncio.get_event_loop().run_in_executor(
                    None, get_online_status, name
                )
                if status == "Online":
                    currently_online.add(name)

            # Only announce players who just came online
            just_came_online = currently_online - last_seen_online
            channel = bot.get_channel(int(channel_id))

            for name in just_came_online:
                await channel.send(f"👀 Psst — **{name}** just logged on! I spotted them first!!")

            last_seen_online = currently_online

        except Exception as e:
            print(f"Guild online tracker error: {e}")

        await asyncio.sleep(120)



async def run_guild_graveyard():
    import death_card as dc
    last_death_name_time = None

    # Load last known death from file so we don't re-announce on restart
    try:
        with open("last death.json") as f:
            saved = json.load(f)
            last_death_name_time = f"{saved.get('player-name','')}_{saved.get('time','')}"
    except Exception:
        pass

    while True:
        try:
            deaths = await asyncio.get_event_loop().run_in_executor(None, dc.fetch_latest_deaths, guild)
            if not deaths:
                await asyncio.sleep(60)
                continue

            latest = deaths[0]
            current_key = f"{latest['player-name']}_{latest['time']}"

            if current_key != last_death_name_time:
                # Find #deaths channel before doing anything irreversible
                if deaths_channel_id:
                    d_channel = bot.get_channel(deaths_channel_id)
                else:
                    d_channel = discord.utils.get(bot.get_all_channels(), name="deaths")
                if not d_channel:
                    print(f"Could not find #deaths channel (id={deaths_channel_id})")
                    await asyncio.sleep(60)
                    continue

                # Build the death card image off the event loop
                try:
                    img_path = await asyncio.get_event_loop().run_in_executor(
                        None, dc.build_death_card, latest
                    )
                except Exception as e:
                    print(f"Death card build error: {e}")
                    img_path = None

                msg = (
                    f"☠️ **{latest['player-name']}** has fallen... I watched from my desk and I'm not okay\n"
                    f"**Killed by:** {latest['killed_by']}\n"
                    f"**Stats:** {latest['stats']}  "
                    f"**Base Fame:** {latest['base_fame']}  "
                    f"**Total Fame:** {latest['total_fame']}\n"
                    f"**Time:** {dc.format_death_time(latest['time'])}"
                )

                if img_path and os.path.exists(img_path):
                    await d_channel.send(msg, file=discord.File(img_path))
                else:
                    await d_channel.send(msg)

                # Only mark as seen after successfully sending
                last_death_name_time = current_key
                with open("last death.json", "w") as f:
                    json.dump(latest, f)

                print(f"Death announced: {latest['player-name']} killed by {latest['killed_by']}")

        except Exception as e:
            print(f"Guild graveyard error: {e}")

        await asyncio.sleep(60)


_background_tasks_started = False

@bot.event
async def on_ready():
    global selenium_lock, _background_tasks_started
    if selenium_lock is None:
        selenium_lock = asyncio.Lock()
    print(f'We have logged in as {bot.user}')
    print(f'curl_cffi available: {rs._HAS_CURL_CFFI}')
    if not intents.message_content:
        print('MESSAGE CONTENT intent is disabled; prefix commands may not be available.')
    if not _background_tasks_started:
        _background_tasks_started = True
        try:
            subprocess.run(["pkill", "-f", "chromium"], capture_output=True)
        except Exception:
            pass
        # Start a virtual X11 display so Chrome can run in non-headless mode.
        # Non-headless Chrome on Xvfb has the same JS environment as a real browser,
        # so Cloudflare's fingerprint checks pass. Headless Chrome (any mode) fails them.
        if "DISPLAY" not in os.environ:
            try:
                subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1366x768x24"])
                await asyncio.sleep(1)
                os.environ["DISPLAY"] = ":99"
                print("Xvfb virtual display started on :99")
            except Exception as e:
                print(f"Xvfb unavailable ({e}) — Chrome will fall back to --headless=new")
        else:
            print(f"DISPLAY already set to {os.environ['DISPLAY']}")
        bot.loop.create_task(run_guild_graveyard())
    #bot.loop.create_task(run_guild_online_tracker())
    #bot.loop.create_task(run_guild_party_tracker())
    #bot.loop.create_task(run_daily_snapshot())
    #bot.loop.create_task(run_event_leaderboards())



	
@bot.command(name="characters")
async def characters(ctx, player_name: str):
    print(f"characters command for {player_name}")
    player_character_list = player_characters.get_player_characters(player_name)

    if not player_character_list:
        await ctx.send(f"Hmm... couldn't find any characters for **{player_name}**. Their profile might be private, or maybe a typo? I checked twice, I promise 😅")
        return

    await ctx.send(f"Found **{len(player_character_list)}** character{'s' if len(player_character_list) != 1 else ''} for **{player_name}**! Here they are — I even rendered the portraits 🎨")
    for i, char in enumerate(player_character_list):
        RIP.skin_image_parser(char['skin_id'], f"{char['class']}_{i}")
        for item in char['equipment']:
            RIP.item_image_parser(item['id'], item['name'])

        RIP.character_image_combiner(char, i)

        season_tag = "🌿 Seasonal" if char['seasonal'] else "💀 Unseasonal"
        maxed_tag = "⭐ " if char['stats'] == "8/8" else ""
        await ctx.send(
            f"{maxed_tag}**{char['class']}** | {season_tag} | Level {char['level']} | Fame: {char['fame']} | Stats: {char['stats']}",
            file=discord.File("./images/alive_output.png")
        )

    RIP.delete_all_files_in_folder("./itempics")
    RIP.delete_all_files_in_folder("./skinpics")

@bot.command(name="player")
async def player(ctx, player_name: str):
    info = rs.get_player_info(player_name)
    if not info:
        await ctx.send(f"❌ Could not find player **{player_name}** on RealmScope.")
        return

    W = 36

    def content(text=""):
        return f"    |{text:^{W}}|."

    def stat(label, value, rank=""):
        rank_str = f" {rank}" if rank else ""
        text = f" {label} {value}{rank_str}"
        return f"    |{text:<{W}}|."

    name_line = f"* {info['stars']} *  {info['name']}"

    lines = []
    lines.append(f"   {'_' * W}")
    lines.append(f" / \\{' ' * W}\\.")
    lines.append(f"|   |{' ' * W}|.")
    lines.append(content("~ THE ATHENEUM ~"))
    if info['guild_rank']:
        lines.append(content(info['guild_rank']))
    lines.append(f" \\_ |{name_line:^{W}}|.")
    lines.append(content())
    lines.append(stat("(F)  Fame         ", f"{info['total_fame']:,}",    info['rank_fame']))
    lines.append(stat("(SF) Seasonal Fame", f"{info['seasonal_fame']:,}", info['rank_seasonal_fame']))
    lines.append(stat("(AF) Account Fame ", f"{info['account_fame']:,}",  info['rank_account_fame']))
    lines.append(content())
    lines.append(stat("(S)  Skins        ", f"{info['skins']:,}",         info['rank_skins']))
    lines.append(stat("(*)  Shinies      ", f"{info['total_shinies']:,}"))
    lines.append(stat("(X)  Exaltations  ", f"{info['exaltations']:,}"))
    lines.append(content())
    lines.append(content())
    lines.append(f"    |   {'_' * W}|___")
    lines.append(f"    |  /{' ' * W}/.")
    lines.append(f"    \\_/{'_' * W}/.")

    await ctx.send("```\n" + "\n".join(lines) + "\n```")


@bot.command(name="parties")
async def parties(ctx):
    data = rs.get_top_parties(5)
    if not data:
        await ctx.send("Ugh... RealmScope wasn't cooperating just now. Try again in a sec? 😓")
        return

    W = 44

    def top():  return f"  ╔{'═' * W}╗"
    def bot():  return f"  ╚{'═' * W}╝"
    def mid():  return f"  ╠{'═' * W}╣"
    def div():  return f"  ╟{'─' * W}╢"
    def row(t): return f"  ║ {t:<{W-2}} ║"
    def ctr(t): return f"  ║{t:^{W}}║"

    lines = []
    lines.append(top())
    lines.append(ctr("~ Top 5 Active Parties ~"))
    lines.append(mid())

    for i, p in enumerate(data):
        if i > 0:
            lines.append(div())
        rank_label = f"#{i+1}"
        desc = p['desc'][:30] + ".." if len(p['desc']) > 30 else p['desc']
        lines.append(row(f"{rank_label}  {desc}"))
        lines.append(row(f"   Players  {p['players']:<10}  [{p['server']}]"))
        lines.append(row(f"   {p['status']:<10} {p['privacy']:<10} {p['type']:<10}"))
        lines.append(row(f"   Created  {p['created']}"))

    lines.append(bot())

    await ctx.send("```\n" + "\n".join(lines) + "\n```")


@bot.command(name="shinies")
async def shinies(ctx, player_name: str):
    await ctx.send(f"Ooh, checking **{player_name}**'s shiny collection!! Give me a moment... ✨")
    data = rs.get_shiny_data(player_name)
    if not data:
        await ctx.send(f"Hmm... couldn't find shiny data for **{player_name}**. Either their profile's private or they just haven't gotten any shinies yet (yikes) 😬")
        return

    W = 42
    def top():    return f"  ╔{'═' * W}╗"
    def bot():    return f"  ╚{'═' * W}╝"
    def mid():    return f"  ╠{'═' * W}╣"
    def row(t):   return f"  ║ {t:<{W-2}} ║"
    def ctr(t):
        return f"  ║{t:^{W}}║"

    lines = []
    lines.append(top())
    lines.append(ctr(f"*+* {player_name}'s Shiny Collection *+*"))
    lines.append(mid())
    lines.append(row(f"{'Total Shinies':<26}{data['total']:>6}"))
    lines.append(row(f"{'Progress':<26}{data['progress']:>6}"))
    lines.append(row(f"{'':>4}{data['progress_pct']}"))
    lines.append(row(""))
    lines.append(row(f"{'Shiny Rank':<26}{data['rank']:>6}"))
    lines.append(row(f"{'':>4}{data['rank_sub']}"))
    lines.append(row(""))
    lines.append(row(f"{'Seasonal Rank':<26}{data['season_rank']:>6}"))
    lines.append(row(f"{'':>4}{data['season_rank_sub']}"))
    lines.append(bot())

    msg = "```\n" + "\n".join(lines) + "\n```"

    success = sib.build_shiny_image(data["seasons"], player_name)
    if success:
        await ctx.send(msg, file=discord.File("./images/shinies_output.png"))
    else:
        await ctx.send(msg)

# State for party notifications
_guild_party_state = {}  # player -> party_id they were last seen in

async def run_guild_party_tracker():
    global _guild_party_state, _guild_members_cache, _guild_members_last_fetch
    while True:
        try:
            now = asyncio.get_event_loop().time()
            if not _guild_members_cache or (now - _guild_members_last_fetch) > 600:
                async with selenium_lock:
                    _guild_members_cache = await asyncio.get_event_loop().run_in_executor(
                        None, rs.get_guild_members, "TheAtheneum"
                    )
                _guild_members_last_fetch = now
                print(f"Guild member cache refreshed: {len(_guild_members_cache)} members")

            async with selenium_lock:
                current = await asyncio.get_event_loop().run_in_executor(
                    None, rs.get_guild_party_status_with_members, "TheAtheneum", _guild_members_cache
                )

            channel = bot.get_channel(int(channel_id))

            for player, info in current.items():
                prev_party = _guild_party_state.get(player.lower())
                if prev_party != info["party_id"]:
                    spots_left = info["max"] - info["current"]
                    desc = info["desc"] if info["desc"] != "—" else f"Party #{info['party_id']}"
                    await channel.send(
                        f">> **{player}** joined **{desc}**! "
                        f"[{info['current']}/{info['max']}] "
                        f"({spots_left} spot{'s' if spots_left != 1 else ''} left) "
                        f"| {info['server']}"
                    )

            _guild_party_state = {p.lower(): v["party_id"] for p, v in current.items()}

        except Exception as e:
            print(f"Guild party tracker error: {e}")

        await asyncio.sleep(120)

@bot.command(name="gparty")
async def gparty(ctx):
    await ctx.send("On it!! Scanning all parties for guildmates... this might take up to 30 seconds, I'm running as fast as I can 🏃")
    
    async with selenium_lock:
        members = await asyncio.get_event_loop().run_in_executor(
            None, rs.get_guild_members, "TheAtheneum"
        )
    async with selenium_lock:
        current = await asyncio.get_event_loop().run_in_executor(
            None, rs.get_guild_party_status_with_members, "TheAtheneum", members
        )

    W = 44
    def top():  return f"  ╔{'═' * W}╗"
    def bot():  return f"  ╚{'═' * W}╝"
    def mid():  return f"  ╠{'═' * W}╣"
    def div():  return f"  ╟{'─' * W}╢"
    def row(t): return f"  ║ {t:<{W-2}} ║"
    def ctr(t): return f"  ║{t:^{W}}║"

    lines = []
    lines.append(top())
    lines.append(ctr("~ Atheneum Members In Parties ~"))
    lines.append(mid())

    if not current:
        lines.append(ctr("No members found in any party"))
    else:
        first = True
        for player, info in current.items():
            if not first:
                lines.append(div())
            first = False
            desc = info["desc"] if info["desc"] != "—" else f"Party #{info['party_id']}"
            desc_short = desc[:30] + ".." if len(desc) > 30 else desc
            spots_left = info["max"] - info["current"]
            lines.append(row(f"(>) {player}"))
            lines.append(row(f"    {desc_short}"))
            lines.append(row(f"    [{info['current']}/{info['max']}] {spots_left} spots left  |  {info['server']}"))

    lines.append(bot())
    await ctx.send("```\n" + "\n".join(lines) + "\n```")

@bot.command(name="groster")
async def groster(ctx):
    await ctx.send("Pulling up the roster!! Give me a sec... 📋")

    async with selenium_lock:
        members = await asyncio.get_event_loop().run_in_executor(
            None, rs.get_guild_roster, "TheAtheneum"
        )

    if not members:
        await ctx.send("Oof... couldn't load the roster. RealmScope might be having a moment. Try again? 😬")
        return

    W = 46

    def top():  return f"  ╔{'═' * W}╗"
    def bot():  return f"  ╚{'═' * W}╝"
    def div():  return f"  ╟{'─' * W}╢"
    def mid():  return f"  ╠{'═' * W}╣"
    def row(t): return f"  ║ {t:<{W-2}} ║"
    def ctr(t): return f"  ║{t:^{W}}║"

    lines = []
    lines.append(top())
    lines.append(ctr(""))
    lines.append(ctr("~ THE ATHENEUM ~"))
    lines.append(ctr(f"{len(members)} Members"))
    lines.append(ctr(""))
    lines.append(mid())

    for m in members:
        name = m["name"][:16]
        rank = m["rank"][:9]
        fame = f"{m['fame']:,}"
        lines.append(row(f"{name:<17} {rank:<10} {fame:>12}"))

    lines.append(bot())

    msg = "```\n" + "\n".join(lines) + "\n```"
    if len(msg) <= 1990:
        await ctx.send(msg)
    else:
        # Split into chunks
        header_lines = lines[:6]
        member_lines = lines[6:-1]
        footer = lines[-1]

        chunk = ["```"] + header_lines
        for line in member_lines:
            chunk.append(line)
            if len("\n".join(chunk) + "\n```") > 1800:
                await ctx.send("\n".join(chunk) + "\n```")
                chunk = ["```"]
        chunk.append(footer)
        await ctx.send("\n".join(chunk) + "\n```")


@bot.command(name="search")
async def search(ctx, player_name: str):
    info = rs.get_player_recruitment_info(player_name)
    if not info:
        await ctx.send(f"Hmm... I couldn't find **{player_name}** anywhere. Private profile, or maybe a typo? I looked everywhere!! 🔍")
        return

    W = 32  # Fixed inner width — everything must fit within this

    def line(text=""):
        """A centered content line."""
        return f"    |{text:^{W}}|."

    def sline(label, value):
        """A stat line — label left, value right, truncated to fit."""
        value = str(value)
        # Max space for value after label + 1 space
        max_val = W - len(label) - 2
        if len(value) > max_val:
            value = value[:max_val]
        return f"    | {label}{value:>{max_val}} |."

    def div():
        return f"    |{'~' * W}|."

    def wrap(label, value):
        """If label+value too long, split onto two lines."""
        value = str(value)
        first_line = f" {label} {value}"
        if len(first_line) <= W:
            return [f"    |{first_line:<{W}}|."]
        # Split — label on first line, value indented on second
        return [
            f"    | {label:<{W-1}}|.",
            f"    |   {value:>{W-4}}|."
        ]

    status_str = "(+) ONLINE" if info["status"] == "Online" else "(-) Offline"
    name_line  = f"{info['name'][:18]}  * {info['stars']} *"
    maxed_str  = f"{info['maxed_chars']} maxed" if info["maxed_chars"] > 0 else "none maxed"
    chars_val  = f"{info['total_chars']}  ({maxed_str})"

    scroll_lines = []
    scroll_lines.append(f"   {'_' * W}")
    scroll_lines.append(f" / \\{' ' * W}\\.")
    scroll_lines.append(f"|   |{' ' * W}|.")
    scroll_lines.append(line("~ RECRUITMENT CARD ~"))
    scroll_lines.append(f" \\_ |{name_line:^{W}}|.")
    scroll_lines.append(line(status_str))
    scroll_lines.append(line())
    scroll_lines.append(div())
    scroll_lines.append(line())
    scroll_lines += wrap("(F)  Fame         ", f"{info['total_fame']:,}")
    scroll_lines += wrap("(SF) Seasonal Fame", f"{info['seasonal_fame']:,}")
    scroll_lines += wrap("(AF) Account Fame ", f"{info['account_fame']:,}")
    scroll_lines.append(line())
    scroll_lines.append(div())
    scroll_lines.append(line())
    scroll_lines += wrap("(X)  Exaltations  ", f"{info['exaltations']:,}")
    scroll_lines += wrap("(S)  Skins        ", f"{info['skins']:,}")
    scroll_lines += wrap("(*)  Shinies      ", f"{info['shinies']:,}")
    scroll_lines.append(line())
    scroll_lines.append(div())
    scroll_lines.append(line())
    scroll_lines += wrap("(C)  Characters   ", chars_val)
    scroll_lines += wrap("(B)  Best Stats   ", f"{info['best_stats']}/8")
    scroll_lines.append(line())
    scroll_lines.append(div())
    scroll_lines.append(line())
    scroll_lines += wrap("(T)  First Seen   ", info["first_seen"])
    scroll_lines += wrap("(L)  Last Seen    ", info["last_seen"])
    scroll_lines += wrap("(V)  Server       ", info["server"])
    scroll_lines.append(line())
    scroll_lines.append(f"    |   {'_' * W}|___")
    scroll_lines.append(f"    |  /{' ' * W}/.")
    scroll_lines.append(f"    \\_/{'_' * W}/.")

    await ctx.send("```\n" + "\n".join(scroll_lines) + "\n```")

@bot.command(name="afk")
async def afk(ctx):
    await ctx.send("Checking who's been slacking off... don't tell them I said that 🤫")

    async with selenium_lock:
        afk_members = await asyncio.get_event_loop().run_in_executor(
            None, rs.get_afk_members, "TheAtheneum", 30
        )

    if afk_members is None:
        await ctx.send("Uh oh... couldn't grab guild data right now. RealmScope might be struggling 😅")
        return

    W = 46

    def top():  return f"  ╔{'═' * W}╗"
    def bot():  return f"  ╚{'═' * W}╝"
    def mid():  return f"  ╠{'═' * W}╣"
    def row(t): return f"  ║ {t:<{W-2}} ║"
    def ctr(t): return f"  ║{t:^{W}}║"

    lines = []
    lines.append(top())
    lines.append(ctr(""))
    lines.append(ctr("~ AFK MEMBERS ~"))
    lines.append(ctr("Offline for 30+ days"))
    lines.append(ctr(""))
    lines.append(mid())

    if not afk_members:
        lines.append(ctr("Everyone's been logging in — nice!! 🎉"))
    else:
        lines.append(row(f"{'Name':<18} {'Away':>8}   {'Fame':>12}"))
        lines.append(mid())
        for m in afk_members:
            name = m["name"][:17]
            lines.append(row(f"{name:<18} {m['time_str']:>8}   {m['fame']:>12,}"))

    lines.append(bot())

    msg = "```\n" + "\n".join(lines) + "\n```"
    await ctx.send(msg)


@bot.command(name="item")
async def item(ctx, *, item_name: str):
    slug = item_name.lower().strip().replace(" ", "-")
    await ctx.send(f"Looking up **{item_name}** on the wiki! One sec... 📖")

    info = rs.get_wiki_item(slug)
    if not info:
        await ctx.send(
            f"Hmm... couldn't find **{item_name}** on the RealmEye wiki 😅\n"
            f"Try the exact item name — like `!item void blade` or `!item helm of the juggernaut`!"
        )
        return

    W = 34
    def line(text=""):  return f"    |{text:^{W}}|."
    def div():          return f"    |{'~' * W}|."
    def lline(text):    return f"    | {text:<{W-2}}|."
    def sline(label, value):
        value   = str(value)
        content = f" {label}: {value}"
        if len(content) <= W:
            return [f"    |{content:<{W}}|."]
        # Wrap onto two lines
        return [
            f"    | {label}:{' ' * max(0, W-len(label)-2)}|.",
            f"    |   {value[:W-4]:<{W-4}}|.",
        ]

    s     = info["stats"]
    name  = info["name"]

    # Tier + source
    tier = s.get("tier", "?")
    src  = s.get("tier_source", "")
    tier_line = f"{tier}  [{src}]" if src else tier

    scroll = []
    scroll.append(f"   {'_' * W}")
    scroll.append(f" / \\{' ' * W}\\.")
    scroll.append(f"|   |{' ' * W}|.")
    scroll.append(line("~ ITEM LOOKUP ~"))
    scroll.append(f" \\_ |{name[:W]:^{W}}|.")
    scroll.append(line(tier_line[:W]))
    if info["loot_bag"]:
        scroll.append(line(info["loot_bag"]))
    scroll.append(line())
    scroll.append(div())
    scroll.append(line())

    # ── Combat stats (weapons / abilities) ───────────────────────────────────
    combat_keys = [
        ("damage",       "Damage"),
        ("total_damage", "Total Dmg"),
        ("shots",        "Shots"),
        ("rof",          "Rate of Fire"),
        ("range",        "Range"),
        ("speed",        "Proj Speed"),
        ("lifetime",     "Lifetime"),
        ("amplitude",    "Amplitude"),
        ("frequency",    "Frequency"),
        ("mp_cost",      "MP Cost"),
        ("on_equip",     "On Equip"),
        ("effects",      "Effect(s)"),
        ("power_level",  "Power Level"),
    ]
    has_combat = False
    for key, label in combat_keys:
        if key in s:
            scroll += sline(label, s[key])
            has_combat = True

    # ── Artifact / consumable stats ───────────────────────────────────────────
    artifact_keys = [
        ("stack_limit",   "Stack Limit"),
        ("dust_cost",     "Dust Cost"),
        ("weight_effects","Weight Effects"),
        ("min_mod_tier",  "Min Mod Tier"),
    ]
    for key, label in artifact_keys:
        if key in s:
            val = str(s[key])
            if len(val) > W - len(label) - 4:
                # Long weight effects — split into lines
                scroll.append(lline(f"{label}:"))
                for chunk in [val[i:i+W-4] for i in range(0, len(val), W-4)]:
                    scroll.append(lline(f"  {chunk}"))
            else:
                scroll += sline(label, val)
            has_combat = True

    # ── Common stats ─────────────────────────────────────────────────────────
    general_keys = [
        ("xp_bonus",    "XP Bonus"),
        ("feed_power",  "Feed Power"),
        ("used_dust",   "Dust"),
        ("forging_cost","Forge Cost"),
        ("dismantling", "Dismantle"),
    ]
    for key, label in general_keys:
        if key in s:
            scroll += sline(label, s[key])

    if s.get("soulbound"):
        scroll.append(lline("Soulbound"))

    scroll.append(line())
    scroll.append(div())
    scroll.append(line())

    # ── Shiny / Reskin ────────────────────────────────────────────────────────
    scroll += sline("Has Shiny",  "Yes" if info["has_shiny"] else "No")
    if info["reskin_of"]:
        scroll += sline("Reskin of", info["reskin_of"][:W-14])

    # ── Awakened enchantments ─────────────────────────────────────────────────
    if info["awakened"]:
        scroll.append(line())
        scroll.append(div())
        scroll.append(line())
        scroll.append(lline("Awakened Enchantment:"))
        for ench in info["awakened"]:
            for chunk in [ench[i:i+W-4] for i in range(0, min(len(ench), W*2), W-4)]:
                scroll.append(lline(f"  {chunk}"))

    # ── Drops / Obtained ─────────────────────────────────────────────────────
    if info["drops"] or info["obtained"] or info["blueprint"]:
        scroll.append(line())
        scroll.append(div())
        scroll.append(line())
        if info["drops"]:
            scroll.append(lline("Drops From:"))
            for d in info["drops"]:
                scroll.append(lline(f"  {d[:W-4]}"))
        if info["obtained"]:
            scroll.append(lline("Obtained Through:"))
            for o in info["obtained"]:
                scroll.append(lline(f"  {o[:W-4]}"))
        if info["blueprint"]:
            scroll += sline("Blueprint", info["blueprint"][:W-14])

    scroll.append(line())
    scroll.append(f"    |   {'_' * W}|___")
    scroll.append(f"    |  /{' ' * W}/.")
    scroll.append(f"    \\_/{'_' * W}/.")

    msg = "```\n" + "\n".join(scroll) + "\n```"

    # Send with item image — prefer shiny image if available as a second file
    files = []
    for url_key, fname in [("img_url", "item.png"), ("shiny_url", "item_shiny.png")]:
        url = info.get(url_key)
        if url:
            try:
                req      = urllib.request.Request(url, headers={"User-Agent": "Magic Browser"})
                img_data = urllib.request.urlopen(req, timeout=10).read()
                files.append(discord.File(io.BytesIO(img_data), filename=fname))
            except Exception:
                pass

    if files:
        await ctx.send(msg, file=files[0])
        if len(files) > 1:
            await ctx.send("✨ And here's the shiny version!! *sparkle sparkle*", file=files[1])
    else:
        await ctx.send(msg)

@bot.command(name="online")
async def online(ctx):
    await ctx.send("Eyes open!! Checking who's online... 👀")

    async with selenium_lock:
        results = await asyncio.get_event_loop().run_in_executor(
            None, rs.get_guild_online_status, "TheAtheneum"
        )

    if not results:
        await ctx.send("Couldn't get the guild status right now... RealmScope's being weird 😓")
        return

    online_members = [m for m in results if m["status"] == "Online"]

    W = 36

    def top():  return f"  ╔{'═' * W}╗"
    def bot():  return f"  ╚{'═' * W}╝"
    def mid():  return f"  ╠{'═' * W}╣"
    def row(t): return f"  ║ {t:<{W-2}} ║"
    def ctr(t): return f"  ║{t:^{W}}║"

    lines = []
    lines.append(top())
    lines.append(ctr(""))
    lines.append(ctr("~ ATHENEUM ONLINE ~"))
    lines.append(ctr(f"{len(online_members)} of {len(results)} members online"))
    lines.append(ctr(""))
    lines.append(mid())

    if not online_members:
        lines.append(ctr("Nobody online... the realm is quiet 👻"))
    else:
        for m in online_members:
            lines.append(row(f"(+)  {m['name']}"))

    lines.append(bot())


    await ctx.send("```\n" + "\n".join(lines) + "\n```")

# ── Background: daily snapshot at midnight UTC ──────────────────────
async def run_daily_snapshot():
    while True:
        now = datetime.now(timezone.utc)
        seconds_until_midnight = (
            (23 - now.hour) * 3600 +
            (59 - now.minute) * 60 +
            (60 - now.second)
        )
        await asyncio.sleep(seconds_until_midnight)
        try:
            is_sunday     = datetime.now(timezone.utc).weekday() == 6
            fetch_shinies = is_sunday  # Full shiny scan once a week

            async with selenium_lock:
                members = await asyncio.get_event_loop().run_in_executor(
                    None, rs.get_guild_roster, "TheAtheneum"
                )
            if members:
                snap = gs.take_snapshot(members, fetch_shinies=fetch_shinies)
                gs.store_snapshot(snap)
                print(f"Daily snapshot: {snap['date']} — {len(members)} members"
                      + (" (with shinies)" if fetch_shinies else ""))
        except Exception as e:
            print(f"Snapshot error: {e}")
        await asyncio.sleep(60)


def _leaderboard_msg(title: str, entries: list, failed: list = None) -> str:
    W = 44
    def top():  return f"  ╔{'═' * W}╗"
    def bot():  return f"  ╚{'═' * W}╝"
    def mid():  return f"  ╠{'═' * W}╣"
    def div():  return f"  ╟{'─' * W}╢"
    def row(t): return f"  ║ {t:<{W-2}} ║"
    def ctr(t): return f"  ║{t:^{W}}║"

    medals = ["(1)", "(2)", "(3)"]
    lines  = [top(), ctr(title), mid()]

    if not entries:
        lines.append(ctr("No data available"))
    else:
        for i, (name, val) in enumerate(entries):
            medal = medals[i] if i < 3 else f"({i+1})"
            lines.append(row(f"{medal} {name:<16} {val:>12,}"))

    if failed:
        lines.append(div())
        lines.append(ctr("~ Could Not Fetch ~"))
        for name in failed:
            lines.append(row(f"  (?) {name:<16} retry later"))

    lines.append(bot())
    return "```\n" + "\n".join(lines) + "\n```"

# ── Commands ─────────────────────────────────────────────────────────

@bot.command(name="snapshot")
async def snapshot_cmd(ctx, *, flags: str = ""):
    fetch_shinies = "--shinies" in flags
    msg = "Taking a guild snapshot!! Hold on... 📸"
    if fetch_shinies:
        msg += " (Full shiny scan included — this takes 2-3 mins, I'm not slacking I promise)"
    await ctx.send(msg)

    async with selenium_lock:
        members = await asyncio.get_event_loop().run_in_executor(
            None, rs.get_guild_roster, "TheAtheneum"
        )
    if not members:
        await ctx.send("Oof... couldn't grab guild data for the snapshot. RealmScope might be down 😓")
        return

    snap = gs.take_snapshot(members, fetch_shinies=fetch_shinies)
    gs.store_snapshot(snap)
    await ctx.send(
        f"Snapshot saved!! **{len(members)}** members recorded at `{snap['date']}`. Good data, good data! 📋"
        + (" Shinies included too!! That one took a while, you're welcome." if fetch_shinies else "")
    )

# ── !gseason ──────────────────────────────────────────────────────────────────
@bot.command(name="gseason")
async def gseason(ctx, top: int = 15):
    """Seasonal fame leaderboard — pulls live from guild roster page."""
    await ctx.send("Pulling up the seasonal leaderboard!! Let's see who's been grinding... 📊")

    members = await _get_roster()

    if not members:
        await ctx.send("Oof... couldn't load the roster. RealmScope might be having a moment. Try again? 😬")
        return

    members.sort(key=lambda m: m["seasonal_fame"], reverse=True)
    top_n   = members[:top]
    medals  = ["(1)", "(2)", "(3)"]
    W       = 46

    def top_():  return f"  ╔{'═' * W}╗"
    def bot_():  return f"  ╚{'═' * W}╝"
    def mid_():  return f"  ╠{'═' * W}╣"
    def row_(t): return f"  ║ {t:<{W-2}} ║"
    def ctr_(t): return f"  ║{t:^{W}}║"

    lines = [top_(), ctr_("~ Seasonal Fame Leaderboard ~"), mid_()]
    lines.append(row_(f"{'Player':<18} {'Seasonal Fame':>14}"))

    lines.append(mid_())

    for i, m in enumerate(top_n):
        medal = medals[i] if i < 3 else f"({i+1})"
        name  = m["name"][:16]
        sf    = f"{m['seasonal_fame']:,}"
        tf    = f"{m['fame']:,}"
        lines.append(row_(f"{medal} {name:<16} {sf:>14}"))

    lines.append(bot_())
    age = _cache_age_str(_roster_cache["timestamp"])
    await ctx.send(f"```\n" + "\n".join(lines) + f"\n```\n*Last updated: {age}*")


# ── !gdaily ───────────────────────────────────────────────────────────────────
@bot.command(name="gdaily")
async def gdaily(ctx):
    """Today's and 24h seasonal fame gains per member."""
    await ctx.send("Checking today's fame gains!! Who's been a good little realmie today? 📊")

    members = await _get_roster()
    if not members:
        await ctx.send("Oof... couldn't load the roster. RealmScope might be having a moment. Try again? 😬")
        return
    member_names = [m["name"] for m in members]

    results = await _get_fame(member_names)

    board = [(r["name"], r["daily"]) for r in results
             if not r.get("failed") and r["daily"] > 0]
    board.sort(key=lambda x: x[1], reverse=True)

    W      = 44
    medals = ["(1)", "(2)", "(3)"]

    def top_():  return f"  ╔{'═' * W}╗"
    def bot_():  return f"  ╚{'═' * W}╝"
    def mid_():  return f"  ╠{'═' * W}╣"
    def row_(t): return f"  ║ {t:<{W-2}} ║"
    def ctr_(t): return f"  ║{t:^{W}}║"

    lines = [top_(), ctr_("~ Daily Fame Gains (24h) ~"), mid_()]

    if not board:
        lines.append(ctr_("Nobody gained fame today... get off Discord and play!! 😤"))
    else:
        lines.append(row_(f"{'Player':<18} {'24h Gained':>14}"))
        lines.append(mid_())
        for i, (name, gained) in enumerate(board[:15]):
            medal = medals[i] if i < 3 else f"({i+1})"
            lines.append(row_(f"{medal} {name[:16]:<16} {gained:>14,}"))

    lines.append(bot_())
    age = _cache_age_str(_fame_cache["timestamp"])
    await ctx.send(f"```\n" + "\n".join(lines) + f"\n```\n*Last updated: {age}*")


# ── !gweekly ──────────────────────────────────────────────────────────────────
@bot.command(name="gweekly")
async def gweekly(ctx):
    """Last 7 days seasonal fame gains per member."""
    await ctx.send("Checking this week's fame! Let's see who's been putting in the hours... 📊")

    members = await _get_roster()
    if not members:
        await ctx.send("Oof... couldn't load the roster. RealmScope might be having a moment. Try again? 😬")
        return
    member_names = [m["name"] for m in members]

    results = await asyncio.get_event_loop().run_in_executor(
        None, rs.get_guild_seasonal_fame, member_names
    )

    board = [(r["name"], r["weekly"]) for r in results
             if not r.get("failed") and r["weekly"] > 0]
    board.sort(key=lambda x: x[1], reverse=True)

    W      = 44
    medals = ["(1)", "(2)", "(3)"]

    def top_():  return f"  ╔{'═' * W}╗"
    def bot_():  return f"  ╚{'═' * W}╝"
    def mid_():  return f"  ╠{'═' * W}╣"
    def row_(t): return f"  ║ {t:<{W-2}} ║"
    def ctr_(t): return f"  ║{t:^{W}}║"

    lines = [top_(), ctr_("~ Weekly Fame Gains (7 days) ~"), mid_()]

    if not board:
        lines.append(ctr_("No fame gained in the last 7 days"))
    else:
        lines.append(row_(f"{'Player':<18} {'7d Gained':>14}"))
        lines.append(mid_())
        for i, (name, gained) in enumerate(board[:15]):
            medal = medals[i] if i < 3 else f"({i+1})"
            lines.append(row_(f"{medal} {name[:16]:<16} {gained:>14,}"))

    lines.append(bot_())
    await ctx.send("```\n" + "\n".join(lines) + "\n```")


# ── !gshinies ─────────────────────────────────────────────────────────────────
@bot.command(name="gshinies")
async def gshinies(ctx, *, item_name: str = ""):
    """
    !gshinies          — Seasonal shiny leaderboard (from guild roster)
    !gshinies <item>   — Who in the guild has obtained a specific shiny
    """
    if item_name:
        # Specific shiny search — need to check individual shiny pages
        await ctx.send(f"Ooh, hunting for **{item_name}** shiny across the whole guild!! Give me a bit... ✨")

        members = await _get_roster()
        if not members:
            await ctx.send("Oof... couldn't load the roster. RealmScope might be having a moment. Try again? 😬")
            return
        member_names = [m["name"] for m in members]

        # Fetch shiny pages concurrently
        import concurrent.futures
        def check_shiny(name):
            try:
                data = rs.get_shiny_data(name)
                if not data:
                    return name, []
                matches = []
                for season in data.get("seasons", []):
                    for item in season.get("items", []):
                        if item_name.lower() in item.get("name", "").lower():
                            matches.append({
                                "item":   item["name"],
                                "date":   item.get("obtained_date", "?"),
                                "season": season.get("season", "?"),
                            })
                return name, matches
            except Exception:
                return name, []

        found = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
            futures = {ex.submit(check_shiny, n): n for n in member_names}
            for fut in concurrent.futures.as_completed(futures):
                name, matches = fut.result()
                for m in matches:
                    found.append((name, m["item"], m["date"]))

        found.sort(key=lambda x: x[2])  # sort by date

        W      = 52
        medals = ["(1)", "(2)", "(3)"]

        def top_():  return f"  ╔{'═' * W}╗"
        def bot_():  return f"  ╚{'═' * W}╝"
        def mid_():  return f"  ╠{'═' * W}╣"
        def row_(t): return f"  ║ {t:<{W-2}} ║"
        def ctr_(t): return f"  ║{t:^{W}}║"

        lines = [top_(), ctr_(f"~ Shiny: {item_name.title()} ~"), mid_()]

        if not found:
            lines.append(ctr_(f"Nobody has it yet... it's still out there waiting 👀"))
        else:
            lines.append(row_(f"{'Player':<18} {'Item':<22} {'Date':>8}"))
            lines.append(mid_())
            for i, (name, item, date) in enumerate(found):
                medal = medals[i] if i < 3 else f"({i+1})"
                item_s = item[:20] if len(item) > 20 else item
                lines.append(row_(f"{medal} {name[:16]:<16} {item_s:<22} {date:>8}"))

        lines.append(bot_())
        await ctx.send("```\n" + "\n".join(lines) + "\n```")

    else:
        # General seasonal shiny leaderboard — from guild roster (fast)
        await ctx.send("Compiling the shiny leaderboard!! Who's been the luckiest this season? ✨")

        async with selenium_lock:
            members = await asyncio.get_event_loop().run_in_executor(
                None, rs.get_guild_roster, "TheAtheneum"
            )

        if not members:
            await ctx.send("Oof... couldn't load the roster. RealmScope might be having a moment. Try again? 😬")
            return

        # seasonal_shinies comes from get_player_info, not roster
        # Use get_player_info concurrently for seasonal shiny count
        import concurrent.futures

        def get_seasonal_shinies(name):
            try:
                info = rs.get_player_info(name)
                return name, info["seasonal_shinies"] if info else 0
            except Exception:
                return name, 0

        shiny_counts = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            futures = {ex.submit(get_seasonal_shinies, m["name"]): m["name"]
                      for m in members}
            for fut in concurrent.futures.as_completed(futures):
                name, count = fut.result()
                shiny_counts[name] = count

        board = sorted(shiny_counts.items(), key=lambda x: x[1], reverse=True)
        board = [(n, c) for n, c in board if c > 0]

        W      = 40
        medals = ["(1)", "(2)", "(3)"]

        def top_():  return f"  ╔{'═' * W}╗"
        def bot_():  return f"  ╚{'═' * W}╝"
        def mid_():  return f"  ╠{'═' * W}╣"
        def row_(t): return f"  ║ {t:<{W-2}} ║"
        def ctr_(t): return f"  ║{t:^{W}}║"

        lines = [top_(), ctr_("~ Seasonal Shiny Leaderboard ~"), mid_()]

        if not board:
            lines.append(ctr_("No seasonal shinies yet!! Season just started?? 👀"))
        else:
            lines.append(row_(f"{'Player':<18} {'Seasonal Shinies':>16}"))
            lines.append(mid_())
            for i, (name, count) in enumerate(board[:15]):
                medal = medals[i] if i < 3 else f"({i+1})"
                lines.append(row_(f"{medal} {name[:16]:<16} {count:>16}"))

        lines.append(bot_())
        await ctx.send("```\n" + "\n".join(lines) + "\n```")


# ── !gtop ─────────────────────────────────────────────────────────────────────
@bot.command(name="gtop")
async def gtop(ctx, n: int = 10):
    """Top N guild members by seasonal fame."""
    n = min(max(n, 3), 25)
    await ctx.send(f"Getting the top {n}!! One sec... 🏆")

    members = await _get_roster()

    if not members:
        await ctx.send("Oof... couldn't load the roster. RealmScope might be having a moment. Try again? 😬")
        return

    members.sort(key=lambda m: m["seasonal_fame"], reverse=True)
    top_n   = members[:n]
    medals  = ["(1)", "(2)", "(3)"]
    W       = 44

    def top_():  return f"  ╔{'═' * W}╗"
    def bot_():  return f"  ╚{'═' * W}╝"
    def mid_():  return f"  ╠{'═' * W}╣"
    def row_(t): return f"  ║ {t:<{W-2}} ║"
    def ctr_(t): return f"  ║{t:^{W}}║"

    lines = [top_(), ctr_(f"~ Top {n} — Seasonal Fame ~"), mid_()]
    lines.append(row_(f"{'Player':<18} {'Seasonal Fame':>14}"))
    lines.append(mid_())

    for i, m in enumerate(top_n):
        medal = medals[i] if i < 3 else f"({i+1})"
        name  = m["name"][:16]
        sf    = f"{m['seasonal_fame']:,}"
        lines.append(row_(f"{medal} {name:<16} {sf:>14}"))

    lines.append(bot_())
    age = _cache_age_str(_roster_cache["timestamp"])
    await ctx.send(f"```\n" + "\n".join(lines) + f"\n```\n*Last updated: {age}*")



@bot.command(name="refresh")
async def refresh(ctx):
    """Force refresh the roster and fame cache."""
    _roster_cache["timestamp"] = 0
    _fame_cache["timestamp"]   = 0
    await ctx.send("Cache wiped!! 🔄 I'll grab fresh data on the next command — nice and clean! You're welcome btw")



# ── !gannounce ────────────────────────────────────────────────────────────────
@bot.command(name="gannounce")
async def gannounce(ctx):
    """Manually trigger the daily announcement to #leaderboards."""
    await post_daily_announcement()


# ── Daily announcement ────────────────────────────────────────────────────────
async def post_daily_announcement():
    lb_channel = discord.utils.get(bot.get_all_channels(), name="leaderboards")
    if not lb_channel:
        print("Could not find #leaderboards channel")
        return

    # Reuse the same fast roster fetch
    async with selenium_lock:
        members = await asyncio.get_event_loop().run_in_executor(
            None, rs.get_guild_roster, "TheAtheneum"
        )
    if not members:
        return

    members.sort(key=lambda m: m["seasonal_fame"], reverse=True)

    # Also get daily/weekly gains
    member_names = [m["name"] for m in members]
    fame_results = await asyncio.get_event_loop().run_in_executor(
        None, rs.get_guild_seasonal_fame, member_names
    )
    daily_board = sorted(
        [(r["name"], r["daily"]) for r in fame_results
         if not r.get("failed") and r["daily"] > 0],
        key=lambda x: x[1], reverse=True
    )

    PST     = pytz.timezone("America/New_York")
    now_str = datetime.now(PST).strftime("%B %d, %Y")

    W      = 46
    medals = ["(1)", "(2)", "(3)"]

    def top_():  return f"  ╔{'═' * W}╗"
    def bot_():  return f"  ╚{'═' * W}╝"
    def mid_():  return f"  ╠{'═' * W}╣"
    def div_():  return f"  ╟{'─' * W}╢"
    def row_(t): return f"  ║ {t:<{W-2}} ║"
    def ctr_(t): return f"  ║{t:^{W}}║"

    # Build full announcement as one message
    lines = []
    lines.append(top_())
    lines.append(ctr_("~ THE ATHENEUM DAILY REPORT ~"))
    lines.append(ctr_(now_str))
    lines.append(mid_())
    lines.append(ctr_("SEASONAL FAME STANDINGS"))
    lines.append(mid_())
    lines.append(row_(f"{'Player':<18} {'Seasonal Fame':>14}  {'Fame':>8}"))
    lines.append(mid_())
    for i, m in enumerate(members[:10]):
        medal = medals[i] if i < 3 else f"({i+1})"
        lines.append(row_(
            f"{medal} {m['name'][:16]:<16} "
            f"{m['seasonal_fame']:>14,}  "
            f"{m['fame']:>8,}"
        ))

    if daily_board:
        lines.append(div_())
        lines.append(ctr_("TODAY'S TOP GAINERS"))
        lines.append(div_())
        for i, (name, gained) in enumerate(daily_board[:5]):
            medal = medals[i] if i < 3 else f"({i+1})"
            lines.append(row_(f"{medal} {name[:16]:<16} +{gained:>14,}"))

    lines.append(bot_())

    await lb_channel.send("```\n" + "\n".join(lines) + "\n```")

    print(f"Daily announcement posted for {now_str}")

@bot.command(name="gstats")
async def gstats(ctx, player_name: str):
    await ctx.send(f"Looking up **{player_name}**'s stats!! Give me a moment... 📊")

    info, fame_history = await asyncio.gather(
        asyncio.get_event_loop().run_in_executor(None, rs.get_player_info, player_name),
        asyncio.get_event_loop().run_in_executor(
            None, rs.get_player_seasonal_fame_history, player_name, 2
        ),
    )

    if not info:
        await ctx.send(f"Hmm... couldn't find **{player_name}** on RealmScope. Private profile or typo? 😅")
        return

    daily_seasonal  = fame_history["daily"]         if fame_history else 0
    weekly_seasonal = fame_history["weekly"]        if fame_history else 0
    total_seasonal  = fame_history["current_total"] if fame_history else info.get("seasonal_fame", 0)

    W = 36
    def line(text=""): return f"    |{text:^{W}}|."
    def sline(label, value):
        content = f" {label}: {value}"
        if len(content) > W:
            return [
                f"    | {label}:{' ' * (W - len(label) - 2)}|.",
                f"    |   {str(value):>{W-4}}|."
            ]
        return [f"    |{content:<{W}}|."]
    def div(): return f"    |{'~' * W}|."

    guild_rank = info.get("guild_rank") or "Member"

    scroll = []
    scroll.append(f"   {'_' * W}")
    scroll.append(f" / \\{' ' * W}\\.")
    scroll.append(f"|   |{' ' * W}|.")
    scroll.append(line("~ GUILD STATS ~"))
    scroll.append(f" \\_ |{info['name']:^{W}}|.")
    scroll.append(line(guild_rank))
    scroll.append(line())
    scroll.append(div())
    scroll.append(line())
    scroll += sline("Fame",          f"{info.get('total_fame', 0):,}")
    scroll.append(line())
    scroll += sline("Seasonal Fame", f"{total_seasonal:,}")
    scroll += sline("  Today",       f"+{daily_seasonal:,}")
    scroll += sline("  This Week",   f"+{weekly_seasonal:,}")
    scroll.append(line())
    scroll.append(div())
    scroll.append(line())
    scroll += sline("Stars",         info.get("stars", 0))
    scroll += sline("Exaltations",   info.get("exaltations", 0))
    scroll += sline("Skins",         info.get("skins", 0))
    scroll += sline("Shinies",       info.get("total_shinies", 0))
    scroll.append(line())
    scroll.append(f"    |   {'_' * W}|___")
    scroll.append(f"    |  /{' ' * W}/.")
    scroll.append(f"    \\_/{'_' * W}/.")

    await ctx.send("```\n" + "\n".join(scroll) + "\n```")

@bot.command(name="newseason")
async def newseason(ctx):
    """Marks the start of a new season for tracking."""
    gs.set_season_start()
    await ctx.send("New season marked!! 🎉 Delta tracking resets from right now — let the grind begin!! May the best realmie win and all that 🏆")


@bot.command(name="seasonrace")
async def seasonrace(ctx):
    """Shows seasonal fame gained since the season start was marked."""
    snap_new    = gs.get_latest_snapshot()
    snap_season = gs.get_season_start_snapshot()
    if not snap_new:
        await ctx.send("No snapshot data yet... run `!snapshot` first! 📊")
        return
    if not snap_season:
        await ctx.send("No season start recorded yet! Use `!newseason` to mark when the race begins 🏁")
        return
    entries = gs.delta_leaderboard(snap_season, snap_new, "seasonal_fame")
    await ctx.send(_leaderboard_msg(
        "~ Season Fame Race ~", entries, "Seasonal Fame", show_delta=True
    ))
# ── Guild event competition commands (disabled — not in use) ──────────
# Uncomment this block + import guild_events as ge to re-enable.
# async def run_event_leaderboards(): ...



@bot.command(name="testdeath")
async def testdeath(ctx):
    """Fetch the latest death and post it as a card to test the death announcer."""
    import death_card as dc
    await ctx.send("Testing the death card... spooky 💀 Give me a sec...")
    try:
        deaths = dc.fetch_latest_deaths(guild)
        if not deaths:
            await ctx.send("No recent deaths found... the guild is alive!! For now 😬")
            return
        latest = deaths[0]
        await ctx.send(f"*(debug)* Found: **{latest['player-name']}** (class_id: `{latest.get('class_id', '?')}`) killed by **{latest['killed_by']}**")
        img_path = dc.build_death_card(latest)
        await ctx.send(file=discord.File(img_path))
    except Exception as e:
        await ctx.send(f"❌ Error: {e}")
        raise


@bot.command(name="drecent")
async def drecent(ctx):
    """Show the last 5 guild deaths as death cards."""
    import death_card as dc
    await ctx.send("Pulling up the graveyard... 💀 give me a second, this might take a moment!")
    try:
        deaths = dc.fetch_latest_deaths(guild)
        if not deaths:
            await ctx.send("No recent deaths! The guild is thriving 😮 ...for now.")
            return
        recent = deaths[:5]
        await ctx.send(f"Found **{len(recent)}** recent death(s) — here they are, RIP 😔")
        loop = asyncio.get_event_loop()
        for i, death in enumerate(recent):
            try:
                out_path = f"./images/death_cmd_{i}.png"
                img_path = await loop.run_in_executor(
                    None, lambda d=death, p=out_path: dc.build_death_card(d, p)
                )
                await ctx.send(file=discord.File(img_path))
            except Exception as e:
                await ctx.send(f"Couldn't build the card for **{death.get('player-name', '?')}** 😭")
                print(f"drecent card error: {e}")
    except Exception as e:
        await ctx.send("Couldn't pull the graveyard... RealmEye might be napping 😴")
        print(f"drecent error: {e}")


@bot.command(name="dtop")
async def dtop(ctx):
    """Top guild deaths this week by base fame, with total fame contributed."""
    import death_card as dc
    from datetime import datetime, timezone, timedelta

    await ctx.send("Checking this week's graveyard hall of fame... 💀📊 one moment!")
    try:
        deaths = dc.fetch_latest_deaths(guild)
        if not deaths:
            await ctx.send("No deaths found! Either everyone is immortal, or RealmEye is napping 😴")
            return

        now_utc   = datetime.now(timezone.utc)
        week_ago  = now_utc - timedelta(days=7)

        def _fame(s) -> int:
            try:
                return int(str(s).replace(" ", "").replace(",", "").replace("\xa0", ""))
            except Exception:
                return 0

        def _parse_dt(raw: str):
            try:
                s = raw.strip()
                if s.endswith("Z"):
                    s = s[:-1] + "+00:00"
                return datetime.fromisoformat(s)
            except Exception:
                return None

        week_deaths = [d for d in deaths if (t := _parse_dt(d.get("time", ""))) and t >= week_ago]

        if not week_deaths:
            await ctx.send("No deaths this week! Everyone's been suspiciously careful 🤔")
            return

        week_deaths.sort(key=lambda d: _fame(d.get("base_fame", 0)), reverse=True)
        total_base  = sum(_fame(d.get("base_fame",  0)) for d in week_deaths)
        total_total = sum(_fame(d.get("total_fame", 0)) for d in week_deaths)
        top = week_deaths[:5]

        embed = discord.Embed(
            title="💀  This Week's Hall of Fallen Heroes",
            description=(
                f"**{len(week_deaths)}** guild member(s) fell this week.\n"
                f"All those deaths contributed **{total_base:,}** base fame — ouch 😬\n"
                f"Total fame lost: **{total_total:,}** — rest in peace, legends 🪦"
            ),
            color=0xC0392B
        )
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        for i, d in enumerate(top):
            bf = _fame(d.get("base_fame", 0))
            tf = _fame(d.get("total_fame", 0))
            embed.add_field(
                name=f"{medals[i]}  {d['player-name']}",
                value=(
                    f"**{bf:,}** base fame · **{tf:,}** total\n"
                    f"Killed by: {d['killed_by']}\n"
                    f"🕐 {dc.format_death_time(d['time'])}"
                ),
                inline=False
            )
        embed.set_footer(text="Guill the Intern™  ·  !drecent for the last 5 death cards")
        await ctx.send(embed=embed)

        # Post death cards for the top 3
        await ctx.send("And here are the death cards for the top fallen heroes this week:")
        loop = asyncio.get_event_loop()
        for i, death in enumerate(top[:3]):
            try:
                out_path = f"./images/death_top_{i}.png"
                img_path = await loop.run_in_executor(
                    None, lambda d=death, p=out_path: dc.build_death_card(d, p)
                )
                await ctx.send(file=discord.File(img_path))
            except Exception as e:
                print(f"dtop card error: {e}")

    except Exception as e:
        await ctx.send("Something went wrong pulling the graveyard 😭 Try again in a bit!")
        print(f"dtop error: {e}")


# ── Guild event competition commands (disabled — not in use) ──────────
# !trackable, !eventadd, !events, !event, !eventend, !eventall
# To re-enable: uncomment this section and add "import guild_events as ge"


@bot.command(name="build")
async def build(ctx, class_name: str = "", stat: str = ""):
    import re
    class_name = class_name.lower().strip()
    stat       = stat.lower().strip()

    all_classes_set = set(bs.CLASS_BUILDS.keys()) | set(bs.SSNL_CLASS_MAP.keys())

    # ── No class given → usage + full class list ──────────────────────────────
    if not class_name:
        all_classes = sorted(all_classes_set)
        await ctx.send(
            "Oops! Tell me which class (and optionally a stat) 😅\n"
            "**Usage:** `!build <class> [stat]`\n"
            "**Examples:** `!build wizard attack` · `!build sorcerer hp` · `!build knight defense`\n"
            f"**Classes:** `{'`, `'.join(all_classes)}`\n"
            "**DPS stats:** `attack`, `defense`, `speed`, `vitality`, `wisdom`, `mana`\n"
            "**All 8 stat builds:** `hp`, `mp`, `attack`, `defense`, `speed`, `dexterity`, `vitality`, `wisdom`"
        )
        return

    # ── Invalid class ─────────────────────────────────────────────────────────
    if class_name not in all_classes_set:
        close = sorted(c for c in all_classes_set if class_name in c or c.startswith(class_name[:3]))
        hint  = f"\nDid you mean: `{'`, `'.join(close)}`?" if close else ""
        await ctx.send(
            f"Hmm... `{class_name}` doesn't ring a bell!{hint}\n"
            f"Type `!build` to see all available classes 📋"
        )
        return

    available_dps  = bs.CLASS_BUILDS.get(class_name, {})
    is_single_dps  = available_dps and list(available_dps.keys()) == ["general"]

    # Warrior special case: no stat → run general DPS build immediately
    if is_single_dps and not stat:
        stat = "general"

    # ── No stat given → show options table ───────────────────────────────────
    if not stat:
        W = 50
        def top():  return f"  ╔{'═' * W}╗"
        def bot_(): return f"  ╚{'═' * W}╝"
        def mid():  return f"  ╠{'═' * W}╣"
        def div():  return f"  ╟{'─' * W}╢"
        def row(t): return f"  ║ {t:<{W-2}} ║"
        def ctr(t): return f"  ║{t:^{W}}║"

        lines = [top(), ctr(f"~ {class_name.title()} Build Options ~"), mid()]

        if available_dps:
            lines.append(row("DPS Leaderboard Builds:"))
            lines.append(div())
            for sname, kdata in available_dps.items():
                lines.append(row(f"  !build {class_name} {sname:<12}  [{kdata['key']}]"))
            lines.append(mid())

        covered = {bs.DPS_TO_SSNL.get(k) for k in available_dps} - {None}
        ssnl_opts = [(inp, disp) for inp, disp in bs.SSNL_STATS_DISPLAY if disp not in covered]
        lines.append(row("SSNL Stat Leaderboard Builds:"))
        lines.append(div())
        for inp, disp in ssnl_opts:
            lines.append(row(f"  !build {class_name} {inp:<12}  ({disp})"))

        lines.append(bot_())
        await ctx.send("```\n" + "\n".join(lines) + "\n```")
        return

    # ── Route: DPS or SSNL? ───────────────────────────────────────────────────
    use_dps  = stat in available_dps
    use_ssnl = (not use_dps) and (stat in bs.SSNL_STAT_MAP)

    if not use_dps and not use_ssnl:
        covered  = {bs.DPS_TO_SSNL.get(k) for k in available_dps} - {None}
        dps_list = list(available_dps.keys())
        ssnl_list = [inp for inp, disp in bs.SSNL_STATS_DISPLAY if disp not in covered]
        await ctx.send(
            f"Hmm, `{stat}` isn't a valid stat for **{class_name.title()}** 🤔\n"
            + (f"**DPS stats:** `{'`, `'.join(dps_list)}`\n" if dps_list else "")
            + f"**Stat builds:** `{'`, `'.join(ssnl_list)}`\n"
            f"Try `!build {class_name}` to see all options!"
        )
        return

    def img_to_file(img, filename):
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return discord.File(buf, filename=filename)

    W_   = 46
    def top_():  return f"  ╔{'═' * W_}╗"
    def bot__(): return f"  ╚{'═' * W_}╝"
    def mid_():  return f"  ╠{'═' * W_}╣"
    def row_(t): return f"  ║ {t:<{W_-2}} ║"
    def ctr_(t): return f"  ║{t:^{W_}}║"

    if use_dps:
        # ── DPS PATH ─────────────────────────────────────────────────────────
        build_key_data = available_dps[stat]
        is_support     = class_name in bs.SUPPORT_CLASSES
        display_stat   = "" if stat == "general" else f" {stat.title()}"

        await ctx.send(f"Pulling up **{class_name.title()}{display_stat}** builds from the DPS leaderboard!! One moment... ⚔️")

        data = await asyncio.get_event_loop().run_in_executor(
            None, bs.fetch_build_data, build_key_data, 15
        )
        if not data or not data.get("rows"):
            await ctx.send(
                "Hmm... couldn't grab the DPS build data right now 😓\n"
                "RealmShark might be down — try again in a bit!"
            )
            return

        rows     = data["rows"]
        meta     = data.get("meta", {})
        analysis = bs.analyze_builds(rows)

        def make_avg_dps():
            return bi.build_tier_image(
                tier_label   = f"~ AVERAGE BUILD  (Top {len(rows)} Consensus)",
                items        = analysis["avg_items"],
                enchants     = analysis["top_enchants"],
                alt_enchants = analysis["alt_enchants"],
                dps          = analysis["stat_avgs"].get("dps", 0),
                total_dmg    = analysis["stat_avgs"].get("totalDamage", 0),
                swap_items   = analysis["swap_items"],
                is_support   = is_support,
            )

        avg_img    = await asyncio.get_event_loop().run_in_executor(None, make_avg_dps)
        season_str = meta.get("season", bs.get_current_season()).upper()

        notes      = meta.get("notes", [])
        build_desc = notes[0] if notes else ""
        build_desc = re.sub(
            r'\.\s*(Weapon DPS.*|Exalt.*|Ability activations.*)',
            '', build_desc, flags=re.IGNORECASE
        ).strip().rstrip(".")

        lines = [top_(), ctr_(f"~ {class_name.title()}{display_stat} Build ~"),
                 ctr_(f"Top {len(rows)}  |  Season {season_str}  |  DPS Leaderboard"), mid_()]
        if build_desc:
            lines.append(row_(build_desc[:W_-2]))
        lines.append(bot__())

        await ctx.send("```\n" + "\n".join(lines) + "\n```")
        await ctx.send(file=img_to_file(avg_img, f"avg_{class_name}_{stat}.png"))

    else:
        # ── SSNL PATH ─────────────────────────────────────────────────────────
        ssnl_stat  = bs.SSNL_STAT_MAP[stat]
        ssnl_class = bs.SSNL_CLASS_MAP[class_name]

        await ctx.send(
            f"Pulling up **{class_name.title()} {ssnl_stat}** builds from the SSNL leaderboard!! "
            f"One moment... 📊"
        )

        data = await asyncio.get_event_loop().run_in_executor(
            None, bs.fetch_ssnl_data, ssnl_class, ssnl_stat
        )
        if not data or not data.get("rows"):
            await ctx.send(
                f"Couldn't find any data for **{class_name.title()} {ssnl_stat}** right now 😓\n"
                "The leaderboard might be empty or the tracker might be down — try again in a bit!"
            )
            return

        rows     = data["rows"]
        analysis = bs.analyze_builds(rows)

        top_val    = rows[0].get("statValue", 0) if rows else 0
        stats_line = f"Best {ssnl_stat}: {top_val:,}  (Top {len(rows)} {ssnl_class}s  |  SSNL)"

        def make_avg_ssnl():
            return bi.build_tier_image(
                tier_label   = f"~ AVERAGE BUILD  (Top {len(rows)} {ssnl_stat})",
                items        = analysis["avg_items"],
                enchants     = analysis["top_enchants"],
                alt_enchants = analysis["alt_enchants"],
                dps          = 0,
                total_dmg    = 0,
                swap_items   = analysis["swap_items"],
                is_support   = False,
                stats_line   = stats_line,
            )

        avg_img    = await asyncio.get_event_loop().run_in_executor(None, make_avg_ssnl)
        season_str = bs.get_current_season().upper()

        lines = [top_(), ctr_(f"~ {class_name.title()} {ssnl_stat} Build ~"),
                 ctr_(f"Top {len(rows)}  |  Season {season_str}  |  SSNL Leaderboard"), mid_(),
                 row_(f"Avg build from top {len(rows)} {ssnl_class}s by {ssnl_stat}"),
                 bot__()]

        await ctx.send("```\n" + "\n".join(lines) + "\n```")
        await ctx.send(file=img_to_file(avg_img, f"avg_{class_name}_{stat}.png"))


@bot.command(name="find")
async def find_event(ctx, *, query: str = ""):
    if not query:
        await ctx.send(
            "Tell me what to search for!! 🔍\n"
            "**Usage:** `!find <event / dungeon / item>`\n"
            "• `!find cube` — active Cube Gods\n"
            "• `!find shatters` — events dropping The Shatters portal\n"
            "• `!find juggernaut` — events dropping that white bag item\n"
            "• `!find o3` — top realms closest to O3\n"
            "• `!find alien` — Alien Invasion events"
        )
        return

    await ctx.send(f"On it!! Scanning the realms for **{query}**... 🔍")

    result = await asyncio.get_event_loop().run_in_executor(
        None, et.find_event, query
    )

    rtype = result.get("type")

    if rtype == "error":
        await ctx.send(f"Ugh, something went wrong: {result['message']} 😓")
        return

    # ── Ambiguous query (e.g. "alien" matches multiple events) ───────────────
    if rtype == "ambiguous":
        options = result.get("options", [])
        opts_str = "\n".join(f"• `!find {o}`" for o in options)
        await ctx.send(
            f"Hmm, **{query}** could mean a few things! Which one did you mean? 🤔\n{opts_str}"
        )
        return

    # ── No match — show suggestions ───────────────────────────────────────────
    if rtype == "no_match":
        suggestions = result.get("suggestions", [])
        if suggestions:
            sugg_str = ", ".join(f"`{s}`" for s in suggestions)
            await ctx.send(
                f"Couldn't find **{query}** — did you mean: {sugg_str}?\n"
                f"Try `!find <event name>` with the full name!"
            )
        else:
            await ctx.send(
                f"Hmm... I don't know what **{query}** is 🤔\n"
                f"Try an event name, dungeon name, or white bag item — or `!find o3` for realm scores!"
            )
        return

    is_o3        = rtype == "o3"
    results      = result["results"]
    query_name   = "O3 Realm Scores" if is_o3 else result.get("query_name", query)
    search_mode  = result.get("search_mode", "event")
    possible     = result.get("possible_events", [])
    drops        = result.get("drops", {})

    # Title varies by mode
    if is_o3:
        title = "~ O3 Watch — Top Realm Scores ~"
    elif search_mode == "dungeon":
        title = f"~ Events Dropping: {query_name} ~"
    elif search_mode == "item":
        title = f"~ Events Dropping: {query_name} ~"
    else:
        title = f"~ {query_name} — Active Events ~"

    # ── No active results ─────────────────────────────────────────────────────
    if not results:
        if possible and search_mode == "dungeon":
            evts = "\n".join(f"• **{e}** — `!find {e.lower().replace(' ', '')}`" for e in possible[:6])
            await ctx.send(
                f"**{query_name}** portal isn't active right now! 🌀\n"
                f"These events can drop it — check back when one's up:\n{evts}"
            )
        elif possible and search_mode == "item":
            evts = "\n".join(f"• **{e}** — `!find {e.lower().replace(' ', '')}`" for e in possible[:6])
            await ctx.send(
                f"No active events dropping **{query_name}** right now! 🎒\n"
                f"Events that can drop it:\n{evts}"
            )
        else:
            suggestions = et.get_suggestions(query)
            if suggestions:
                sugg_str = ", ".join(f"`{s}`" for s in suggestions)
                await ctx.send(
                    f"No active **{query_name}** found right now. 🌍\n"
                    f"*(Similar events: {sugg_str})*"
                )
            else:
                await ctx.send(
                    f"No active **{query_name}** found right now. 🌍 Maybe check back later!"
                )
        return

    def make_img():
        return ei.build_event_image(
            results,
            title,
            is_o3=is_o3,
            drops=drops if not is_o3 else None,
            search_mode=search_mode,
            possible_events=possible,
        )

    img = await asyncio.get_event_loop().run_in_executor(None, make_img)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    fname = f"find_{query.replace(' ', '_')}.png"
    if is_o3:
        await ctx.send("Here are the hottest realms — ranked by score **and** population! 🔥", file=discord.File(buf, filename=fname))
    else:
        await ctx.send(file=discord.File(buf, filename=fname))


@bot.command(name="leaderboards")
async def leaderboards(ctx):
    """Send a pinnable overview of all leaderboard and stat commands."""
    embed = discord.Embed(
        title="📋 The Atheneum — Command Guide",
        description=(
            "*Hi!! I'm Guill, your friendly (and honestly quite underappreciated) guild intern.*\n"
            "*Here's a quick overview — use `!commands` for the full list, or `!help <command>` for details on any specific one!*"
        ),
        color=0x8e44ad
    )

    embed.add_field(
        name="👤 Player Lookup",
        value=(
            "`!player <name>` — Full profile scroll\n"
            "`!search <name>` — Recruitment card\n"
            "`!characters <name>` — Characters & gear\n"
            "`!shinies <name>` — Shiny collection\n"
            "`!gstats <name>` — Stat deltas"
        ),
        inline=True
    )

    embed.add_field(
        name="🏰 Guild Roster",
        value=(
            "`!groster` — Full guild roster\n"
            "`!online` — Who's online\n"
            "`!afk` — Offline 30+ days\n"
            "`!gdiscord` — Roster vs Discord\n"
            "`!gparty` / `!parties` — Party info"
        ),
        inline=True
    )

    embed.add_field(
        name="📊 Fame & Leaderboards",
        value=(
            "`!gseason [n]` — Season fame board\n"
            "`!gtop [n]` — Top N members\n"
            "`!gdaily` — Today's gains\n"
            "`!gweekly` — This week's gains\n"
            "`!gshinies [item]` — Shiny board"
        ),
        inline=True
    )

    embed.add_field(
        name="⚔️ Build & Items",
        value=(
            "`!build <class> [stat]` — DPS builds\n"
            "`!item <name>` — Item wiki lookup\n"
            "`!find <event>` — Active realm events\n"
            "`!find o3` — O3 realm scores"
        ),
        inline=True
    )

    embed.add_field(
        name="💀 Deaths",
        value=(
            "`!drecent` — Last 5 death cards\n"
            "`!dtop` — Top deaths this week\n"
            "`!testdeath` — Test death card"
        ),
        inline=True
    )

    embed.add_field(
        name="🎲 Trivia",
        value=(
            "`!trivia start [diff] [n]` — Start a round\n"
            "`!trivia quick` — Single question\n"
            "`!trivia scores` — Leaderboard\n"
            "`!trivia add ...` — Submit a question"
        ),
        inline=True
    )

    embed.set_footer(text="The Atheneum · Guill the Intern™ · !commands for the full list · !help <command> for details")
    await ctx.send(embed=embed)


_trivia_active   = False
_trivia_stop     = [False]   # mutable flag passed into run_trivia_round
_trivia_task     = None


# ── Auto trivia task ──────────────────────────────────────────────────────────
AUTO_TRIVIA_CHANNEL = "guild-chat"  # change to whatever channel name you want
AUTO_TRIVIA_MINUTES = 180              # how often to post a question

@tasks.loop(minutes=AUTO_TRIVIA_MINUTES)
async def auto_trivia_task():
    try:
        channel = discord.utils.get(bot.get_all_channels(), name=AUTO_TRIVIA_CHANNEL)
        if not channel or _trivia_active:
            return

        questions = ts.load_questions("all")
        if not questions:
            return

        q          = random.choice(questions)
        diff_emoji = ts.DIFFICULTY_EMOJI.get(q.get("difficulty", "medium"), "")
        diff       = q.get("difficulty", "medium")
        points     = ts.DIFFICULTY_CONFIG.get(diff, {}).get("points", 1)
        answers    = [a.lower().strip() for a in q["a"]]
        hint       = q.get("hint", "")

        await channel.send(
            f"🎲 **Auto Trivia time!!** {diff_emoji} — worth **{points}** pt{'s' if points != 1 else ''} — I picked this one myself!\n"
            f"**{q['q']}**\n"
            f"⏳ Open until someone gets it or 1 hour passes!"
        )

        # Send hint after 30 minutes
        hint_sent = False

        def check(msg):
            return (
                msg.channel == channel and
                not msg.author.bot and
                msg.content.lower().strip() in answers
            )

        start = asyncio.get_event_loop().time()
        while True:
            elapsed   = asyncio.get_event_loop().time() - start
            remaining = 3600 - elapsed  # 1 hour max

            if remaining <= 0:
                await channel.send(
                    f"⏰ Auto trivia expired!! Nobody got it... disappointing tbh.\n"
                    f"The answer was **{q['a'][0]}** — come on guys!!"
                )
                break

            # Send hint after 30 minutes
            if not hint_sent and hint and elapsed >= 1800:
                await channel.send(f"💡 **Hint:** {hint}")
                hint_sent = True

            try:
                msg = await bot.wait_for("message", check=check, timeout=60.0)
                winner = msg.author.display_name
                await channel.send(
                    f"✅ **{winner}** got it!! Great job!!\n"
                    f"The answer was **{q['a'][0]}** (+{points} pt{'s' if points != 1 else ''}) 🎉"
                )
                ts.add_score(winner, points, diff)
                break
            except asyncio.TimeoutError:
                continue  # keep waiting, check elapsed time

    except Exception as e:
        print(f"Auto trivia error: {e}")

@bot.command(name="trivia")
async def trivia(ctx, subcommand: str = "start", *, args: str = ""):
    global _trivia_active, _trivia_stop, _trivia_task

    # ── start ─────────────────────────────────────────────────────────────────
    if subcommand == "start":
        if _trivia_active:
            await ctx.send("A trivia round is already running!! Use `!trivia stop` to end it first 🛑")
            return

        # Parse: !trivia start [difficulty] [num_questions]
        parts      = args.strip().split() if args.strip() else []
        difficulty = "all"
        num_q      = 5
        valid_diff = list(ts.DIFFICULTY_CONFIG.keys()) + ["all"]

        for part in parts:
            if part.lower() in valid_diff:
                difficulty = part.lower()
            elif part.isdigit():
                num_q = max(1, min(int(part), 20))

        _trivia_active  = True
        _trivia_stop    = [False]

        async def run_and_clear():
            global _trivia_active
            try:
                await ts.run_trivia_round(
                    bot, ctx.channel,
                    difficulty=difficulty,
                    num_questions=num_q,
                    stop_flag=_trivia_stop,
                )
            except asyncio.CancelledError:
                pass
            finally:
                _trivia_active = False

        _trivia_task = bot.loop.create_task(run_and_clear())

    # ── quick ─────────────────────────────────────────────────────────────────
    elif subcommand == "quick":
        diff  = args.strip().lower() if args.strip() in ts.DIFFICULTY_CONFIG else "all"
        questions = ts.load_questions(diff)
        if not questions:
            await ctx.send("No questions found for that difficulty... I'll add more soon!! Maybe. 😅")
            return
        q = random.choice(questions)
        await ts.ask_question(bot, ctx.channel, q, 1, 1)

    # ── stop ──────────────────────────────────────────────────────────────────
    elif subcommand == "stop":
        if not _trivia_active:
            await ctx.send("No trivia round is running right now! Nothing to stop 🤷")
            return
        _trivia_stop[0] = True
        if _trivia_task:
            _trivia_task.cancel()
        _trivia_active = False
        await ctx.send("Trivia stopped!! 🛑 Alright, quiz time is over. For now...")

    # ── scores ────────────────────────────────────────────────────────────────
    elif subcommand == "scores":
        await ctx.send(ts.build_scores_scroll())

    # ── stats ─────────────────────────────────────────────────────────────────
    elif subcommand == "stats":
        player = args.strip() or ctx.author.display_name
        await ctx.send(ts.build_player_stats_scroll(player))

    # ── add ───────────────────────────────────────────────────────────────────
    elif subcommand == "add":
        # Format: !trivia add difficulty | category | Question? | answer | [alt answer] | [hint]
        # Example: !trivia add hard | Lore | Who built the Abyss of Demons? | malphas | hint text
        parts = [p.strip() for p in args.split("|")]
        if len(parts) < 4:
            await ctx.send(
                "Format: `!trivia add <difficulty> | <category> | <question> | <answer> | [alt answer] | [hint]`\n"
                "Difficulties: `easy` `medium` `hard` `expert`\n"
                "Categories: `General` `Events` `Dungeons` `Lore`\n"
                "Example: `!trivia add hard | Lore | Who built the Abyss of Demons? | malphas | the archdemon mason`"
            )
            return

        diff     = parts[0].lower()
        cat      = parts[1].title()
        question = parts[2]
        # Everything between question and last part = answers, last part = hint
        # If last part doesn't look like an answer (longer, descriptive) treat as hint
        answer_parts = parts[3:]
        hint         = ""
        # Heuristic: if last entry is longer than 30 chars and not the only answer, it's a hint
        if len(answer_parts) > 1 and len(answer_parts[-1]) > 30:
            hint         = answer_parts[-1]
            answer_parts = answer_parts[:-1]

        if diff not in ts.DIFFICULTY_CONFIG:
            await ctx.send(f"Invalid difficulty. Use: `{'`, `'.join(ts.DIFFICULTY_CONFIG.keys())}`")
            return

        new_q = {
            "difficulty": diff,
            "category":   cat,
            "q":          question,
            "a":          [a.lower().strip() for a in answer_parts],
            "hint":       hint,
        }
        ts.save_custom_question(new_q)
        all_q = ts.load_questions("all")
        await ctx.send(
            f"Question added!! Thanks for contributing!! 🎉 Total questions: **{len(all_q)}**\n"
            f"Preview: *{question}* → `{answer_parts[0]}`"
        )

    # ── list ──────────────────────────────────────────────────────────────────
    elif subcommand == "list":
        cat_filter = args.strip().title() if args.strip() else None
        questions  = ts.load_questions("all")

        # Count by category and difficulty
        counts = {}
        for q in questions:
            cat  = q.get("category", "General")
            diff = q.get("difficulty", "medium")
            if cat not in counts:
                counts[cat] = {k: 0 for k in ts.DIFFICULTY_CONFIG}
            counts[cat][diff] = counts[cat].get(diff, 0) + 1

        W = 50
        def top_():  return f"  ╔{'═' * W}╗"
        def bot_():  return f"  ╚{'═' * W}╝"
        def mid_():  return f"  ╠{'═' * W}╣"
        def row_(t): return f"  ║ {t:<{W-2}} ║"
        def ctr_(t): return f"  ║{t:^{W}}║"

        lines = [
            top_(),
            ctr_(f"~ Trivia Questions ({len(questions)} total) ~"),
            mid_(),
            row_(f"{'Category':<16} {'Easy':>6} {'Med':>6} {'Hard':>6} {'Expert':>8}"),
            mid_(),
        ]
        for cat, diff_counts in sorted(counts.items()):
            e = ts.CATEGORY_EMOJI.get(cat, "❓")
            lines.append(row_(
                f"{e} {cat:<14} "
                f"{diff_counts.get('easy',0):>6} "
                f"{diff_counts.get('medium',0):>6} "
                f"{diff_counts.get('hard',0):>6} "
                f"{diff_counts.get('expert',0):>8}"
            ))
        lines.append(mid_())
        lines.append(row_("Usage: !trivia start [difficulty] [num_questions]"))
        lines.append(row_("  e.g. !trivia start hard 10"))
        lines.append(bot_())
        await ctx.send("```\n" + "\n".join(lines) + "\n```")

    # ── help / default ────────────────────────────────────────────────────────
    else:
        W = 50
        def top_():  return f"  ╔{'═' * W}╗"
        def bot_():  return f"  ╚{'═' * W}╝"
        def mid_():  return f"  ╠{'═' * W}╣"
        def row_(t): return f"  ║ {t:<{W-2}} ║"
        def ctr_(t): return f"  ║{t:^{W}}║"

        lines = [
            top_(), ctr_("~ Trivia Commands ~"), mid_(),
            row_("!trivia start             Start 5-question mixed round"),
            row_("!trivia start easy 10     10 easy questions"),
            row_("!trivia start hard        5 hard questions"),
            row_("!trivia quick             One random question"),
            row_("!trivia quick expert      One expert question"),
            row_("!trivia stop              Stop active round"),
            row_("!trivia scores            All-time leaderboard"),
            row_("!trivia stats <player>    Player's trivia stats"),
            row_("!trivia list              Browse question counts"),
            row_("!trivia add ...           Add a custom question"),
            mid_(),
            row_("Difficulties: easy  medium  hard  expert"),
            row_("Categories:   General  Events  Dungeons  Lore"),
            bot_(),
        ]
        await ctx.send("```\n" + "\n".join(lines) + "\n```")


@bot.command(name="gdiscord")
async def gdiscord(ctx):
    """
    Shows guild roster with join date and Discord membership status.
    Highlights members not in the Discord server.
    """
    await ctx.send("Cross-referencing the guild roster against our Discord members... I'm very thorough 🔍 This might take a moment!")

    # Get current roster
    async with selenium_lock:
        members = await asyncio.get_event_loop().run_in_executor(
            None, rs.get_guild_roster, "TheAtheneum"
        )
    if not members:
        await ctx.send("Oof... couldn't load the roster. RealmScope might be having a moment. Try again? 😬")
        return

    # Get join dates from history page
    await ctx.send("Now grabbing join dates... almost done! 📅")
    async with selenium_lock:
        join_dates = await asyncio.get_event_loop().run_in_executor(
            None, rs.get_guild_member_history, "TheAtheneum"
        )

    # Build Discord nickname set — use server nickname first, fall back to username
    discord_guild = ctx.guild
    discord_names = set()
    if discord_guild:
        for member in discord_guild.members:
            # Prefer server nickname, fall back to display name and username
            if member.nick:
                discord_names.add(member.nick.lower())
            discord_names.add(member.display_name.lower())
            discord_names.add(member.name.lower())

    # Build display data
    import datetime as dt_module
    now = int(time_module.time())

    def fmt_join(ts):
        if not ts:
            return "unknown"
        days = (now - ts) // 86400
        if days < 1:
            return "today"
        if days < 30:
            return f"{days}d ago"
        months = days // 30
        rem    = days % 30
        if rem == 0:
            return f"{months}mo ago"
        return f"{months}mo {rem}d ago"

    roster_data = []
    for m in members:
        name_lower  = m["name"].lower()
        in_discord  = name_lower in discord_names
        join_ts     = join_dates.get(name_lower, 0)
        roster_data.append({
            "name":       m["name"],
            "rank":       m["rank"],
            "in_discord": in_discord,
            "join_str":   fmt_join(join_ts),
            "join_ts":    join_ts,
        })

    # Sort: not in Discord first, then by join date oldest first
    roster_data.sort(key=lambda x: (x["in_discord"], -(x["join_ts"] or 0)))

    # Split into two sections: missing Discord and in Discord
    missing = [m for m in roster_data if not m["in_discord"]]
    present = [m for m in roster_data if m["in_discord"]]

    W = 52
    def top_():  return f"  ╔{'═' * W}╗"
    def bot_():  return f"  ╚{'═' * W}╝"
    def mid_():  return f"  ╠{'═' * W}╣"
    def div_():  return f"  ╟{'─' * W}╢"
    def row_(t): return f"  ║ {t:<{W-2}} ║"
    def ctr_(t): return f"  ║{t:^{W}}║"

    # ── Message 1: Missing Discord ────────────────────────────────────────────
    lines = [
        top_(),
        ctr_("~ NOT IN DISCORD ~"),
        ctr_(f"{len(missing)} of {len(roster_data)} members"),
        mid_(),
        row_(f"{'Name':<18} {'Rank':<12} {'Joined':>14}"),
        mid_(),
    ]
    if not missing:
        lines.append(ctr_("Everyone's in the Discord!! Great work, guild!! 🎉"))
    else:
        for m in missing:
            name = m["name"][:17]
            rank = m["rank"][:11] if m["rank"] else "—"
            lines.append(row_(f"(!) {name:<15} {rank:<12} {m['join_str']:>14}"))
    lines.append(bot_())
    
    msg1 = "```\n" + "\n".join(lines) + "\n```"

    # ── Message 2: Full roster ────────────────────────────────────────────────
    lines2 = [
        top_(),
        ctr_("~ FULL GUILD ROSTER ~"),
        ctr_(f"{len(roster_data)} members — ✅ in Discord  ❌ not in Discord"),
        mid_(),
        row_(f"{'Name':<18} {'Discord':>8}  {'Rank':<10} {'Joined':>12}"),
        mid_(),
    ]
    for m in present + missing:  # in Discord first, then missing
        name     = m["name"][:17]
        rank     = m["rank"][:9] if m["rank"] else "—"
        status   = "✅" if m["in_discord"] else "❌"
        lines2.append(row_(f"{name:<18} {status:>8}  {rank:<10} {m['join_str']:>12}"))
    lines2.append(bot_())

    msg2 = "```\n" + "\n".join(lines2) + "\n```"

    # Discord has 2000 char limit — chunk if needed
    await ctx.send(msg1)
    if len(msg2) <= 1990:
        await ctx.send(msg2)
    else:
        # Split into chunks of ~30 members each
        chunk_lines = lines2[:6]  # header
        for line in lines2[6:-1]:
            chunk_lines.append(line)
            if len("```\n" + "\n".join(chunk_lines) + "\n```") > 1800:
                await ctx.send("```\n" + "\n".join(chunk_lines) + "\n```")
                chunk_lines = lines2[:6]  # restart with header
        chunk_lines.append(lines2[-1])  # footer
        await ctx.send("```\n" + "\n".join(chunk_lines) + "\n```")

COMMAND_CATEGORIES = [
    ("👤  PLAYER LOOKUP", [
        ("!player <name>",          "Full profile scroll"),
        ("!search <name>",          "Recruitment card"),
        ("!characters <name>",      "Characters & gear"),
        ("!shinies <name>",         "Shiny collection"),
        ("!gstats <name>",          "Stat deltas & history"),
    ]),
    ("🏰  GUILD ROSTER", [
        ("!groster",                "Full guild roster"),
        ("!online",                 "Who's online right now"),
        ("!afk",                    "Offline 30+ days"),
        ("!gdiscord",               "Roster vs Discord members"),
        ("!gparty",                 "Members in parties"),
        ("!parties",                "Top 5 public parties"),
    ]),
    ("📊  FAME & LEADERBOARDS", [
        ("!gseason [n]",            "Season fame board"),
        ("!gtop [n]",               "Top N by seasonal fame"),
        ("!gdaily",                 "Fame gained today"),
        ("!gweekly",                "Fame gained this week"),
        ("!gshinies [item]",        "Guild shiny leaderboard"),
        ("!seasonrace",             "Race since season start"),
    ]),
    ("⚔️   BUILD & ITEMS", [
        ("!build <class>",          "Show stat options"),
        ("!build <class> <stat>",   "Top DPS builds"),
        ("!item <name>",            "Item stats from wiki"),
    ]),
    ("🌍  REALM EVENTS", [
        ("!find <event>",           "Find active events"),
        ("!find o3",                "Realms close to O3"),
    ]),
    ("🎲  TRIVIA", [
        ("!trivia start",           "5-question mixed round"),
        ("!trivia start <d> <n>",   "Custom difficulty/count"),
        ("!trivia quick [diff]",    "One random question"),
        ("!trivia scores",          "All-time leaderboard"),
        ("!trivia stats <name>",    "Player trivia stats"),
        ("!trivia add ...",         "Submit a question"),
        ("!trivia list",            "Browse question bank"),
        ("!trivia stop",            "Stop active round"),
    ]),
    ("💀  DEATHS", [
        ("!drecent",                "Last 5 death cards"),
        ("!dtop",                   "Top deaths this week by fame"),
        ("!testdeath",              "Test death card"),
    ]),
    ("🔧  ADMIN & UTILS", [
        ("!snapshot [--shinies]",   "Save baseline (for events/seasonrace)"),
        ("!newseason",              "Mark season start"),
        ("!refresh",                "Clear data cache"),
        ("!leaderboards",           "Pinnable guide embed"),
        ("!gannounce",              "Post daily report"),
    ]),
]


@bot.command(name="commands")
async def commands_list(ctx):
    W   = 48
    CW  = 22
    DW  = W - CW - 4

    def top():    return f"  ╔{'═' * W}╗"
    def bottom(): return f"  ╚{'═' * W}╝"
    def mid():    return f"  ╠{'═' * W}╣"
    def div():    return f"  ╟{'─' * W}╢"
    def row(t):   return f"  ║ {t:<{W-2}} ║"
    def ctr(t):   return f"  ║{t:^{W}}║"

    def build_page(cats, header):
        lines = [top(), ctr(header), mid()]
        for i, (cat_name, cmds) in enumerate(cats):
            if i > 0:
                lines.append(div())
            lines.append(row(f"{cat_name}"))
            lines.append(div())
            for cmd, desc in cmds:
                lines.append(row(f"{cmd:<{CW}}  {desc[:DW]:<{DW}}"))
        lines.append(bottom())
        return "```\n" + "\n".join(lines) + "\n```"

    intro = "📋 **Guill's Command Manual** *(I made this myself btw, just saying)*\nUse `!help <command>` for detailed info on any command!"
    page1 = build_page(COMMAND_CATEGORIES[:4], "~ GUILL'S COMMANDS  (1/2) ~")
    page2 = build_page(COMMAND_CATEGORIES[4:], "~ GUILL'S COMMANDS  (2/2) ~")

    await ctx.send(intro)
    await ctx.send(page1)
    await ctx.send(page2)


@bot.command(name="help")
async def help_cmd(ctx, *, command_name: str = ""):
    if command_name:
        command_name = command_name.lower().strip()
        help_details = {
            "player": (
                "!player <name>",
                "Full scroll-style profile for any RealmEye player.\nIncludes total fame, seasonal fame, account fame, skins, shinies, and exaltations.",
                "!player Cupdog"
            ),
            "search": (
                "!search <name>",
                "Recruitment card — great for evaluating applicants.\nIncludes online status, fame, exaltations, skins, shinies, characters, and last seen.",
                "!search Cupdog"
            ),
            "characters": (
                "!characters <name>",
                "Lists all characters with class sprites and equipment images.\nEach shows: class, seasonal status, level, fame, and stat progress.",
                "!characters Cupdog"
            ),
            "shinies": (
                "!shinies <name>",
                "Full shiny item collection across all seasons.\nIncludes rank, progress, and a visual grid of obtained shinies.",
                "!shinies Cupdog"
            ),
            "gstats": (
                "!gstats <name>",
                "Live player stats from RealmScope.\nIncludes total fame, seasonal fame with today/week deltas, stars, exaltations, skins, and shinies.\nNo snapshot required — fully live data.",
                "!gstats Cupdog"
            ),
            "build": (
                "!build <class> [stat]",
                "Top DPS/HPS builds from the RealmShark leaderboard.\nRun `!build <class>` first to see available stat options.\nShows top player build, average build, swaps, and enchantments.",
                "!build wizard attack\n!build knight defense\n!build archer"
            ),
            "item": (
                "!item <item name>",
                "Item stats from the RealmEye wiki.\nIncludes drop sources, blueprints, enchantments, and item images.\nUse the full item name — spaces or hyphens both work.",
                "!item void blade\n!item helm of the juggernaut\n!item scepter of devastation"
            ),
            "find": (
                "!find <event / dungeon / item>",
                "Scans active realms for a specific event, dungeon portal, or drop.\nUse `!find o3` to see realms closest to spawning Oryx 3.\nSearches by event name, dungeon name, or white bag item name.",
                "!find cube\n!find shatters\n!find juggernaut\n!find o3\n!find avatar"
            ),
            "trivia": (
                "!trivia <subcommand>",
                "`!trivia start [difficulty] [count]` — Start a round (default: 5 mixed)\n"
                "`!trivia quick [difficulty]` — One quick question\n"
                "`!trivia stop` — Stop the current round\n"
                "`!trivia scores` — All-time leaderboard\n"
                "`!trivia stats <name>` — One player's stats\n"
                "`!trivia list` — Browse the question bank\n"
                "`!trivia add diff | category | question | answer | [hint]` — Submit a question\n\n"
                "**Difficulties:** easy · medium · hard · expert",
                "!trivia start hard 10\n!trivia quick expert\n!trivia scores"
            ),
            "gshinies": (
                "!gshinies [item_name]",
                "No item name: seasonal shiny leaderboard for the whole guild.\nWith item name: searches all members for that specific shiny.",
                "!gshinies\n!gshinies void blade"
            ),
            "gtop": (
                "!gtop [number]",
                "Top N guild members by seasonal fame.\nDefault is 10, maximum is 25.",
                "!gtop\n!gtop 5\n!gtop 25"
            ),
            "snapshot": (
                "!snapshot [--shinies]",
                "Saves a snapshot of the current guild state.\nNeeded for `!seasonrace` and guild events (`!eventadd`) only.\n`!gseason`, `!gtop`, `!gdaily`, `!gweekly`, `!gstats` all fetch live data — no snapshot needed.\nAdd `--shinies` for a full shiny count scan (takes 2-3 min).",
                "!snapshot\n!snapshot --shinies"
            ),
            "gseason": (
                "!gseason [top_n]",
                "Seasonal fame leaderboard — live from the guild roster.\nDefault shows top 15. Cached for 30 minutes.",
                "!gseason\n!gseason 10\n!gseason 25"
            ),
            "gdaily": (
                "!gdaily",
                "Today's seasonal fame gains for all members.\nPulls live data from RealmScope (cached 30 min).",
                "!gdaily"
            ),
            "gweekly": (
                "!gweekly",
                "Last 7 days of seasonal fame gains for all members.",
                "!gweekly"
            ),
            "drecent": (
                "!drecent",
                "Shows the last 5 guild deaths as death cards.\n"
                "Each card shows the player's class sprite, items (with enchantment rarity colors and shiny sprites), "
                "killer, stats, fame, and time of death in US Eastern time.\n"
                "Item images are fetched from the RealmEye wiki and cached — first run may be slightly slower.",
                "!drecent"
            ),
            "dtop": (
                "!dtop",
                "Shows this week's top guild deaths ranked by base fame.\n"
                "Includes a summary of total base fame and total fame contributed by all deaths this week.\n"
                "Also posts death cards for the top 3 deaths.\n"
                "Only counts deaths from the last 7 days.",
                "!dtop"
            ),
            "testdeath": (
                "!testdeath",
                "Fetches the most recent guild death and posts it as a death card.\n"
                "Useful for testing the death announcer after changes.",
                "!testdeath"
            ),
        }

        if command_name in help_details:
            usage, desc, examples = help_details[command_name]
            embed = discord.Embed(
                title=f"📖  `!{command_name}`",
                description=f"**Usage:** `{usage}`\n\n{desc}",
                color=0x8e44ad
            )
            embed.add_field(
                name="Example Usage",
                value=f"```\n{examples}\n```",
                inline=False
            )
            embed.set_footer(text="Guill the Intern™  |  !commands for the full list")
            await ctx.send(embed=embed)
        else:
            await ctx.send(
                f"Hmm... I don't have specific help written up for `{command_name}` yet 😅\n"
                f"Try `!commands` for the full list, or just give the command a shot!"
            )
        return

    # General help embed
    embed = discord.Embed(
        title="📋  The Atheneum — Command Guide",
        description=(
            "*Hi!! I'm Guill, your friendly (and honestly quite underappreciated) guild intern.*\n"
            "*Use `!commands` for the full list, or `!help <command>` for details on any specific one!*"
        ),
        color=0x8e44ad
    )
    embed.add_field(
        name="👤 Player Lookup",
        value=(
            "`!player <name>` — Full profile scroll\n"
            "`!search <name>` — Recruitment card\n"
            "`!characters <name>` — Characters & gear\n"
            "`!shinies <name>` — Shiny collection\n"
            "`!gstats <name>` — Stat deltas"
        ),
        inline=True
    )
    embed.add_field(
        name="🏰 Guild Roster",
        value=(
            "`!groster` — Full guild roster\n"
            "`!online` — Who's online\n"
            "`!afk` — Offline 30+ days\n"
            "`!gdiscord` — Roster vs Discord\n"
            "`!gparty` / `!parties` — Party info"
        ),
        inline=True
    )
    embed.add_field(
        name="📊 Fame & Leaderboards",
        value=(
            "`!gseason [n]` — Season fame board\n"
            "`!gtop [n]` — Top N members\n"
            "`!gdaily` — Today's gains\n"
            "`!gweekly` — This week's gains\n"
            "`!gshinies [item]` — Shiny board"
        ),
        inline=True
    )
    embed.add_field(
        name="⚔️ Build & Items",
        value=(
            "`!build <class> [stat]` — DPS builds\n"
            "`!item <name>` — Item wiki lookup\n"
            "`!find <event>` — Active realm events\n"
            "`!find o3` — O3 realm scores"
        ),
        inline=True
    )
    embed.add_field(
        name="💀 Deaths",
        value=(
            "`!drecent` — Last 5 death cards\n"
            "`!dtop` — Top deaths this week\n"
            "`!testdeath` — Test death card"
        ),
        inline=True
    )
    embed.add_field(
        name="🎲 Trivia",
        value=(
            "`!trivia start [diff] [n]` — Start a round\n"
            "`!trivia quick` — Single question\n"
            "`!trivia scores` — Leaderboard\n"
            "`!trivia add ...` — Submit a question"
        ),
        inline=True
    )
    embed.set_footer(text="The Atheneum  ·  Guill the Intern™  ·  !commands for the full list  ·  !help <command> for details")
    await ctx.send(embed=embed)

@bot.command(name="rstest")
async def rstest(ctx):
    """Diagnostic: test realmscope.gg connectivity via the persistent browser."""
    display = os.environ.get("DISPLAY", "not set")
    xvfb_hint = " ⚠️ Xvfb not running — install with `sudo apt-get install -y xvfb` then restart" if display == "not set" else ""
    await ctx.send(f"🔍 Testing RealmScope — DISPLAY={display}{xvfb_hint} — stand by...")

    def test_browser():
        def read_cd_log():
            try:
                with open("/tmp/chromedriver.log") as f:
                    lines = f.readlines()
                return "".join(lines[-4:])[:300].replace("\n", " | ")
            except Exception:
                return "no log"
        try:
            soup = rs._browser_get_soup("https://realmscope.gg/player/arnauvila")
            if soup:
                title = soup.title.string[:60] if soup.title else "no title"
                has_stats = bool(soup.find("ul", id="player-stats-list"))
                return f"✅ browser: page loaded — `{title}` — stats element: {has_stats}"
            else:
                return f"❌ browser: _browser_get_soup returned None\nCD log: `{read_cd_log()}`"
        except Exception as e:
            return f"❌ browser: `{type(e).__name__}: {str(e)[:100]}`\nCD log: `{read_cd_log()}`"

    browser_result = await asyncio.get_event_loop().run_in_executor(None, test_browser)
    await ctx.send(browser_result)


discord_key = os.getenv("DISCORD_KEY")
bot.run(discord_key)
