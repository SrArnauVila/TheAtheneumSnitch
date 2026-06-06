import urllib.request
import json
import re
import os
import ssl
from difflib import get_close_matches
from typing import Optional


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
    # Alien Invasion events (confirmed from realmstock HTML, 2025)
    45863: "Alien UFO",
    56341: "Alien Reactor",
    56342: "Alien Reactor",
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

# All canonical event names from the realmstock event notifier page.
# Used for fuzzy suggestions — kept separate from OBJECT_ID_MAP so suggestions
# work even for events whose object IDs haven't been captured yet.
KNOWN_EVENT_NAMES: list[str] = sorted([
    "5 Leaf Shamrock", "Adult Baneserpent", "Aerial Warship", "Alien Reactor",
    "Alien UFO", "Alluring Blossom", "Alpha Werewolf", "Amethyst",
    "Ancient Kaiju", "Animal Merchant", "Appetizer", "Artificial Sprite God",
    "Assembled Giant", "Astral Rift", "Avatar of the Forgotten King",
    "Beach Bum", "Beer God", "Biff", "Bilgewater's Galleon",
    "Blood Bomb", "Bloodroot Heart", "Blooming Flowers",
    "Candy Gnome", "Carnival Effigy", "Carp Emperor", "Celestial Sprite",
    "Challenger", "Commander Calbrik", "Corrupted Bramblethorn",
    "Cosmic Sprite", "Crab Sovereign", "Critter Brood", "Cube God",
    "Cyclops God", "Daeva Prison", "Daughter of Limon", "Death Knight",
    "Decaract", "Demonic Effigy", "Dread Viper", "Dwarf Miner",
    "Elder Ent Ancient", "Elder Sprite Tree", "Elf Event", "Emerald",
    "Ent Ancient", "Eternal Tormentor", "Ethereal Shrine",
    "Eye of the Storm", "Eye of the Underworld", "Festival Overseer",
    "Flesh Golem", "Flying Behemoth", "Gardener", "Gates of the Nether",
    "Ghost King", "Ghost Ship", "Ghost Ship Whirlpool", "Glitch",
    "Gobble God", "Goblin Outpost", "Goblin Patriarch", "Grand Sphinx",
    "Hemomancer", "Henchman's Horde", "Hermit God", "Hornet's Nest",
    "Infernal Ironsmith", "Insurgent Rebel Commander", "Interregnum",
    "Jack Frost", "Jester Box", "Jotunn", "Keyper", "Killer Bee Nest",
    "Kogbold Expedition Engine", "Lantern Holder",
    "Legion Excavator", "Legion General", "Legion Guard Captain",
    "Legion Head Researcher", "Legion Lead Strategist", "Legion Scout Master",
    "Legion Surveyor", "Legion Watchmaster", "Leprechaun", "Lich", "Lich King",
    "Lord of the Lost Lands", "Lost Sentry", "Mad God Mayhem",
    "Maiden of the Sea", "Mammoth Rat", "Maze Minotaur", "Mercenary",
    "Monstrous Grizzly", "Mutant Overgrowth", "Mysterious Crystal",
    "Oasis Giant", "Ore: Diamond", "Ore: Emerald", "Ore: Iron", "Ore: Stone",
    "Organ Harvester", "Oryx Horde", "Oryx Wood Totems", "Oryxmas Elf Event",
    "Pentaract", "Permafrost Lord", "Phoenix Lord", "Piranha Shoal",
    "Plague Doctor", "Possessed Pumpkin", "Present",
    "Ravenous Rot", "Reconstruction Leprechaun", "Red Demon", "Rock Dragon",
    "Ruby", "Sapphire", "Sentient Monolith", "Shady Sect Leader",
    "Shady Vagrant", "Sigma Werewolf", "Sinister Scarecrow",
    "Skeletal Centipede", "Skull Knight", "Skull Shrine", "Snowball Stash",
    "Snowy Frost God", "St Patrick's Shamrock", "St. Patrick", "Sunken Treasure",
    "Sword in the Stone", "Temple Encounter", "Temple Statue",
    "Thanksgiving Banquet", "Topaz", "Totalia", "Turkey God",
    "Valentine's Heart", "Void Prison", "Washed-Up Captain", "Water Bubbles",
    "Well of Souls", "White Snake", "Wood Totems", "World's Oyster",
    "Yokai Realm Event", "Zombie Horde",
])

# Aliases for user-friendly search — maps shorthand → canonical event name
EVENT_ALIASES = {
    # O3 special case — handled separately
    "o3":                   "__O3__",
    "oryx3":                "__O3__",
    "sanctuary":            "__O3__",
    # Alien Invasion (ambiguous — show picker)
    "alien":                "__ALIEN_AMBIGUOUS__",
    # Alien UFO
    "alienufo":             "Alien UFO",
    "ufo":                  "Alien UFO",
    # Alien Reactor
    "alienreactor":         "Alien Reactor",
    "reactor":              "Alien Reactor",
    # Classic events
    "cube":                 "Cube God",
    "cubegodsub":           "Cube God",
    "penta":                "Pentaract",
    "pentaract":            "Pentaract",
    "avatar":               "Avatar of the Forgotten King",
    "aoft":                 "Avatar of the Forgotten King",
    "hermit":               "Hermit God",
    "sphinx":               "Grand Sphinx",
    "ghost":                "Ghost Ship",
    "ghostship":            "Ghost Ship",
    "ghostwhirl":           "Ghost Ship Whirlpool",
    "ghostshipwhirl":       "Ghost Ship Whirlpool",
    "whirlpool":            "Ghost Ship Whirlpool",
    "skull":                "Skull Shrine",
    "skullshrine":          "Skull Shrine",
    "lich":                 "Lich",
    "lichking":             "Lich King",
    "lk":                   "Lich King",
    "cyclops":              "Cyclops God",
    "cyclopsgod":           "Cyclops God",
    "demon":                "Red Demon",
    "red":                  "Red Demon",
    "reddemon":             "Red Demon",
    "phoenix":              "Phoenix Lord",
    "oasis":                "Oasis Giant",
    # Modern bosses
    "grizzly":              "Monstrous Grizzly",
    "kaiju":                "Ancient Kaiju",
    "golem":                "Flesh Golem",
    "fleshgolem":           "Flesh Golem",
    "warship":              "Aerial Warship",
    "aerial":               "Aerial Warship",
    "pumpkin":              "Possessed Pumpkin",
    "halloween":            "Possessed Pumpkin",
    "skullknight":          "Skull Knight",
    "sk":                   "Skull Knight",
    "bramble":              "Corrupted Bramblethorn",
    "bramblethorn":         "Corrupted Bramblethorn",
    "maze":                 "Maze Minotaur",
    "minotaur":             "Maze Minotaur",
    "crab":                 "Crab Sovereign",
    "sovereign":            "Crab Sovereign",
    "ravenous":             "Ravenous Rot",
    "rot":                  "Ravenous Rot",
    "beer":                 "Beer God",
    "beergod":              "Beer God",
    "dwarfminer":           "Dwarf Miner",
    "dwarf":                "Dwarf Miner",
    "miner":                "Dwarf Miner",
    "wellofsouls":          "Well of Souls",
    "well":                 "Well of Souls",
    "wos":                  "Well of Souls",
    "monolith":             "Sentient Monolith",
    "deathknight":          "Death Knight",
    "dk":                   "Death Knight",
    "kogbold":              "Kogbold Expedition Engine",
    "kee":                  "Kogbold Expedition Engine",
    "infernal":             "Infernal Ironsmith",
    "ironsmith":            "Infernal Ironsmith",
    "bloodroot":            "Bloodroot Heart",
    "calbrik":              "Commander Calbrik",
    "totalia":              "Totalia",
    "daeva":                "Daeva Prison",
    "void":                 "Void Prison",
    "voidprison":           "Void Prison",
    "celestial":            "Celestial Sprite",
    "cosmic":               "Cosmic Sprite",
    "mercenary":            "Mercenary",
    "merc":                 "Mercenary",
    "insurgent":            "Insurgent Rebel Commander",
    "irc":                  "Insurgent Rebel Commander",
    "rebel":                "Insurgent Rebel Commander",
    "flowerbloom":          "Blooming Flowers",
    "blooming":             "Blooming Flowers",
    "flowers":              "Blooming Flowers",
    "water":                "Water Bubbles",
    "waterbubbles":         "Water Bubbles",
    "eternal":              "Eternal Tormentor",
    "tormentor":            "Eternal Tormentor",
    "flying":               "Flying Behemoth",
    "behemoth":             "Flying Behemoth",
    "elderent":             "Elder Ent Ancient",
    "elderentancient":      "Elder Ent Ancient",
    "ent":                  "Elder Ent Ancient",
    "entancient":           "Elder Ent Ancient",
    "critter":              "Critter Brood",
    "critterbrood":         "Critter Brood",
    "assembled":            "Assembled Giant",
    "assembledgiant":       "Assembled Giant",
    "baneserpent":          "Adult Baneserpent",
    "bane":                 "Adult Baneserpent",
    "sigma":                "Sigma Werewolf",
    "alpha":                "Alpha Werewolf",
    "werewolf":             "Alpha Werewolf",
    "goblin":               "Goblin Patriarch",
    "patriarch":            "Goblin Patriarch",
    "goblinout":            "Goblin Outpost",
    "goblinoutpost":        "Goblin Outpost",
    "outpost":              "Goblin Outpost",
    "sword":                "Sword in the Stone",
    "sits":                 "Sword in the Stone",
    "organ":                "Organ Harvester",
    "harvester":            "Organ Harvester",
    "plague":               "Plague Doctor",
    "doctor":               "Plague Doctor",
    "skeletal":             "Skeletal Centipede",
    "centipede":            "Skeletal Centipede",
    "alluring":             "Alluring Blossom",
    "blossom":              "Alluring Blossom",
    "madgod":               "Mad God Mayhem",
    "mgm":                  "Mad God Mayhem",
    "mysterious":           "Mysterious Crystal",
    "crystal":              "Mysterious Crystal",
    "mc":                   "Mysterious Crystal",
    "shady":                "Shady Sect Leader",
    "sectleader":           "Shady Sect Leader",
    "shadyvagrant":         "Shady Vagrant",
    "vagrant":              "Shady Vagrant",
    "demoneffigy":          "Demonic Effigy",
    "effigy":               "Demonic Effigy",
    "snowball":             "Snowball Stash",
    "snowballstash":        "Snowball Stash",
    "rockdragon":           "Rock Dragon",
    "rock":                 "Rock Dragon",
    "turkey":               "Turkey God",
    "thanksgiving":         "Thanksgiving Banquet",
    "elf":                  "Elf Event",
    "elfevent":             "Elf Event",
    "oryxmas":              "Oryxmas Elf Event",
    "oryxmaself":           "Oryxmas Elf Event",
    "santaevent":           "Oryxmas Elf Event",
    "beach":                "Beach Bum",
    "beachbum":             "Beach Bum",
    "gobble":               "Gobble God",
    "goblegod":             "Gobble God",
    "daughter":             "Daughter of Limon",
    "limon":                "Daughter of Limon",
    "wc":                   "Washed-Up Captain",
    "captain":              "Washed-Up Captain",
    "washed":               "Washed-Up Captain",
    "maiden":               "Maiden of the Sea",
    "lotll":                "Lord of the Lost Lands",
    "lord":                 "Lord of the Lost Lands",
    "est":                  "Elder Sprite Tree",
    "sprite":               "Elder Sprite Tree",
    "rift":                 "Astral Rift",
    "astral":               "Astral Rift",
    "arift":                "Astral Rift",
    "templestatue":         "Temple Statue",
    "temple":               "__TEMPLE_AMBIGUOUS__",
    "templeencounter":      "Temple Encounter",
    "encounter":            "Temple Encounter",
    "eyestorm":             "Eye of the Storm",
    "storm":                "Eye of the Storm",
    "eyeunderworld":        "Eye of the Underworld",
    "underworld":           "Eye of the Underworld",
    "lost":                 "Lost Sentry",
    "lostsentry":           "Lost Sentry",
    "valday":               "Valentine's Heart",
    "valentine":            "Valentine's Heart",
    "heart":                "Valentine's Heart",
    "stpatrick":            "St Patrick's Shamrock",
    "shamrock":             "St Patrick's Shamrock",
    "leprechaun":           "Leprechaun",
    "reclep":               "Reconstruction Leprechaun",
    "reconstructionlep":    "Reconstruction Leprechaun",
    "interregnum":          "Interregnum",
    "inter":                "Interregnum",
    "candygnome":           "Candy Gnome",
    "candy":                "Candy Gnome",
    "carnival":             "Carnival Effigy",
    "carnivaleffigy":       "Carnival Effigy",
    "woodtotems":           "Wood Totems",
    "totems":               "Wood Totems",
    "oryxwoodtotems":       "Oryx Wood Totems",
    "oryxwood":             "Oryx Wood Totems",
    "oryxhorde":            "Oryx Horde",
    "horde":                "Oryx Horde",
    "gatesofnether":        "Gates of the Nether",
    "gates":                "Gates of the Nether",
    "nether":               "Gates of the Nether",
    # Legion bosses
    "legsurveyor":          "Legion Surveyor",
    "surveyor":             "Legion Surveyor",
    "leggeneral":           "Legion General",
    "general":              "Legion General",
    "legwatchmaster":       "Legion Watchmaster",
    "watchmaster":          "Legion Watchmaster",
    "legstrategist":        "Legion Lead Strategist",
    "strategist":           "Legion Lead Strategist",
    "legresearcher":        "Legion Head Researcher",
    "researcher":           "Legion Head Researcher",
    "legcaptain":           "Legion Guard Captain",
    "legscout":             "Legion Scout Master",
    "legexcavator":         "Legion Excavator",
    "excavator":            "Legion Excavator",
    # Newer events (2024-2025)
    "bilgewater":           "Bilgewater's Galleon",
    "galleon":              "Bilgewater's Galleon",
    "bloodbomb":            "Blood Bomb",
    "carp":                 "Carp Emperor",
    "carpemperor":          "Carp Emperor",
    "challenger":           "Challenger",
    "decaract":             "Decaract",
    "dreadviper":           "Dread Viper",
    "viper":                "Dread Viper",
    "eyeofunderworld":      "Eye of the Underworld",
    "festivalover":         "Festival Overseer",
    "festival":             "Festival Overseer",
    "gardener":             "Gardener",
    "ghostking":            "Ghost King",
    "glitch":               "Glitch",
    "hemomancer":           "Hemomancer",
    "hemo":                 "Hemomancer",
    "henchmanshorde":       "Henchman's Horde",
    "hornets":              "Hornet's Nest",
    "hornetsnest":          "Hornet's Nest",
    "jackfrost":            "Jack Frost",
    "frost":                "Jack Frost",
    "jester":               "Jester Box",
    "jesterbox":            "Jester Box",
    "jotunn":               "Jotunn",
    "lantern":              "Lantern Holder",
    "lanternholder":        "Lantern Holder",
    "mammoth":              "Mammoth Rat",
    "mammothrat":           "Mammoth Rat",
    "mutant":               "Mutant Overgrowth",
    "mutantovergrowth":     "Mutant Overgrowth",
    "overgrowth":           "Mutant Overgrowth",
    "permafrost":           "Permafrost Lord",
    "permafrostlord":       "Permafrost Lord",
    "piranha":              "Piranha Shoal",
    "piranhashoal":         "Piranha Shoal",
    "sinisterscare":        "Sinister Scarecrow",
    "scarecrow":            "Sinister Scarecrow",
    "snowyfrost":           "Snowy Frost God",
    "sunken":               "Sunken Treasure",
    "sunkentreasure":       "Sunken Treasure",
    "whitesnake":           "White Snake",
    "yokai":                "Yokai Realm Event",
    "yokaievent":           "Yokai Realm Event",
    "zombie":               "Zombie Horde",
    "zombiehorde":          "Zombie Horde",
    "5leaf":                "5 Leaf Shamrock",
    "leafshamrock":         "5 Leaf Shamrock",
}

# Ambiguous aliases — multiple events share one short name
AMBIGUOUS_ALIASES: dict[str, list[str]] = {
    "__ALIEN_AMBIGUOUS__":  ["Alien UFO", "Alien Reactor"],
    "__TEMPLE_AMBIGUOUS__": ["Temple Statue", "Temple Encounter"],
}

# Authoritative flat list for fuzzy suggestions (derived from HTML event list)
_ALL_EVENT_NAMES: list[str] = KNOWN_EVENT_NAMES


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
    """Resolve a user query to an event name, special token, or best-guess title."""
    q = query.lower().strip().replace(" ", "").replace("'", "").replace("-", "")
    if q in EVENT_ALIASES:
        return EVENT_ALIASES[q]
    q_spaced = query.lower().strip()
    # Search full canonical list (includes events not yet in OBJECT_ID_MAP)
    for name in KNOWN_EVENT_NAMES:
        if q_spaced in name.lower():
            return name
    return query.title()


def get_suggestions(query: str, limit: int = 4) -> list[str]:
    """Return a list of known event/dungeon/item names close to the query string."""
    q_normalized = query.lower().strip()

    # 1. Event name substring match
    candidates: list[str] = [n for n in _ALL_EVENT_NAMES if q_normalized in n.lower()]

    # 2. Dungeon portal name match (e.g. "shatters" → "The Shatters")
    if not candidates:
        seen: set[str] = set()
        for drop_data in EVENT_DROPS.values():
            for d in drop_data.get("dungeon", []):
                name = d["name"] if isinstance(d, dict) else d
                if q_normalized in name.lower() and name not in seen:
                    candidates.append(name)
                    seen.add(name)

    # 3. White bag item name match
    if not candidates:
        seen2: set[str] = set()
        for drop_data in EVENT_DROPS.values():
            for w in drop_data.get("whites", []):
                name = w["name"] if isinstance(w, dict) else w
                if q_normalized in name.lower() and name not in seen2:
                    candidates.append(name)
                    seen2.add(name)

    # 4. Fuzzy fallback against event names
    if not candidates:
        candidates = get_close_matches(query.title(), _ALL_EVENT_NAMES, n=limit, cutoff=0.45)

    return candidates[:limit]


def find_event(query: str) -> dict:
    events = fetch_events()
    if not events:
        return {"type": "error", "message": "Could not fetch event data."}

    resolved = resolve_event_name(query)
    q_lower  = query.lower().strip()

    # ── Ambiguous alias (e.g. "alien" → multiple events) ─────────────────────
    if resolved in AMBIGUOUS_ALIASES:
        options = AMBIGUOUS_ALIASES[resolved]
        return {
            "type":        "ambiguous",
            "query":       query,
            "options":     options,
        }

    # ── O3 special case ───────────────────────────────────────────────────────
    if resolved == "__O3__":
        realm_scores = {}
        for e in events:
            if e["is_dungeon"] or e["score"] < 0:
                continue
            key = (e["server"], e["realm"])
            if key not in realm_scores or e["score"] > realm_scores[key]["score"]:
                realm_scores[key] = e

        def _o3_rank(r: dict) -> float:
            # Composite: score * population weight. Realms with <15 players heavily penalized.
            # Full weight at 40+ players, zero weight below 10.
            pop = r["population"]
            pop_weight = max(0.0, min(1.0, (pop - 10) / 30))
            return r["score"] * pop_weight

        top = sorted(realm_scores.values(), key=_o3_rank, reverse=True)[:7]
        return {"type": "o3", "results": top}

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

    # ── No match — compute suggestions ───────────────────────────────────────
    suggestions = get_suggestions(query)
    return {
        "type":        "no_match",
        "query":       query,
        "suggestions": suggestions,
    }