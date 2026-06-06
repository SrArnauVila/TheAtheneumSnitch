import discord
import asyncio
import image_downloader as imd
import guild_graveyard as gg
import json
import os
from datetime import datetime
from dotenv import load_dotenv
from pathlib import Path
import Realm_image_parser as RIP
from discord.ext import commands
from discord.ext import tasks
import player_characters
import realmscope_scraper as rs
from datetime import datetime, timezone
import time as time_module
from player_tracker import get_online_status
import build_scraper as bs
import build_image  as bi
import io
import re
import event_tracker as et
import event_image  as ei
import pytz
import trivia_system as ts
import random


load_dotenv(Path('keys.env'))
# ── Cache system ──────────────────────────────────────────────────────────────
_roster_cache = {"data": None, "timestamp": 0}
_fame_cache   = {"data": None, "timestamp": 0}
CACHE_TTL     = 1800  # 30 minutes

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
    async with selenium_lock:
        data = await asyncio.get_event_loop().run_in_executor(
            None, rs.get_guild_roster, "TheAtheneum"
        )
    if data:
        _roster_cache["data"]      = data
        _roster_cache["timestamp"] = time_module.time()
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
channel_id = int(os.getenv("CHANNEL_ID"))
channel = None
guild = os.getenv("GUILD_NAME")

#imd.Download_Images()
#with open('last death.json', 'w') as f:
 #   last_death = gg.guild_graveyard(guild, 0)
  #  i = 1
   # while last_death['player-name'] == "Private":
    #    print("private death")
     #   last_death = gg.guild_graveyard(guild, i)
      #  i += 1
    #json.dump(last_death, f)
#f.close()


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
                await channel.send(f"(+) **{name}** just came Online!")

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
            deaths = dc.fetch_latest_deaths(guild)
            if not deaths:
                await asyncio.sleep(60)
                continue

            latest = deaths[0]
            current_key = f"{latest['player-name']}_{latest['time']}"

            if current_key != last_death_name_time:
                last_death_name_time = current_key

                # Save to file
                with open("last death.json", "w") as f:
                    json.dump(latest, f)

                # Build the death card image
                try:
                    imd.Download_Images()
                    img_path = dc.build_death_card(latest)
                except Exception as e:
                    print(f"Death card build error: {e}")
                    img_path = None

                # Find #deaths channel
                deaths_channel = discord.utils.get(
                    bot.get_all_channels(), name="deaths"
                )
                if not deaths_channel:
                    print("Could not find #deaths channel")
                    await asyncio.sleep(60)
                    continue

                msg = (
                    f"**☠ {latest['player-name']}** just died!\n"
                    f"**Killed by:** {latest['killed_by']}\n"
                    f"**Stats:** {latest['stats']}  "
                    f"**Base Fame:** {latest['base_fame']}  "
                    f"**Total Fame:** {latest['total_fame']}\n"
                    f"**Time:** {latest['time']}"
                )

                if img_path and os.path.exists(img_path):
                    await deaths_channel.send(msg, file=discord.File(img_path))
                else:
                    await deaths_channel.send(msg)

                print(f"Death announced: {latest['player-name']} killed by {latest['killed_by']}")

        except Exception as e:
            print(f"Guild graveyard error: {e}")

        await asyncio.sleep(60)


@bot.event
async def on_ready():
    global selenium_lock
    selenium_lock = asyncio.Lock()
    print(f'We have logged in as {bot.user}')
    if not intents.message_content:
        print('MESSAGE CONTENT intent is disabled; prefix commands may not be available.')
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
        await ctx.send(f"Could not find characters for **{player_name}**. The profile may be private or the name is incorrect.")
        return

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

import realmscope_scraper as rs
import shiny_image_builder as sib

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
        await ctx.send("❌ Could not fetch party data from RealmScope.")
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
    await ctx.send(f"🔍 Fetching shiny data for **{player_name}**...")
    data = rs.get_shiny_data(player_name)
    if not data:
        await ctx.send(f"❌ Could not find shiny data for **{player_name}** on RealmScope.")
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
    await ctx.send("Scanning parties for guild members... (this may take 30s)")
    
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
    await ctx.send("Fetching guild roster...")

    async with selenium_lock:
        members = await asyncio.get_event_loop().run_in_executor(
            None, rs.get_guild_roster, "TheAtheneum"
        )

    if not members:
        await ctx.send("❌ Could not fetch guild roster.")
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
        await ctx.send(f"❌ Could not find **{player_name}** on RealmScope.")
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
    await ctx.send("Checking for AFK guild members...")

    async with selenium_lock:
        afk_members = await asyncio.get_event_loop().run_in_executor(
            None, rs.get_afk_members, "TheAtheneum", 30
        )

    if afk_members is None:
        await ctx.send("❌ Could not fetch guild data.")
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
        lines.append(ctr("No members AFK for 30+ days!"))
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
    await ctx.send(f"Looking up **{item_name}**...")

    info = rs.get_wiki_item(slug)
    if not info:
        await ctx.send(
            f"❌ Could not find **{item_name}** on the RealmEye wiki.\n"
            f"Try the exact item name, e.g. `!item legion-elite-staff`"
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
            await ctx.send("Shiny version:", file=files[1])
    else:
        await ctx.send(msg)

@bot.command(name="online")
async def online(ctx):
    await ctx.send("Checking who is online...")

    async with selenium_lock:
        results = await asyncio.get_event_loop().run_in_executor(
            None, rs.get_guild_online_status, "TheAtheneum"
        )

    if not results:
        await ctx.send("❌ Could not fetch guild status.")
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
        lines.append(ctr("No members currently online"))
    else:
        for m in online_members:
            lines.append(row(f"(+)  {m['name']}"))

    lines.append(bot())


    await ctx.send("```\n" + "\n".join(lines) + "\n```")

import guild_stats as gs

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
    msg = "Taking guild snapshot"
    if fetch_shinies:
        msg += " (including shinies — this will take 2-3 minutes)..."
    await ctx.send(msg)

    async with selenium_lock:
        members = await asyncio.get_event_loop().run_in_executor(
            None, rs.get_guild_roster, "TheAtheneum"
        )
    if not members:
        await ctx.send("❌ Could not fetch guild data.")
        return

    snap = gs.take_snapshot(members, fetch_shinies=fetch_shinies)
    gs.store_snapshot(snap)
    await ctx.send(
        f"Snapshot saved — **{len(members)}** members at `{snap['date']}`."
        + (" Shinies included." if fetch_shinies else "")
    )

async def _fetch_guild_fame_board(period: str) -> tuple:
    """Returns (board, failed_names) where board is sorted list of (name, value)."""
    snap = gs.get_latest_snapshot()
    if not snap:
        return [], []

    member_names = [v["name"] for v in snap["members"].values()]

    results = await asyncio.get_event_loop().run_in_executor(
        None, rs.get_guild_seasonal_fame, member_names
    )

    board  = []
    failed = []
    for r in results:
        if r.get("failed"):
            failed.append(r["name"])
        else:
            val = r[period]
            if val > 0:
                board.append((r["name"], val))

    board.sort(key=lambda x: x[1], reverse=True)
    return board, failed


# ── !gseason ──────────────────────────────────────────────────────────────────
@bot.command(name="gseason")
async def gseason(ctx, top: int = 15):
    """Seasonal fame leaderboard — pulls live from guild roster page."""
    await ctx.send("📊 Fetching seasonal fame leaderboard...")

    members = await _get_roster()

    if not members:
        await ctx.send("❌ Could not fetch guild roster.")
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
    await ctx.send("📊 Fetching daily fame gains...")

    snap = gs.get_latest_snapshot()
    member_names = list(_guild_members_cache) if _guild_members_cache else []

    if not member_names and snap:
        member_names = [v["name"] for v in snap["members"].values()]

    if not member_names:
        await ctx.send("❌ No member data available. Try `!snapshot` first.")
        return

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
        lines.append(ctr_("No fame gained in the last 24h"))
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
    await ctx.send("📊 Fetching weekly fame gains...")

    member_names = list(_guild_members_cache) if _guild_members_cache else []
    snap = gs.get_latest_snapshot()
    if not member_names and snap:
        member_names = [v["name"] for v in snap["members"].values()]

    if not member_names:
        await ctx.send("❌ No member data available. Try `!snapshot` first.")
        return

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
        await ctx.send(f"✨ Searching for **{item_name}** across guild members...")

        member_names = list(_guild_members_cache) if _guild_members_cache else []
        if not member_names:
            snap = gs.get_latest_snapshot()
            if snap:
                member_names = [v["name"] for v in snap["members"].values()]

        if not member_names:
            await ctx.send("❌ No member data available.")
            return

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
            lines.append(ctr_(f"No members have this shiny yet"))
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
        await ctx.send("✨ Fetching seasonal shiny leaderboard...")

        async with selenium_lock:
            members = await asyncio.get_event_loop().run_in_executor(
                None, rs.get_guild_roster, "TheAtheneum"
            )

        if not members:
            await ctx.send("❌ Could not fetch guild roster.")
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
            lines.append(ctr_("No seasonal shinies yet!"))
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
    await ctx.send(f"📊 Fetching top {n}...")

    members = await _get_roster()

    if not members:
        await ctx.send("❌ Could not fetch guild roster.")
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
    await ctx.send("🔄 Cache cleared — next command will fetch fresh data.")



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
    now_str = dt_module.datetime.now(PST).strftime("%B %d, %Y")

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

    # Save snapshot for daily comparison
    gl.save_daily_snapshot([
        {"name": m["name"], "seasonal_fame": m["seasonal_fame"],
         "seasonal_shinies": 0, "shiny_items": {}}
        for m in members
    ])
    print(f"Daily announcement posted for {now_str}")

@bot.command(name="gstats")
async def gstats(ctx, player_name: str):
    snap = gs.get_latest_snapshot()
    if not snap:
        await ctx.send("No snapshot data yet. Run `!snapshot` first.")
        return

    key     = player_name.lower()
    current = snap["members"].get(key)
    if not current:
        await ctx.send(f"**{player_name}** not found in latest snapshot.")
        return

    # Fetch live fame history from realmscope
    await ctx.send(f"Fetching stats for **{player_name}**...")
    fame_history = await asyncio.get_event_loop().run_in_executor(
        None, rs.get_player_seasonal_fame_history, player_name, 2
    )

    daily_seasonal   = fame_history["daily"]         if fame_history else 0
    weekly_seasonal  = fame_history["weekly"]        if fame_history else 0
    total_seasonal   = fame_history["current_total"] if fame_history else current.get("seasonal_fame", 0)

    # For regular fame, use snapshot deltas
    snap_24h = gs.get_snapshot_before(24)
    snap_7d  = gs.get_snapshot_before(168)

    def snap_delta(old_snap, stat):
        if not old_snap:
            return "N/A"
        old = old_snap["members"].get(key, {}).get(stat, 0)
        d   = current.get(stat, 0) - old
        return f"+{d:,}" if d >= 0 else f"{d:,}"

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

    scroll = []
    scroll.append(f"   {'_' * W}")
    scroll.append(f" / \\{' ' * W}\\.")
    scroll.append(f"|   |{' ' * W}|.")
    scroll.append(line("~ GUILD STATS ~"))
    scroll.append(f" \\_ |{current['name']:^{W}}|.")
    scroll.append(line(current["rank"]))
    scroll.append(line())
    scroll.append(div())
    scroll.append(line())
    scroll += sline("Fame",             f"{current.get('fame', 0):,}")
    scroll += sline("  24h",            snap_delta(snap_24h, 'fame'))
    scroll += sline("  7d",             snap_delta(snap_7d, 'fame'))
    scroll.append(line())
    scroll += sline("Seasonal Fame",    f"{total_seasonal:,}")
    scroll += sline("  Today",          f"+{daily_seasonal:,}")
    scroll += sline("  This Week",      f"+{weekly_seasonal:,}")
    scroll.append(line())
    scroll.append(div())
    scroll.append(line())
    scroll += sline("Stars",            current.get('stars', 0))
    scroll += sline("Shinies",          current.get('shinies', 0))
    scroll.append(line())
    scroll.append(f"    |   {'_' * W}|___")
    scroll.append(f"    |  /{' ' * W}/.")
    scroll.append(f"    \\_/{'_' * W}/.")

    await ctx.send("```\n" + "\n".join(scroll) + "\n```")

@bot.command(name="newseason")
async def newseason(ctx):
    """Marks the start of a new season for tracking."""
    gs.set_season_start()
    await ctx.send("New season started! Seasonal delta tracking reset from this point.")


@bot.command(name="seasonrace")
async def seasonrace(ctx):
    """Shows seasonal fame gained since the season start was marked."""
    snap_new    = gs.get_latest_snapshot()
    snap_season = gs.get_season_start_snapshot()
    if not snap_new:
        await ctx.send("No snapshot data yet.")
        return
    if not snap_season:
        await ctx.send("No season start set. Use `!newseason` to mark the start.")
        return
    entries = gs.delta_leaderboard(snap_season, snap_new, "seasonal_fame")
    await ctx.send(_leaderboard_msg(
        "~ Season Fame Race ~", entries, "Seasonal Fame", show_delta=True
    ))
# ── Daily event leaderboard broadcaster ─────────────────────────────
async def run_event_leaderboards():
    """Posts daily leaderboard updates for all active events."""
    while True:
        now = datetime.now(timezone.utc)
        # Fire at noon UTC daily
        seconds_until_noon = (
            ((12 - now.hour) % 24) * 3600 +
            (0  - now.minute) * 60 +
            (0  - now.second)
        )
        if seconds_until_noon <= 0:
            seconds_until_noon += 86400
        await asyncio.sleep(seconds_until_noon)

        try:
            active = ge.get_active_events()
            if not active:
                await asyncio.sleep(60)
                continue

            channel = bot.get_channel(int(channel_id))
            for event in active:
                board = ge.get_event_leaderboard(event)
                if not board:
                    continue

                W = 48
                def top():  return f"  ╔{'═' * W}╗"
                def bot_():  return f"  ╚{'═' * W}╝"
                def mid():  return f"  ╠{'═' * W}╣"
                def row(t): return f"  ║ {t:<{W-2}} ║"
                def ctr(t): return f"  ║{t:^{W}}║"

                medals = ["(1)", "(2)", "(3)"]
                lines  = []
                lines.append(top())
                lines.append(ctr(f"~ {event['name']} ~"))
                lines.append(ctr(f"Tracking: {event['stat_label']}  |  Ends: {event['end_date']}"))
                lines.append(mid())
                lines.append(row(f"{'Player':<18} {'Gained':>10}   {'Total':>12}"))
                lines.append(mid())

                for i, (name, base, current, delta) in enumerate(board[:10]):
                    medal = medals[i] if i < 3 else f"({i+1})"
                    lines.append(row(
                        f"{medal} {name[:15]:<15} {f'+{delta:,}':>10}   {current:>12,}"
                    ))

                lines.append(bot_())
                await channel.send("```\n" + "\n".join(lines) + "\n```")

        except Exception as e:
            print(f"Event leaderboard error: {e}")

        await asyncio.sleep(60)



@bot.command(name="testdeath")
async def testdeath(ctx):
    """Fetch the latest death and post it as a card to test the death announcer."""
    import death_card as dc
    await ctx.send("🔍 Fetching latest death...")
    try:
        deaths = dc.fetch_latest_deaths(guild)
        if not deaths:
            await ctx.send("❌ No deaths found.")
            return
        latest = deaths[0]
        await ctx.send(f"Found: **{latest['player-name']}** (class_id: {latest.get('class_id', '?')}) killed by **{latest['killed_by']}**")
        img_path = dc.build_death_card(latest)
        await ctx.send(file=discord.File(img_path))
    except Exception as e:
        await ctx.send(f"❌ Error: {e}")
        raise


# ── Event commands ───────────────────────────────────────────────────

@bot.command(name="trackable")
async def trackable(ctx):
    """Shows all stats that can be automatically tracked for events."""
    W = 44
    def top():  return f"  ╔{'═' * W}╗"
    def bot_():  return f"  ╚{'═' * W}╝"
    def mid():  return f"  ╠{'═' * W}╣"
    def row(t): return f"  ║ {t:<{W-2}} ║"
    def ctr(t): return f"  ║{t:^{W}}║"

    lines = []
    lines.append(top())
    lines.append(ctr("~ Auto-Trackable Event Stats ~"))
    lines.append(mid())
    lines.append(row(f"{'Stat Key':<18}  {'Description'}"))
    lines.append(mid())
    for key, label in ge.VALID_STATS.items():
        lines.append(row(f"{key:<18}  {label}"))
    lines.append(mid())
    lines.append(row("Usage: !eventadd name|desc|end|prize|stat_key"))
    lines.append(bot_())
    await ctx.send("```\n" + "\n".join(lines) + "\n```")


@bot.command(name="eventadd")
async def eventadd(ctx, *, args: str):
    """
    Create an auto-tracked event.
    Usage: !eventadd name | description | end_date | prize | stat_key
    Example: !eventadd Shatter Madness | Most fame gained wins | 2026-06-01 | Custom role | fame
    Run !trackable to see valid stat keys.
    """
    parts = [p.strip() for p in args.split("|")]
    if len(parts) < 5:
        await ctx.send(
            "Usage: `!eventadd name | description | end_date | prize | stat_key`\n"
            "Run `!trackable` to see valid stat keys."
        )
        return

    stat = parts[4].lower().strip()
    if stat not in ge.VALID_STATS:
        valid = ", ".join(f"`{k}`" for k in ge.VALID_STATS)
        await ctx.send(f"Invalid stat. Valid options: {valid}")
        return

    snap = gs.get_latest_snapshot()
    if not snap:
        await ctx.send(
            "No snapshot exists yet — taking one now before creating the event..."
        )
        async with selenium_lock:
            members = await asyncio.get_event_loop().run_in_executor(
                None, rs.get_guild_roster, "TheAtheneum"
            )
        if members:
            snap = gs.take_snapshot(members)
            gs.store_snapshot(snap)

    event = ge.add_event(parts[0], parts[1], parts[2], parts[3], stat)
    if not event:
        await ctx.send("Failed to create event.")
        return

    member_count = len(event.get("baseline", {}))
    await ctx.send(
        f"Event **{event['name']}** created! ID: `#{event['id']}`\n"
        f"Tracking: **{event['stat_label']}** for **{member_count}** members.\n"
        f"Leaderboard updates daily at noon UTC. Use `!event {event['id']}` to check standings."
    )


@bot.command(name="events")
async def events(ctx):
    """Shows all active events."""
    active = ge.get_active_events()
    W = 46
    def top():  return f"  ╔{'═' * W}╗"
    def bot_():  return f"  ╚{'═' * W}╝"
    def mid():  return f"  ╠{'═' * W}╣"
    def div():  return f"  ╟{'─' * W}╢"
    def row(t): return f"  ║ {t:<{W-2}} ║"
    def ctr(t): return f"  ║{t:^{W}}║"

    lines = [top(), ctr("~ ACTIVE GUILD EVENTS ~"), mid()]

    if not active:
        lines.append(ctr("No active events right now"))
    else:
        for i, e in enumerate(active):
            if i > 0:
                lines.append(div())
            board = ge.get_event_leaderboard(e)
            leader = board[0][0] if board else "No data yet"
            lines.append(row(f"#{e['id']}  {e['name'][:30]}"))
            lines.append(row(f"     Tracks: {e['stat_label']:<20} Ends: {e['end_date']}"))
            lines.append(row(f"     Prize:  {e['prize'][:30]}"))
            lines.append(row(f"     Leader: {leader}"))

    lines.append(bot_())
    await ctx.send("```\n" + "\n".join(lines) + "\n```")


@bot.command(name="event")
async def event_detail(ctx, event_id: int):
    """Shows full leaderboard for an event. Usage: !event 1"""
    e = ge.get_event_by_id(event_id)
    if not e:
        await ctx.send(f"No event found with ID `#{event_id}`.")
        return

    board = ge.get_event_leaderboard(e)
    W     = 48
    def top():   return f"  ╔{'═' * W}╗"
    def bot_():   return f"  ╚{'═' * W}╝"
    def mid():   return f"  ╠{'═' * W}╣"
    def row(t):  return f"  ║ {t:<{W-2}} ║"
    def ctr(t):  return f"  ║{t:^{W}}║"

    status  = "(!) ACTIVE" if e["active"] else f"(x) ENDED — Winner: {e['winner']}"
    medals  = ["(1)", "(2)", "(3)"]

    lines   = []
    lines.append(top())
    lines.append(ctr(f"~ {e['name']} ~"))
    lines.append(ctr(status))
    lines.append(mid())
    lines.append(row(f"Tracks:  {e['stat_label']}"))
    lines.append(row(f"Ends:    {e['end_date']}"))
    lines.append(row(f"Prize:   {e['prize']}"))
    lines.append(row(f"Desc:    {e['description'][:40]}"))
    lines.append(mid())

    if not board:
        lines.append(ctr("No snapshot data available yet"))
    else:
        lines.append(row(f"{'Player':<18} {'Gained':>10}   {'Total':>12}"))
        lines.append(mid())
        for i, (name, base, current, delta) in enumerate(board[:15]):
            medal = medals[i] if i < 3 else f"({i+1})"
            lines.append(row(
                f"{medal} {name[:15]:<15} {f'+{delta:,}':>10}   {current:>12,}"
            ))

    lines.append(bot_())
    await ctx.send("```\n" + "\n".join(lines) + "\n```")


@bot.command(name="eventend")
async def eventend(ctx, event_id: int):
    """
    End an event. Winner is determined automatically from the leaderboard.
    Usage: !eventend 1
    """
    e = ge.get_event_by_id(event_id)
    if not e:
        await ctx.send(f"No event found with ID `#{event_id}`.")
        return

    success = ge.end_event(event_id)
    if success:
        e = ge.get_event_by_id(event_id)
        await ctx.send(
            f"Event **{e['name']}** has ended!\n"
            f"The winner is **{e['winner']}** with the highest **{e['stat_label']}** gain!\n"
            f"Congratulations on winning **{e['prize']}**!"
        )
    else:
        await ctx.send(f"Could not end event `#{event_id}`.")


@bot.command(name="eventall")
async def eventall(ctx):
    """Shows all events including ended ones."""
    all_events = ge.get_all_events()
    if not all_events:
        await ctx.send("No events have been created yet.")
        return

    W = 46
    def top():  return f"  ╔{'═' * W}╗"
    def bot_():  return f"  ╚{'═' * W}╝"
    def mid():  return f"  ╠{'═' * W}╣"
    def div():  return f"  ╟{'─' * W}╢"
    def row(t): return f"  ║ {t:<{W-2}} ║"
    def ctr(t): return f"  ║{t:^{W}}║"

    lines = [top(), ctr("~ ALL GUILD EVENTS ~"), mid()]
    for i, e in enumerate(all_events):
        if i > 0:
            lines.append(div())
        status = "(!) ACTIVE" if e["active"] else "(x) ENDED"
        lines.append(row(f"#{e['id']}  {e['name'][:28]}  {status}"))
        lines.append(row(f"     Tracks: {e['stat_label']}"))
        if e["winner"]:
            lines.append(row(f"     Winner: {e['winner']}"))
    lines.append(bot_())
    await ctx.send("```\n" + "\n".join(lines) + "\n```")


@bot.command(name="build")
async def build(ctx, class_name: str = "", stat: str = ""):
    import re
    class_name = class_name.lower().strip()
    stat       = stat.lower().strip()

    if not class_name:
        all_classes = sorted(
            list(bs.CLASS_BUILDS.keys()) + list(bs.SSNL_ONLY_CLASSES)
        )
        await ctx.send(
            "Usage: `!build <class> <stat>`\n"
            "Example: `!build archer attack`\n"
            f"Classes: `{'`, `'.join(all_classes)}`"
        )
        return

    if class_name in bs.SSNL_ONLY_CLASSES:
        await ctx.send(
            f"**{class_name.title()}** is not on the DPS leaderboard. "
            f"SSNL build support coming soon!"
        )
        return

    if class_name not in bs.CLASS_BUILDS:
        close = [c for c in bs.CLASS_BUILDS if class_name in c]
        hint  = f" Did you mean: `{'`, `'.join(close)}`?" if close else ""
        await ctx.send(f"Unknown class `{class_name}`.{hint}")
        return

    available = bs.CLASS_BUILDS[class_name]

    # Warrior and single-build classes skip stat selection
    if list(available.keys()) == ["general"]:
        stat = "general"

    if not stat or stat not in available:
        W = 50
        def top():  return f"  ╔{'═' * W}╗"
        def bot_(): return f"  ╚{'═' * W}╝"
        def mid():  return f"  ╠{'═' * W}╣"
        def row(t): return f"  ║ {t:<{W-2}} ║"
        def ctr(t): return f"  ║{t:^{W}}║"

        lines = [top(), ctr(f"~ {class_name.title()} Build Options ~"), mid()]
        for stat_name in available:
            key  = available[stat_name]["key"]
            line = f"!build {class_name} {stat_name:<12}  [{key}]"
            lines.append(row(line[:W-2]))
        lines.append(bot_())
        await ctx.send("```\n" + "\n".join(lines) + "\n```")
        return

    build_key_data = available[stat]
    is_support     = class_name in bs.SUPPORT_CLASSES
    display_stat   = "" if stat == "general" else f" {stat.title()}"

    await ctx.send(f"Fetching **{class_name.title()}{display_stat}** build data...")

    data = await asyncio.get_event_loop().run_in_executor(
        None, bs.fetch_build_data, build_key_data, 15
    )
    if not data or not data.get("rows"):
        await ctx.send("Could not fetch build data. Try again later.")
        return

    rows     = data["rows"]
    meta     = data.get("meta", {})
    analysis = bs.analyze_builds(rows)

    def make_images():
        top_row   = analysis["top"]
        top_items = {item["slot"]: item for item in top_row.get("equipment", [])}

        top_img = bi.build_tier_image(
            tier_label   = f"* TOP BUILD -- #{top_row['rank']} {top_row['playerName']}",
            items        = top_items,
            enchants     = analysis["top_enchants"],
            alt_enchants = analysis["alt_enchants"],
            dps          = top_row.get("dps", 0),
            total_dmg    = top_row.get("totalDamage", 0),
            swap_items   = None,
            is_support   = is_support,
        )

        avg_img = bi.build_tier_image(
            tier_label   = f"~ AVERAGE BUILD  (Top 15 Consensus)",
            items        = analysis["avg_items"],
            enchants     = analysis["top_enchants"],
            alt_enchants = analysis["alt_enchants"],
            dps          = analysis["stat_avgs"].get("dps", 0),
            total_dmg    = analysis["stat_avgs"].get("totalDamage", 0),
            swap_items   = analysis["swap_items"],
            is_support   = is_support,
        )
        return top_img, avg_img

    top_img, avg_img = await asyncio.get_event_loop().run_in_executor(
        None, make_images
    )

    def img_to_file(img, filename):
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return discord.File(buf, filename=filename)

    top_file = img_to_file(top_img, f"top_{class_name}_{stat}.png")
    avg_file = img_to_file(avg_img, f"avg_{class_name}_{stat}.png")

    # Clean info scroll
    season_str = data.get("meta", {}).get("season", "current").upper()
    W_   = 46
    def top_():  return f"  ╔{'═' * W_}╗"
    def bot__(): return f"  ╚{'═' * W_}╝"
    def mid_():  return f"  ╠{'═' * W_}╣"
    def row_(t): return f"  ║ {t:<{W_-2}} ║"
    def ctr_(t): return f"  ║{t:^{W_}}║"

    # Get clean build description — strip technical noise
    notes      = meta.get("notes", [])
    build_desc = notes[0] if notes else ""
    build_desc = re.sub(
        r'\.\s*(Weapon DPS.*|Exalt.*|Ability activations.*)',
        '', build_desc, flags=re.IGNORECASE
    ).strip()
    # Remove trailing period
    build_desc = build_desc.rstrip(".")

    lines = [
        top_(),
        ctr_(f"~ {class_name.title()}{display_stat} Build ~"),
        ctr_(f"Top 15  |  Season {season_str}"),
        mid_(),
    ]
    if build_desc:
        lines.append(row_(build_desc[:W_-2]))
    lines.append(bot__())

    await ctx.send("```\n" + "\n".join(lines) + "\n```")
    await ctx.send(file=top_file)
    await ctx.send(file=avg_file)


@bot.command(name="find")
async def find_event(ctx, *, query: str = ""):
    if not query:
        await ctx.send(
            "Usage: `!find <event/dungeon/item>`\n"
            "• `!find cube` — active Cube Gods\n"
            "• `!find shatters` — active events dropping The Shatters portal\n"
            "• `!find juggernaut` — active events dropping that item\n"
            "• `!find o3` — top 5 realms closest to O3"
        )
        return

    await ctx.send(f"Searching for **{query}**...")

    result = await asyncio.get_event_loop().run_in_executor(
        None, et.find_event, query
    )

    if result.get("type") == "error":
        await ctx.send(f"Error: {result['message']}")
        return

    is_o3        = result["type"] == "o3"
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

    # No results and no possible events
    if not results and not possible:
        await ctx.send(
            f"No active events found for **{query_name}**. "
            f"Try `!findevents` to browse all searchable events."
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
    await ctx.send(file=discord.File(buf, filename=fname))


@bot.command(name="leaderboards")
async def leaderboards(ctx):
    """Send a pinnable overview of all leaderboard and stat commands."""
    embed = discord.Embed(
        title="📊 The Atheneum — Commands Guide",
        color=0x2b2d42
    )

    embed.add_field(
        name="👤 Player Stats",
        value=(
            "`!player <name>` — Full player profile (chars, fame, exalts)\n"
            "`!characters <name>` — List all characters\n"
            "`!shinies <name>` — Shiny item collection\n"
            "`!search <name>` — Search for a player"
        ),
        inline=False
    )

    embed.add_field(
        name="🏆 Guild Leaderboards",
        value=(
            "`!gtop` — Top guild members by fame\n"
            "`!gdaily` — Today's fame gains\n"
            "`!gweekly` — This week's fame gains\n"
            "`!gseason` — Season leaderboard\n"
            "`!gstats` — Guild overall statistics"
        ),
        inline=False
    )

    embed.add_field(
        name="⚔️ Build Leaderboards",
        value=(
            "`!build <class>` — Top DPS builds for a class\n"
            "`!build <class> <type>` — Specific build type (attack / defense / speed / etc)\n"
            "Example: `!build wizard attack` · `!build knight defense`"
        ),
        inline=False
    )

    embed.add_field(
        name="🌍 Event Finder",
        value=(
            "`!find <event>` — Find active realm events (top 3 shown)\n"
            "`!find o3` — Top 5 realms closest to spawning O3\n"
            "Examples: `!find cube` · `!find avatar` · `!find monolith` · `!find rift`"
        ),
        inline=False
    )

    embed.add_field(
        name="📋 Guild Events & Parties",
        value=(
            "`!events` — Active guild events\n"
            "`!eventadd <name>` — Start a guild event\n"
            "`!eventend <name>` — End a guild event\n"
            "`!parties` — Active party listings\n"
            "`!gparty` — Start a guild party"
        ),
        inline=False
    )

    embed.add_field(
        name="🔍 Online & Roster",
        value=(
            "`!online` — Who's currently online\n"
            "`!groster` — Full guild roster\n"
            "`!afk` — AFK members"
        ),
        inline=False
    )

    embed.set_footer(text="The Atheneum · Use !commands for the full command list")

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
            f"🎲 **Auto Trivia!** {diff_emoji} — worth **{points}** pt{'s' if points != 1 else ''}\n"
            f"**{q['q']}**\n"
            f"⏳ Open until answered or 1 hour passes!"
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
                    f"⏰ Auto trivia expired! Nobody got it.\n"
                    f"The answer was **{q['a'][0]}**"
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
                    f"✅ **{winner}** got the auto trivia question!\n"
                    f"The answer was **{q['a'][0]}** (+{points} pt{'s' if points != 1 else ''})"
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
            await ctx.send("A trivia round is already running! Use `!trivia stop` to end it.")
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
            await ctx.send("No questions found.")
            return
        q = random.choice(questions)
        await ts.ask_question(bot, ctx.channel, q, 1, 1)

    # ── stop ──────────────────────────────────────────────────────────────────
    elif subcommand == "stop":
        if not _trivia_active:
            await ctx.send("No trivia round is currently running.")
            return
        _trivia_stop[0] = True
        if _trivia_task:
            _trivia_task.cancel()
        _trivia_active = False
        await ctx.send("⛔ Trivia round stopped.")

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
            f"✅ Question added! Total questions: **{len(all_q)}**\n"
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
    await ctx.send("🔍 Fetching guild roster and Discord status...")

    # Get current roster
    async with selenium_lock:
        members = await asyncio.get_event_loop().run_in_executor(
            None, rs.get_guild_roster, "TheAtheneum"
        )
    if not members:
        await ctx.send("❌ Could not fetch guild roster.")
        return

    # Get join dates from history page
    await ctx.send("📅 Fetching join dates...")
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
        lines.append(ctr_("✅ All members are in Discord!"))
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

COMMAND_LIST = [
    ("!commands",   "Shows all bot commands"),
    ("!player",     "Player stats scroll"),
    ("!search",     "Recruitment card for any player"),
    ("!characters", "Player's characters & equipment"),
    ("!shinies",    "Player's shiny collection"),
    ("!item",       "Item lookup on RealmEye wiki"),
    ("!parties",    "Top 5 most active parties"),
    ("!gparty",     "Guild members in parties"),
    ("!online",     "Guild members online now"),
    ("!groster",    "Full guild roster with ranks"),
    ("!afk",        "Members offline 30+ days"),
    ("!snapshot",   "Save a guild snapshot"),
    ("!gdaily",     "Seasonal fame gained today"),
    ("!gweekly",    "Seasonal fame this week"),
    ("!gseason",    "Season fame leaderboard"),
    ("!gtop",       "Leaderboard: !gtop fame/stars/etc"),
    ("!gstats",     "A player's stat progression"),
    ("!trackable",  "All auto-trackable event stats"),
    ("!events",     "Active guild events"),
    ("!event",      "Event leaderboard: !event 1"),
    ("!eventadd",   "Create auto-tracked event"),
    ("!eventend",   "End event, auto-pick winner"),
    ("!eventall",   "All events including ended"),
    ("!build",      "Class builds: !build archer attack"),
]

@bot.command(name="commands")
async def commands_list(ctx):
    W = 44
    CMD_W = 14
    DESC_W = W - CMD_W - 4

    def top():  return f"  ╔{'═' * W}╗"
    def bot():  return f"  ╚{'═' * W}╝"
    def mid():  return f"  ╠{'═' * W}╣"
    def row(t): return f"  ║ {t:<{W-2}} ║"
    def ctr(t): return f"  ║{t:^{W}}║"

    lines = []
    lines.append(top())
    lines.append(ctr("~ The Atheneum Bot Commands ~"))
    lines.append(mid())
    for cmd, desc in COMMAND_LIST:
        desc = desc[:DESC_W]  # hard truncate if somehow still too long
        lines.append(row(f"{cmd:<{CMD_W}}  {desc:<{DESC_W}}"))
    lines.append(bot())
    await ctx.send("```\n" + "\n".join(lines) + "\n```")

discord_key = os.getenv("DISCORD_KEY")
bot.run(discord_key)
