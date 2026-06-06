import json
import time
import sys

try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from bs4 import BeautifulSoup
except ImportError:
    print("Run:  pip install undetected-chromedriver selenium beautifulsoup4")
    sys.exit(1)


def _make_driver():
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    # NO headless — opens a real Chrome window
    # RealmEye blocks all headless browsers, visible window bypasses this
    return uc.Chrome(options=options, version_main=148, use_subprocess=True)

# ── Bag types we care about (matched against img alt= attribute) ──────────────
# From the HTML:  <img alt="White Bag" ...>  /  <img alt="Orange Bag" ...>
WANTED_BAGS = {"White Bag", "Orange Bag", "Golden Bag"}

# ── Event slugs ───────────────────────────────────────────────────────────────
EVENT_SLUGS = {
    # Classic
    "Avatar of the Forgotten King":   "avatar-of-the-forgotten-king",
    "Cube God":                        "cube-god",
    "Cyclops God":                     "cyclops-god",
    "Ghost Ship":                      "ghost-ship",
    "Grand Sphinx":                    "grand-sphinx",
    "Hermit God":                      "hermit-god",
    "Killer Bee Nest":                 "killer-bee-nest",
    "Lich":                            "lich",
    "Lich King":                       "lich-king",
    "Lord of the Lost Lands":          "lord-of-the-lost-lands",
    "Pentaract":                       "pentaract",
    "Red Demon":                       "red-demon",
    "Skull Shrine":                    "skull-shrine",
    # World Events
    "Adult Baneserpent":               "adult-baneserpent",
    "Aerial Warship":                  "aerial-warship",
    "Alluring Blossom":                "alluring-blossom",
    "Alpha Werewolf":                  "alpha-werewolf",
    "Ancient Kaiju":                   "ancient-kaiju",
    "Animal Merchant":                 "animal-merchant",
    "Artificial Sprite God":           "artificial-sprite-god",
    "Assembled Giant":                 "assembled-giant",
    "Astral Rift":                     "astral-rift",
    "Bloodroot Heart":                 "bloodroot-heart",
    "Blooming Flowers":                "blooming-flowers",
    "Commander Calbrik":               "commander-calbrik",
    "Corrupted Bramblethorn":          "corrupted-bramblethorn",
    "Crab Sovereign":                  "crab-sovereign",
    "Critter Brood":                   "critter-brood",
    "Daughter of Limon":               "daughter-of-limon",
    "Death Knight":                    "death-knight",
    "Demonic Effigy":                  "demonic-effigy",
    "Dwarf Miner":                     "dwarf-miner",
    "Elder Ent Ancient":               "elder-ent-ancient",
    "Elder Sprite Tree":               "elder-sprite-tree",
    "Eternal Tormentor":               "eternal-tormentor",
    "Ethereal Shrine":                 "ethereal-shrine",
    "Eye of the Storm":                "eye-of-the-storm",
    "Flesh Golem":                     "flesh-golem",
    "Flying Behemoth":                 "flying-behemoth",
    "Gates of the Nether":             "gates-of-the-nether",
    "Goblin Patriarch":                "goblin-patriarch",
    "Infernal Ironsmith":              "infernal-ironsmith",
    "Insurgent Rebel Commander":       "insurgent-rebel-commander",
    "Interregnum":                     "interregnum",
    "Keyper":                          "keyper",
    "Kogbold Expedition Engine":       "kogbold-expedition-engine",
    "Legion Excavator":                "legion-excavator",
    "Legion General":                  "legion-general",
    "Legion Guard Captain":            "legion-guard-captain",
    "Legion Head Researcher":          "legion-head-researcher",
    "Legion Lead Strategist":          "legion-lead-strategist",
    "Legion Scout Master":             "legion-scout-master",
    "Legion Surveyor":                 "legion-surveyor",
    "Legion Watchmaster":              "legion-watchmaster",
    "Lost Sentry":                     "lost-sentry",
    "Mad God Mayhem":                  "mad-god-mayhem",
    "Maiden of the Sea":               "maiden-of-the-sea",
    "Maze Minotaur":                   "maze-minotaur",
    "Mercenary":                       "mercenary",
    "Monstrous Grizzly":               "monstrous-grizzly",
    "Mysterious Crystal":              "mysterious-crystal",
    "Oasis Giant":                     "oasis-giant",
    "Organ Harvester":                 "organ-harvester",
    "Oryx Horde":                      "oryx-horde",
    "Phoenix Lord":                    "phoenix-lord",
    "Plague Doctor":                   "plague-doctor",
    "Ravenous Rot":                    "ravenous-rot",
    "Rock Dragon":                     "rock-dragon",
    "Sentient Monolith":               "sentient-monolith",
    "Shady Sect Leader":               "shady-sect-leader",
    "Sigma Werewolf":                  "sigma-werewolf",
    "Skeletal Centipede":              "skeletal-centipede",
    "Skull Knight":                    "skull-knight",
    "Sword in the Stone":              "sword-in-the-stone",
    "Totalia":                         "totalia",
    "Void Prison":                     "void-prison",
    "Washed-Up Captain":               "washed-up-captain",
    "Water Bubbles":                   "water-bubbles",
    "Well of Souls":                   "well-of-souls",
    "World's Oyster":                  "world-s-oyster",
    # Celestial
    "Celestial Sprite":                "celestial-sprite",
    "Cosmic Sprite":                   "cosmic-sprite",
    "Daeva Prison":                    "daeva-prison",
    # Seasonal
    "Beach Bum":                       "beach-bum",
    "Beer God":                        "beer-god",
    "Candy Gnome":                     "candy-gnome",
    "Carnival Effigy":                 "carnival-effigy",
    "Gobble God":                      "gobble-god",
    "Jack Frost":                      "jack-frost",
    "Leprechaun":                      "leprechaun",
    "Oryxmas Elf Event":               "oryxmas-elf-event",
    "Permafrost Lord":                 "permafrost-lord",
    "Possessed Pumpkin":               "possessed-pumpkin",
    "Present":                         "present",
    "Sinister Scarecrow":              "sinister-scarecrow",
    "Snowball Stash":                  "snowball-stash",
    "Snowy Frost God":                 "snowy-frost-god",
    "St Patrick's Shamrock":           "st-patrick-s-shamrock",
    "Thanksgiving Banquet":            "thanksgiving-banquet",
    "Turkey God":                      "turkey-god",
    "Valentine's Heart":               "valentine-s-heart",
    "Wood Totems":                     "wood-totems",
    "Zombie Horde":                    "zombie-horde",
    # Rare / Special
    "Alien UFO":                       "alien-ufo",
    "Bilgewater's Galleon":            "bilgewater-s-galleon",
    "Blood Bomb":                      "blood-bomb",
    "Decaract":                        "decaract",
    "Dread Viper":                     "dread-viper",
    "Eye of the Underworld":           "eye-of-the-underworld",
    "Ghost King":                      "ghost-king",
    "Hemomancer":                      "hemomancer",
    "Hornet's Nest":                   "hornet-s-nest",
    "Jotunn":                          "jotunn",
    "Mammoth Rat":                     "mammoth-rat",
    "Mutant Overgrowth":               "mutant-overgrowth",
    "Piranha Shoal":                   "piranha-shoal",
    "Sunken Treasure":                 "sunken-treasure",
    "White Snake":                     "white-snake",
    "Yokai Realm Event":               "yokai-realm-event",
    # Dungeons
    "The Shatters":                    "the-shatters",
    "Lost Halls":                      "lost-halls",
    "The Void":                        "the-void",
    "The Cultist Hideout":             "the-cultist-hideout",
    "The Nest":                        "the-nest",
    "Fungal Cavern":                   "fungal-cavern",
    "Crystal Cavern":                  "crystal-cavern",
    "The Crawling Depths":             "the-crawling-depths",
    "Ocean Trench":                    "ocean-trench",
    "Davy Jones' Locker":              "davy-jones-locker",
    "Woodland Labyrinth":              "woodland-labyrinth",
    "Deadwater Docks":                 "deadwater-docks",
    "Spectral Penitentiary":           "spectral-penitentiary",
    "Ice Citadel":                     "ice-citadel",
    "Lair of Draconis":                "lair-of-draconis",
}

REALMEYE_BASE = "https://www.realmeye.com/wiki/"


def parse_drops(html: str) -> dict:
    soup    = BeautifulSoup(html, "html.parser")
    whites  = []   # list of {"name": str, "src": str}
    portals = []   # list of {"name": str, "src": str}

    drops_heading = soup.find("h3", id="drops")
    if not drops_heading:
        return {"whites": [], "dungeon": []}

    loot_table = None
    for sibling in drops_heading.find_next_siblings():
        if sibling.name == "table":
            loot_table = sibling
            break
        tbl = sibling.find("table") if hasattr(sibling, "find") else None
        if tbl:
            loot_table = tbl
            break

    if not loot_table:
        return {"whites": [], "dungeon": []}

    current_bag = None

    for row in loot_table.find_all("tr"):
        tds = row.find_all("td", recursive=False)
        if not tds:
            continue

        # Portal row
        if len(tds) == 1 and tds[0].get("colspan") == "4":
            img = tds[0].find("img")
            if img:
                name = img.get("title", img.get("alt", "")).replace(" Portal", "").strip()
                src  = img.get("src", "")
                if name and len(name) > 2:
                    portals.append({"name": name, "src": src})
            continue

        # Bag image
        first_td = tds[0]
        bag_img  = first_td.find("img", alt=lambda a: a and a.endswith("Bag"))
        if bag_img:
            current_bag = bag_img.get("alt", "")

        if current_bag not in WANTED_BAGS:
            continue

        # Item cells
        for cell in tds[1:]:
            img = cell.find("img", alt=lambda a: a and a not in (
                "", "Tier 10 Weapons", "Tier 11 Weapons", "Tier 12 Weapons",
                "Tier 10 Alternate Weapons", "Tier 11 Alternate Weapons",
                "Tier 12 Alternate Weapons", "Tier 10 Armor", "Tier 11 Armor",
                "Tier 12 Armor", "Tier 5 Abilities", "Tier 6 Abilities",
                "Tier 5 Rings", "Tier 6 Rings", "Stat Increase Potions",
                "Potion of Life", "Potion of Mana", "Pet Eggs", "Sword Rune",
            ) and "Blueprint" not in (a or ""))
            if img:
                name = img.get("alt", "").strip()
                src  = img.get("src", "")
                if name and len(name) > 2:
                    whites.append({"name": name, "src": src})

    def clean(lst):
        seen, out = set(), []
        for x in lst:
            if x["name"] and x["name"] not in seen:
                seen.add(x["name"])
                out.append(x)
        return out

    return {"whites": clean(whites), "dungeon": clean(portals)}


def scrape_all(output_path: str = "event_drops.json"):
    results  = {}
    total    = len(EVENT_SLUGS)
    failed   = []
    no_drops = []

    print("Starting Selenium Chrome driver...")
    driver = _make_driver()

    try:
        print("Visiting RealmEye homepage...")
        driver.get("https://www.realmeye.com/")
        time.sleep(2)

        print(f"Scraping {total} events...\n")

        for i, (name, slug) in enumerate(EVENT_SLUGS.items(), 1):
            print(f"[{i:>3}/{total}] {name}...", end=" ", flush=True)
            url = REALMEYE_BASE + slug

            try:
                driver.get(url)
                WebDriverWait(driver, 12).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                time.sleep(0.8)

                html  = driver.page_source
                drops = parse_drops(html)
                results[name] = drops

                w = len(drops["whites"])
                d = len(drops["dungeon"])

                if w == 0 and d == 0:
                    no_drops.append(name)
                    print("⚠  no drops found")
                else:
                    parts = []
                    if w:
                        preview = ", ".join(x["name"] for x in drops["whites"][:2])
                        parts.append(f"{w} UTs: {preview}{'...' if w > 2 else ''}")
                    if d:
                        parts.append(f"dungeon: {drops['dungeon'][0]['name']}")
                    print("✓  " + " | ".join(parts))

            except Exception as e:
                print(f"FAILED — {e}")
                failed.append(name)
                results[name] = {"whites": [], "dungeon": []}

            time.sleep(0.4)

    finally:
        driver.quit()

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n{'─'*60}")
    print(f"Saved → {output_path}")
    print(f"Total: {total}  |  Failed: {len(failed)}  |  No drops: {len(no_drops)}")

    if failed:
        print(f"\nFailed (check slugs):")
        for n in failed:
            print(f"  {n}  →  {EVENT_SLUGS[n]}")

    if no_drops:
        print(f"\nNo drops found — may need manual entry:")
        for n in no_drops:
            print(f"  {n}")

    return results




def debug_page(slug: str = "avatar-of-the-forgotten-king"):
    """Dump the raw HTML of one page so we can see what Selenium actually gets."""
    print(f"Fetching {REALMEYE_BASE}{slug}...")
    driver = _make_driver()
    try:
        driver.get("https://www.realmeye.com/")
        time.sleep(2)
        driver.get(REALMEYE_BASE + slug)
        WebDriverWait(driver, 12).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(1)
        html = driver.page_source

        # Save full HTML to file so you can inspect it
        with open("debug_avatar.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("Saved full HTML to debug_avatar.html")

        # Also print any table found
        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")
        print(f"\nFound {len(tables)} tables on page")
        for i, t in enumerate(tables):
            imgs = t.find_all("img")
            alts = [img.get("alt","") for img in imgs]
            print(f"  Table {i}: {len(imgs)} images, alts: {alts[:5]}")

        # Check for bag images anywhere on page
        bag_imgs = soup.find_all("img", alt=lambda a: a and "Bag" in a)
        print(f"\nBag images found anywhere: {len(bag_imgs)}")
        for b in bag_imgs:
            print(f"  alt='{b.get('alt')}' src='{b.get('src','')[:60]}'")

    finally:
        driver.quit()


if __name__ == "__main__":
    scrape_all("event_drops.json")