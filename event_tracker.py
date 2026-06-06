import urllib.request
import json
import re
from typing import Optional
# At the top of event_tracker.py, after imports
import os
import json
import ssl


_ssl_context = ssl.create_default_context()
_ssl_context.check_hostname = False
_ssl_context.verify_mode = ssl.CERT_NONE
_DROPS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "event_drops.json")
try:
    with open(_DROPS_PATH, "r", encoding="utf-8") as f:
        EVENT_DROPS: dict = json.load(f)
except FileNotFoundError:
    EVENT_DROPS = {}

def get_drops(event_name: str) -> dict:
    """Return drops for an event. Handles both old (strings) and new (dicts) format."""
    raw = EVENT_DROPS.get(event_name, {"whites": [], "dungeon": []})
    # Normalize old string format to new dict format
    whites = []
    for w in raw.get("whites", []):
        if isinstance(w, str):
            whites.append({"name": w, "src": ""})
        else:
            whites.append(w)
    dungeon = []
    for d in raw.get("dungeon", []):
        if isinstance(d, str):
            dungeon.append({"name": d, "src": ""})
        else:
            dungeon.append(d)
    return {"whites": whites, "dungeon": dungeon}
    
REALMSTOCK_API = "https://realmstock.network/Notifier/EventHistory"

# Object ID to event name mapping (from HTML + API data)
# The API returns objectIds as numbers, HTML shows names
OBJECT_ID_MAP = {
    # Common events
    34481: "Critter Brood",
    34485: "Assembled Giant",
    34456: "Adult Baneserpent",
    34508: "Maiden of the Sea",
    34509: "Organ Harvester",
    34510: "Sigma Werewolf",
    34515: "Flesh Golem",
    34518: "Monstrous Grizzly",
    34537: "Skull Knight",
    34538: "World's Oyster",
    34550: "Goblin Patriarch",
    34551: "Demonic Effigy",
    34553: "Sword in the Stone",
    34558: "Ancient Kaiju",
    34565: "Maze Minotaur",
    34570: "Artificial Sprite God",
    34573: "Eternal Tormentor",
    34581: "Bloodroot Heart",
    34584: "Lich King",
    34605: "Daughter of Limon",
    34499: "Washed-Up Captain",
    34489: "Plague Doctor",
    34493: "Skeletal Centipede",
    34460: "Well of Souls",
    34476: "Infernal Ironsmith",
    # Classic events
    3414: "Skull Shrine",
    3417: "Cube God",
    3412: "Grand Sphinx",
    3408: "Lord of the Lost Lands",
    3423: "Pentaract",
    3425: "Hermit God",
    # Sprite events
    2907: "Elder Sprite Tree",
    # Other events
    16995: "Insurgent Rebel Commander",
    16935: "Sentient Monolith",
    16990: "Ravenous Rot",
    16999: "Alluring Blossom",
    17969: "Keyper",
    19246: "Keyper",
    20744: "Flying Behemoth",
    20800: "Ethereal Shrine",
    21897: "Red Demon",
    21901: "Phoenix Lord",
    21924: "Oasis Giant",
    21936: "Lich",
    21959: "Avatar of the Forgotten King",
    21996: "Lord of the Lost Lands",
    22000: "Grand Sphinx",
    22003: "Skull Shrine",
    22009: "Cube God",
    22019: "Pentaract",
    22023: "Hermit God",
    22034: "Beach Bum",
    22042: "Ghost Ship",
    22109: "Kogbold Expedition Engine",
    22128: "Beer God",
    22137: "Dwarf Miner",
    22146: "Lost Sentry",
    22147: "Ethereal Shrine",
    22149: "Temple Statue",
    22150: "Temple Statue",
    23691: "Spectral Penitentiary",
    24005: "Legion General",
    24012: "Alpha Werewolf",
    24015: "Shady Sect Leader",
    24023: "Animal Merchant",
    25856: "Dwarf Miner",
    25979: "Beer God",
    29517: "Avatar of the Forgotten King",
    29866: "Candy Gnome",
    29932: "Present",
    29934: "Present Cove",
    29935: "Present",
    29936: "Present",
    29938: "Present",
    31622: "Oryxmas Elf Event",
    31639: "Oryxmas Elf Event",
    31640: "Oryxmas Elf Event",
    34476: "Infernal Ironsmith",
    41690: "Mad God Mayhem",
    41891: "Daeva Prison",
    41892: "Daeva Prison",
    41894: "Void Prison",
    44143: "Daeva Prison",
    44151: "Celestial Sprite",
    44153: "Cosmic Sprite",
    44164: "Death Knight",
    45104: "Lost Sentry",
    45521: "Rock Dragon",
    45959: "Commander Calbrik",
    49433: "Interregnum",
    51032: "Possessed Pumpkin",
    51055: "Elder Ent Ancient",
    51061: "Astral Rift",
    51072: "Crab Sovereign",
    51075: "Aerial Warship",
    51078: "Corrupted Bramblethorn",
    51810: "Mercenary",
    51811: "Mercenary",
    51812: "Mercenary",
    51813: "Mercenary",
    51835: "Mercenary",
    51914: "Interregnum",
    51944: "Turkey God",
    51987: "Zombie Horde",
    52013: "Totalia",
    52014: "Totalia",
    52015: "Totalia",
    52016: "Totalia",
    52019: "Thanksgiving Banquet",
    52094: "Commander Calbrik",
    52289: "Carnival Effigy",
    54291: "Legion Surveyor",
    54296: "Legion Watchmaster",
    54301: "Legion Lead Strategist",
    54308: "Legion Head Researcher",
    54323: "Legion Guard Captain",
    54327: "Legion Scout Master",
    54331: "Legion Excavator",
    54986: "Water Bubbles",
    54987: "Water Bubbles",
    57103: "Blooming Flowers",
    57105: "Blooming Flowers",
    57106: "Blooming Flowers",
    57107: "Blooming Flowers",
    57111: "Blooming Flowers",
    57112: "Blooming Flowers",
    # Ores
    0xA440: "Ore: Stone",
    0xA442: "Ore: Iron",
    0xA444: "Ore: Emerald",
    0xA446: "Ore: Diamond",
    # Misc
    0x6F1B: "Wood Totems",
    0x6F48: "Snowball Stash",
    0x3d15: "Present",
    0x5e49: "Candy Gnome",
    2357: "Mysterious Crystal",
    4312: "Killer Bee Nest",
    4259: "The Nest",
    # Dungeons (isDungeon=True)
    3: "Realm",
    1838: "The Crawling Depths",
    1840: "Ocean Trench",
    1857: "Davy Jones Locker",
    1884: "Woodland Labyrinth",
    1885: "Deadwater Docks",
    13983: "Davy Jones Locker",
    23691: "Spectral Penitentiary",
    40189: "Ice Citadel",
    45092: "Lost Halls",
    45591: "Lair of Draconis",
    49433: "Interregnum",
    49768: "Hidden Interregnum",
}

# Add near the top of event_tracker.py
NEXUS_KEY_DUNGEONS = {
    "pirate cave", "forest maze", "spider den", "forbidden jungle",
    "the hive", "snake pit", "sprite world", "cave of a thousand treasures",
    "ancient ruins", "magic woods", "candyland hunting grounds",
    "undead lair", "puppet master's theatre", "toxic sewers",
    "cursed library", "mad lab", "abyss of demons", "manor of the immortals",
    "haunted cemetery", "the machine", "the inner workings",
    "lair of shaitan", "secluded thicket", "high tech terror",
    "moonlight village", "beachzone", "the tavern",
    "tomb of the ancients", "the third dimension",
    "heroic undead lair", "heroic abyss of demons",
    "battle for the nexus", "belladonna's garden",
    "ice tomb", "rainbow road", "santa's workshop",
    "oryx's kitchen", "chess", "cnidarian reef",
    "parasite chambers", "sulfurous wetlands", "mountain temple",
    "puppet master's encore", "malogia", "untaris", "katalund", "forax",
}

# Aliases for user-friendly search — maps shorthand to event name patterns
EVENT_ALIASES = {
    # O3 special case — handled separately
    "o3":           "__O3__",
    "oryx3":        "__O3__",
    "sanctuary":    "__O3__",
    # Common abbreviations
    "cube":         "Cube God",
    "cubegodsub":   "Cube God",
    "penta":        "Pentaract",
    "pentaract":    "Pentaract",
    "avatar":       "Avatar of the Forgotten King",
    "aoft":         "Avatar of the Forgotten King",
    "hermit":       "Hermit God",
    "sphinx":       "Grand Sphinx",
    "ghost":        "Ghost Ship",
    "ghostship":    "Ghost Ship",
    "skull":        "Skull Shrine",
    "skullshrine":  "Skull Shrine",
    "lich":         "Lich",
    "lichking":     "Lich King",
    "lk":           "Lich King",
    "wc":           "Washed-Up Captain",
    "captain":      "Washed-Up Captain",
    "maiden":       "Maiden of the Sea",
    "lotll":        "Lord of the Lost Lands",
    "lord":         "Lord of the Lost Lands",
    "est":          "Elder Sprite Tree",
    "sprite":       "Elder Sprite Tree",
    "rift":         "Astral Rift",
    "astral":       "Astral Rift",
    "arift":        "Astral Rift",
    "cyclops":      "Cyclops God",
    "demon":        "Red Demon",
    "red":          "Red Demon",
    "phoenix":      "Phoenix Lord",
    "oasis":        "Oasis Giant",
    "grizzly":      "Monstrous Grizzly",
    "kaiju":        "Ancient Kaiju",
    "golem":        "Flesh Golem",
    "warship":      "Aerial Warship",
    "aerial":       "Aerial Warship",
    "pumpkin":      "Possessed Pumpkin",
    "skullknight":  "Skull Knight",
    "sk":           "Skull Knight",
    "bramble":      "Corrupted Bramblethorn",
    "bramblethorn": "Corrupted Bramblethorn",
    "maze":         "Maze Minotaur",
    "minotaur":     "Maze Minotaur",
    "crab":         "Crab Sovereign",
    "sovereign":    "Crab Sovereign",
    "ravenous":     "Ravenous Rot",
    "rot":          "Ravenous Rot",
    "beer":         "Beer God",
    "beergod":      "Beer God",
    "dwarfminer":   "Dwarf Miner",
    "dwarf":        "Dwarf Miner",
    "miner":        "Dwarf Miner",
    "wellofsouls":  "Well of Souls",
    "well":         "Well of Souls",
    "wos":          "Well of Souls",
    "monolith":     "Sentient Monolith",
    "deathknight":  "Death Knight",
    "dk":           "Death Knight",
    "legsurveyor":  "Legion Surveyor",
    "surveyor":     "Legion Surveyor",
    "leggeneral":   "Legion General",
    "general":      "Legion General",
    "kogbold":      "Kogbold Expedition Engine",
    "kee":          "Kogbold Expedition Engine",
    "infernal":     "Infernal Ironsmith",
    "ironsmith":    "Infernal Ironsmith",
    "bloodroot":    "Bloodroot Heart",
    "calbrik":      "Commander Calbrik",
    "totalia":      "Totalia",
    "daeva":        "Daeva Prison",
    "void":         "Void Prison",
    "voidprison":   "Void Prison",
    "celestial":    "Celestial Sprite",
    "cosmic":       "Cosmic Sprite",
    "mercenary":    "Mercenary",
    "merc":         "Mercenary",
    "insurgent":    "Insurgent Rebel Commander",
    "irc":          "Insurgent Rebel Commander",
    "rebel":        "Insurgent Rebel Commander",
    "flowerbloom":  "Blooming Flowers",
    "blooming":     "Blooming Flowers",
    "flowers":      "Blooming Flowers",
    "water":        "Water Bubbles",
    "waterbubbles": "Water Bubbles",
    "wb":           "Water Bubbles",
    "eternal":      "Eternal Tormentor",
    "tormentor":    "Eternal Tormentor",
    "flying":       "Flying Behemoth",
    "behemoth":     "Flying Behemoth",
    "elderent":     "Elder Ent Ancient",
    "elderentancient": "Elder Ent Ancient",
    "critter":      "Critter Brood",
    "critterbrood": "Critter Brood",
    "assembled":    "Assembled Giant",
    "assembledgiant": "Assembled Giant",
    "baneserpent":  "Adult Baneserpent",
    "bane":         "Adult Baneserpent",
    "sigma":        "Sigma Werewolf",
    "alpha":        "Alpha Werewolf",
    "werewolf":     "Alpha Werewolf",
    "goblin":       "Goblin Patriarch",
    "patriarch":    "Goblin Patriarch",
    "sword":        "Sword in the Stone",
    "sits":         "Sword in the Stone",
    "organ":        "Organ Harvester",
    "harvester":    "Organ Harvester",
    "plague":       "Plague Doctor",
    "doctor":       "Plague Doctor",
    "skeletal":     "Skeletal Centipede",
    "centipede":    "Skeletal Centipede",
    "skullknife":   "Skull Knight",
    "alluring":     "Alluring Blossom",
    "blossom":      "Alluring Blossom",
    "madgod":       "Mad God Mayhem",
    "mgm":          "Mad God Mayhem",
    "mysterious":   "Mysterious Crystal",
    "crystal":      "Mysterious Crystal",
    "mc":           "Mysterious Crystal",
    "shady":        "Shady Sect Leader",
    "sectleader":   "Shady Sect Leader",
    "demoneffigy":  "Demonic Effigy",
    "effigy":       "Demonic Effigy",
    "beergodsub":   "Beer God",
    "snowball":     "Snowball Stash",
    "snowballstash": "Snowball Stash",
    "ent":          "Elder Ent Ancient",
    "entancient":   "Elder Ent Ancient",
    "rockdragon":   "Rock Dragon",
    "rock":         "Rock Dragon",
    "halloween":    "Possessed Pumpkin",
    "turkey":       "Turkey God",
    "thanksgiving": "Thanksgiving Banquet",
    "elf":          "Oryxmas Elf Event",
    "oryxmas":      "Oryxmas Elf Event",
    "santaevent":   "Oryxmas Elf Event",
    "beach":        "Beach Bum",
    "beachbum":     "Beach Bum",
    "gobblegodsub": "Gobble God",
    "gobble":       "Gobble God",
    "daughter":     "Daughter of Limon",
    "limon":        "Daughter of Limon",
    "washed":       "Washed-Up Captain",
    "templestatue": "Temple Statue",
    "temple":       "Temple Statue",
    "eyestorm":     "Eye of the Storm",
    "eyes":         "Eye of the Storm",
    "ghostshipwhirl": "Ghost Ship Whirlpool",
    "whirlpool":    "Ghost Ship Whirlpool",
    "lost":         "Lost Sentry",
    "lostsentry":   "Lost Sentry",
    "carpenter":    "Carpenter Event",
    "valday":       "Valentine's Heart",
    "heart":        "Valentine's Heart",
    "stpatrick":    "St Patrick's Shamrock",
    "shamrock":     "St Patrick's Shamrock",
    "leprechaun":   "Leprechaun",
    "interregnum":  "Interregnum",
    "inter":        "Interregnum",
    "candygnome":   "Candy Gnome",
    "candy":        "Candy Gnome",
    "carnival":     "Carnival Effigy",
    "carnivaleffigy": "Carnival Effigy",
    "woodtotems":   "Wood Totems",
    "totems":       "Wood Totems",
    "oryxhorde":    "Oryx Horde",
    "horde":        "Oryx Horde",
    "gatesofnether": "Gates of the Nether",
    "gates":        "Gates of the Nether",
    "nether":       "Gates of the Nether",
}


def fetch_events() -> list[dict]:
    """Fetch current event history from realmstock API."""
    req = urllib.request.Request(
        REALMSTOCK_API,
        headers={
            "User-Agent": "Magic Browser",
            "Accept":     "application/json",
            "Referer":    "https://realmstock.com/",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=10, context=_ssl_context) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if not data.get("success"):
                return []
            lines = data["value"].strip().split("\n")
            events = []
            for line in lines:
                if not line.strip():
                    continue
                parts = line.strip().split("|")
                if len(parts) < 10:
                    continue
                try:
                    obj_id     = int(parts[0])
                    realm      = parts[1]
                    server     = parts[2]
                    population = int(parts[3])
                    max_pop    = int(parts[4]) if parts[4] != "?" else 85
                    score      = int(parts[5]) if parts[5] != "?" else -1
                    time_str   = parts[6]
                    uuid       = parts[7]
                    is_dungeon = parts[8].lower() == "true"
                    dust       = int(parts[9]) if parts[9].isdigit() else 0

                    event_name = OBJECT_ID_MAP.get(obj_id, f"Unknown ({obj_id})")
                    events.append({
                        "obj_id":     obj_id,
                        "name":       event_name,
                        "realm":      realm,
                        "server":     server,
                        "population": population,
                        "max_pop":    max_pop,
                        "score":      score,
                        "time":       time_str,
                        "uuid":       uuid,
                        "is_dungeon": is_dungeon,
                        "dust":       dust,
                    })
                except (ValueError, IndexError):
                    continue
            return events
    except Exception as e:
        print(f"Error fetching events: {e}")
        return []


def resolve_event_name(query: str) -> str:
    """Resolve a user query to an event name or special token."""
    q = query.lower().strip().replace(" ", "").replace("'", "").replace("-", "")
    if q in EVENT_ALIASES:
        return EVENT_ALIASES[q]
    # Try partial match against alias values
    q_spaced = query.lower().strip()
    for name in set(OBJECT_ID_MAP.values()):
        if q_spaced in name.lower():
            return name
    return query.title()


def find_event(query: str) -> dict:
    events = fetch_events()
    if not events:
        return {"type": "error", "message": "Could not fetch event data."}

    resolved = resolve_event_name(query)
    q_lower  = query.lower().strip()

    # ── O3 special case ───────────────────────────────────────────────────────
    if resolved == "__O3__":
        realm_scores = {}
        for e in events:
            if e["is_dungeon"] or e["score"] < 0:
                continue
            key = (e["server"], e["realm"])
            if key not in realm_scores or e["score"] > realm_scores[key]["score"]:
                realm_scores[key] = e
        top5 = sorted(realm_scores.values(), key=lambda x: x["score"], reverse=True)[:5]
        return {"type": "o3", "results": top5}

    # ── Mode 2 FIRST: dungeon portal match ────────────────────────────────────
    # Check this BEFORE event name match so "!find nest" hits the dungeon
    # portal search rather than matching "The Nest" as a live dungeon event
    dungeon_events      = []
    matched_dungeon     = None
    matched_dungeon_src = ""
    for event_name, drop_data in EVENT_DROPS.items():
        for dung in drop_data.get("dungeon", []):
            dung_name = dung["name"] if isinstance(dung, dict) else dung
            dung_src  = dung.get("src", "") if isinstance(dung, dict) else ""
            if q_lower in dung_name.lower():
                matched_dungeon     = dung_name
                matched_dungeon_src = dung_src
                dungeon_events.append(event_name)
                break

    if dungeon_events:
        active = [
            e for e in events
            if e["name"] in dungeon_events and not e["is_dungeon"]
        ]
        active.sort(key=lambda x: x["score"], reverse=True)
        return {
            "type":            "event",
            "results":         active,
            "query_name":      matched_dungeon or query.title(),
            "search_mode":     "dungeon",
            "possible_events": dungeon_events,
            "drops": {
                "whites":  [],
                "dungeon": [{"name": matched_dungeon, "src": matched_dungeon_src}]
                           if matched_dungeon else [],
            },
        }
    
    # ── Mode 1 LAST: active event name match ──────────────────────────────────
    # Only runs if query didn't match any dungeon portal or item drop
    name_matches = [
        e for e in events
        if resolved.lower() in e["name"].lower()
        and not e["is_dungeon"]
    ]
    if name_matches:
        name_matches.sort(key=lambda x: x["score"], reverse=True)
        drops = get_drops(name_matches[0]["name"])
        return {
            "type":        "event",
            "results":     name_matches,
            "query_name":  resolved,
            "search_mode": "event",
            "drops":       drops,
        }

    # ── Mode 3: item drop match ───────────────────────────────────────────────
    item_events      = []
    matched_item     = None
    matched_item_src = ""
    for event_name, drop_data in EVENT_DROPS.items():
        for item in drop_data.get("whites", []):
            item_name = item["name"] if isinstance(item, dict) else item
            item_src  = item.get("src", "") if isinstance(item, dict) else ""
            if q_lower in item_name.lower():
                matched_item     = item_name
                matched_item_src = item_src
                item_events.append(event_name)
                break

    if item_events:
        active = [
            e for e in events
            if e["name"] in item_events and not e["is_dungeon"]
        ]
        active.sort(key=lambda x: x["score"], reverse=True)
        return {
            "type":            "event",
            "results":         active,
            "query_name":      matched_item or query.title(),
            "search_mode":     "item",
            "possible_events": item_events,
            "drops": {
                "whites":  [{"name": matched_item, "src": matched_item_src}]
                           if matched_item else [],
                "dungeon": [],
            },
        }

    # ── No match ──────────────────────────────────────────────────────────────
    return {
        "type":        "event",
        "results":     [],
        "query_name":  resolved,
        "search_mode": "event",
        "drops":       {},
    }