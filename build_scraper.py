import urllib.request
import json
import re
from collections import Counter
from typing import Optional
import time as time_module
REALMSHARK_API = "https://tracker.realmshark.cc/api/v1/dps-leaderboard"
REALMSCOPE_BASE = "https://realmscope.gg"
_season_cache = {"value": None, "fetched_at": 0}


# Classes with DPS leaderboard support and their exact API build keys
CLASS_BUILDS = {
    "archer": {
        "attack":  {"key": "atk-archer"},
        "defense": {"key": "def-archer"},
        "speed":   {"key": "speed-archer"},
    },
    "assassin": {
        "wisdom":  {"key": "wis-assassin"},
    },
    "bard": {
        "attack":  {"key": "atk-bard"},
    },
    "knight": {
        "defense":  {"key": "def-knight"},
        "speed":    {"key": "speed-knight"},
        "vitality": {"key": "vit-knight"},
    },
    "mystic": {
        "mana":    {"key": "mana-mystic", "seconds": 6, "abilityCount": 10},
    },
    "necromancer": {
        "attack":  {"key": "atk-necro",  "minionCount": 5},
        "wisdom":  {"key": "wis-necro",  "minionCount": 5},
        "mana":    {"key": "mana-necro", "minionCount": 5},
    },
    "ninja": {
        "attack":  {"key": "atk-ninja"},
        "speed":   {"key": "speed-ninja"},
        "wisdom":  {"key": "wis-ninja"},
    },
    "paladin": {
        "wisdom":  {"key": "wis-paladin"},
    },
    "priest": {
        "wisdom":  {"key": "wis-priest"},
        "vitality": {"key": "vit-priest"},
    },
    "rogue": {
        "vitality": {"key": "vit-rogue",  "lsUptime": "high"},
        "defense":  {"key": "def-rogue",  "lsUptime": "high"},
        "wisdom":   {"key": "wis-rogue",  "lsUptime": "high"},
    },
    "samurai": {
        "attack":   {"key": "atk-samurai"},
        "speed":    {"key": "speed-samurai"},
        "vitality": {"key": "vit-samurai"},
        "wisdom":   {"key": "wis-samurai"},
    },
    "warrior": {
        "general":  {"key": "warrior"},
    },
    "wizard": {
        "attack":   {"key": "atk-wizard"},
        "speed":    {"key": "speed-wizard"},
        "vitality": {"key": "vit-wizard"},
        "wisdom":   {"key": "wis-wizard"},
    },
}

# Classes NOT on DPS leaderboard — use SSNL stats leaderboard instead
SSNL_ONLY_CLASSES = {
    "druid", "huntress", "kensei", "sorcerer", "summoner", "trickster"
}

# Support classes display HPS instead of DPS
SUPPORT_CLASSES = {"priest", "paladin"}

# ── SSNL Stats Leaderboard ────────────────────────────────────────────────────
SSNL_API = "https://tracker.realmshark.cc/api/v1/leaderboard"

# Normalize user input → SSNL API stat key
SSNL_STAT_MAP = {
    "hp":         "HP",
    "life":       "HP",
    "mp":         "Mana",
    "mana":       "Mana",
    "atk":        "Attack",
    "attack":     "Attack",
    "def":        "Defense",
    "defense":    "Defense",
    "defence":    "Defense",
    "spd":        "Speed",
    "speed":      "Speed",
    "dex":        "Dexterity",
    "dexterity":  "Dexterity",
    "vit":        "Vitality",
    "vitality":   "Vitality",
    "wis":        "Wisdom",
    "wisdom":     "Wisdom",
}

# (input keyword, API/display label) — order shown in options
SSNL_STATS_DISPLAY = [
    ("hp",        "HP"),
    ("mp",        "Mana"),
    ("attack",    "Attack"),
    ("defense",   "Defense"),
    ("speed",     "Speed"),
    ("dexterity", "Dexterity"),
    ("vitality",  "Vitality"),
    ("wisdom",    "Wisdom"),
]

# DPS stat key → SSNL stat key (for deduplication in options display)
DPS_TO_SSNL = {
    "attack":   "Attack",
    "defense":  "Defense",
    "speed":    "Speed",
    "vitality": "Vitality",
    "wisdom":   "Wisdom",
    "mana":     "Mana",
}

# All valid classes for SSNL (title-case = API class name)
SSNL_CLASS_MAP = {
    "archer":      "Archer",
    "assassin":    "Assassin",
    "bard":        "Bard",
    "druid":       "Druid",
    "huntress":    "Huntress",
    "kensei":      "Kensei",
    "knight":      "Knight",
    "mystic":      "Mystic",
    "necromancer": "Necromancer",
    "ninja":       "Ninja",
    "paladin":     "Paladin",
    "priest":      "Priest",
    "rogue":       "Rogue",
    "samurai":     "Samurai",
    "sorcerer":    "Sorcerer",
    "summoner":    "Summoner",
    "trickster":   "Trickster",
    "warrior":     "Warrior",
    "wizard":      "Wizard",
}


def fetch_ssnl_data(class_name: str, stat_key: str, limit: int = 5) -> Optional[dict]:
    """
    Fetch SSNL stat leaderboard rows for a class+stat.
    class_name: title-case API name (e.g. "Sorcerer")
    stat_key:   API stat key (e.g. "HP", "Attack") — value from SSNL_STAT_MAP
    Returns {"rows": [...], "meta": {...}} or None on failure.
    """
    season = get_current_season()
    url = (
        f"{SSNL_API}?overview=1&limitPerStat={limit}&hydrate=equipment"
        f"&force=0&season={season}&seasonal=1&class={class_name}"
    )
    req = urllib.request.Request(url, headers={
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Referer": "https://tracker.realmshark.cc/ssnl-stats-leaderboard",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        rows = data.get("overview", {}).get(stat_key, {}).get("rows", [])
        return {"rows": rows, "meta": data.get("meta", {})}
    except Exception as e:
        print(f"SSNL fetch error for {class_name}/{stat_key}: {e}")
        return None


def _strip_level(enchant_name: str) -> str:
    """Remove roman numerals and level numbers from enchantment names."""
    return re.sub(r'\s+(I{1,3}|IV|V?I{0,3}|VI{0,3}|IX|X)$', '', enchant_name).strip()

def fetch_build_data(build_key_data: dict, limit: int = 15) -> Optional[dict]:
    """
    Fetch leaderboard data from realmshark tracker API.
    build_key_data: dict with 'key' and optional extra params
    """
    season  = get_current_season()
    key     = build_key_data["key"]
    seconds = build_key_data.get("seconds", 5)
    ability = build_key_data.get("abilityCount", 8)

    url = (f"{REALMSHARK_API}?limit={limit}&offset=0"
           f"&seconds={seconds}&abilityCount={ability}"
           f"&build={key}&season={season}&seasonal=1")

    # Append optional extra params
    if "minionCount" in build_key_data:
        url += f"&minionCount={build_key_data['minionCount']}"
    if "lsUptime" in build_key_data:
        url += f"&lsUptime={build_key_data['lsUptime']}"

    req = urllib.request.Request(url, headers={
        'User-Agent': 'Magic Browser',
        'Accept': 'application/json',
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            meta_season = data.get("meta", {}).get("season")
            if meta_season:
                _season_cache["value"]      = meta_season
                _season_cache["fetched_at"] = time_module.time()
            return data
    except Exception as e:
        print(f"Error fetching build data for {key}: {e}")
        return None

def analyze_builds(rows: list) -> dict:
    slots = ["Weapon", "Ability", "Armor", "Ring"]
    item_counters    = {s: Counter() for s in slots}
    enchant_counters = {s: Counter() for s in slots}

    for row in rows:
        for item in row.get("equipment", []):
            slot = item["slot"]
            if slot not in item_counters:
                continue
            item_counters[slot][(item["itemId"], item["itemName"])] += 1
            for enc in item.get("enchants", []):
                base = _strip_level(enc["enchantName"])
                enchant_counters[slot][base] += 1

    top_row   = rows[0]
    top_items = {item["slot"]: item for item in top_row.get("equipment", [])}

    avg_items  = {}
    swap_items = {}
    for slot in slots:
        most_common = item_counters[slot].most_common(3)
        if most_common:
            best_id, best_name = most_common[0][0]
            avg_items[slot] = {"itemId": best_id, "itemName": best_name}
            swaps = []
            for (iid, iname), count in most_common[1:]:
                if iname != best_name:
                    swaps.append({"itemId": iid, "itemName": iname, "count": count})
            swap_items[slot] = swaps[:2]

    # Top 2 enchants = main, next 2 = alt
    top_enchants = {}
    alt_enchants = {}
    for slot in slots:
        all_encs = enchant_counters[slot].most_common(4)
        top_enchants[slot] = [n for n, _ in all_encs[:2]]
        alt_enchants[slot] = [n for n, _ in all_encs[2:4]]

    stat_avgs = {}
    for key in ["dps", "totalDamage"]:
        vals = [r.get(key, 0) for r in rows if r.get(key)]
        stat_avgs[key] = sum(vals) / len(vals) if vals else 0

    return {
        "top":           top_row,
        "top_items":     top_items,
        "avg_items":     avg_items,
        "swap_items":    swap_items,
        "top_enchants":  top_enchants,
        "alt_enchants":  alt_enchants,
        "stat_avgs":     stat_avgs,
    }

def get_current_season() -> str:
    """
    Fetches the current season string dynamically from the API.
    Caches for 6 hours to avoid unnecessary requests.
    Falls back to 's28' if the fetch fails.
    """
    now = time_module.time()
    if _season_cache["value"] and now - _season_cache["fetched_at"] < 21600:
        return _season_cache["value"]

    # Use a reliable build that always has data to probe the season
    url = (f"{REALMSHARK_API}?limit=1&offset=0"
           f"&seconds=5&abilityCount=8&build=atk-archer&season=current&seasonal=1")
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Magic Browser',
        'Accept': 'application/json',
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            season = data.get("meta", {}).get("season", "s28")
            _season_cache["value"]      = season
            _season_cache["fetched_at"] = now
            print(f"Current season: {season}")
            return season
    except Exception as e:
        print(f"Could not fetch current season, falling back to s28: {e}")
        # Try incrementing from last known season
        if _season_cache["value"]:
            return _season_cache["value"]
        return "s28"