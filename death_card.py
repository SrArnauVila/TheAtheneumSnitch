import urllib.request
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as _cffi_req
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False
from PIL import Image, ImageDraw, ImageFont
from typing import Optional
from datetime import datetime
import pytz
import os

_TZ_EASTERN = pytz.timezone("America/New_York")

def format_death_time(raw: str) -> str:
    """Parse RealmEye ISO UTC death time and display in US Eastern, no seconds."""
    try:
        s = raw.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
        dt_et = dt.astimezone(_TZ_EASTERN)
        return dt_et.strftime("%b %d, %Y  %I:%M %p")   # e.g. "Jun 06, 2026  11:53 AM"
    except Exception:
        return raw

FONT      = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

CARD_W, CARD_H = 500, 160
BG_COLOR        = (20, 20, 30)
ACCENT_COLOR    = (200, 60, 60)
TEXT_PRIMARY    = (255, 255, 255)
TEXT_SECONDARY  = (180, 180, 200)
TEXT_MUTED      = (120, 120, 140)

SPRITE_SIZE  = 50
ITEM_SIZE    = 40
ITEM_SPACING = 44

_RARITIES = {"divine", "legendary", "rare", "uncommon"}
RARITY_COLORS = {
    "divine":    (255, 200,   0, 90),
    "legendary": (180,  60, 255, 90),
    "rare":      ( 60, 130, 255, 90),
    "uncommon":  ( 60, 200,  80, 90),
}


def fetch_latest_deaths(guild_name: str) -> list:
    """Returns a list of death dicts, skipping private deaths."""
    url = f"https://www.realmeye.com/recent-deaths-in-guild/{guild_name}"
    try:
        if _HAS_CURL_CFFI:
            resp = _cffi_req.get(url, impersonate="chrome120", timeout=15)
            resp.raise_for_status()
            html = resp.text
        else:
            req = urllib.request.Request(url, headers={"User-Agent": "Magic Browser"})
            html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8")
    except Exception as e:
        print(f"Error fetching graveyard: {e}")
        return []

    soup = BeautifulSoup(html, "html.parser")
    tbody = soup.find("tbody")
    if not tbody:
        return []

    deaths = []
    for row in tbody.find_all("tr"):
        tds = row.find_all("td")
        if len(tds) < 8:
            continue

        # Skip private deaths
        name = tds[1].get_text(strip=True)
        if name == "Private" or not name:
            continue

        # Character sprite coords
        char_span = tds[0].find("span", class_="character")
        if not char_span:
            continue
        bp = char_span.get("style", "")
        try:
            coords = bp.split("background-position:")[1].split(";")[0].strip()
            sx = abs(int(coords.split("px")[0].strip()))
            sy = abs(int(coords.split("px")[1].strip().split("px")[0].strip()))
        except Exception:
            continue

        # Equipment — store wiki href for image lookup
        equipment = []
        for a_tag in tds[5].find_all("a"):
            href = a_tag.get("href", "")
            span = a_tag.find("span")
            if not span:
                continue
            title = span.get("title", "")
            item_name = title.split("\n")[0].strip() if title else "Unknown"
            title_first = item_name.split()[0].lower() if item_name else ""
            rarity = title_first if title_first in _RARITIES else ""
            # y ≥ 96 → shiny sprite in the sheet; y < 96 → normal sprite
            is_shiny = False
            try:
                bp = span.get("style", "").split("background-position:")[1].strip()
                iy = abs(int(bp.split("px")[1].strip().split("px")[0].strip()))
                is_shiny = iy >= 96
            except Exception:
                pass
            equipment.append({"name": item_name, "href": href, "rarity": rarity, "shiny": is_shiny})

        # Stats — read the visible "X/8" text directly; data-stats[0] is unrelated
        stats_span = tds[6].find("span", class_="player-stats")
        stats_text = "?/8"
        if stats_span:
            for i_tag in stats_span.find_all("i"):
                i_tag.decompose()
            raw = stats_span.get_text(strip=True)
            stats_text = raw.split()[0] if raw else "?/8"

        # Total fame — strip the info icon text
        total_fame_span = tds[4].find("span", class_="total-fame")
        if total_fame_span:
            # Remove child elements (the info icon) and get just the number
            for child in total_fame_span.find_all("i"):
                child.decompose()
            total_fame = total_fame_span.get_text(strip=True).replace("\xa0", "").replace(" ", "")
        else:
            total_fame = tds[4].get_text(strip=True)

        deaths.append({
            "player-name":  name,
            "class_id":     int(char_span.get("data-class", 0)),
            "time":         tds[2].get_text(strip=True),
            "base_fame":    tds[3].get_text(strip=True),
            "total_fame":   total_fame,
            "equipment":    equipment,
            "stats":        stats_text,
            "killed_by":    tds[7].get_text(strip=True),
            "skin_x":       sx,
            "skin_y":       sy,
        })

    return deaths


CLASS_NAMES = {
    775: "Archer",
    800: "Assassin",
    796: "Bard",
    819: "Druid",
    802: "Huntress",
    818: "Kensei",
    798: "Knight",
    803: "Mystic",
    801: "Necromancer",
    806: "Ninja",
    799: "Paladin",
    784: "Priest",
    768: "Rogue",
    785: "Samurai",
    805: "Sorcerer",
    817: "Summoner",
    804: "Trickster",
    797: "Warrior",
    782: "Wizard",
}

def _draw_class_sprite(class_id: int) -> Image.Image:
    """Load the downloaded class image for this class_id."""
    path = f"./images/classes/{class_id}.png"
    try:
        img = Image.open(path).convert("RGBA")
        img = img.resize((SPRITE_SIZE, SPRITE_SIZE), Image.NEAREST)
        return img
    except Exception as e:
        print(f"Class image load error for {class_id}: {e}")
        # Fallback: gray circle with letter
        name = CLASS_NAMES.get(class_id, "?")
        fallback = Image.new("RGBA", (SPRITE_SIZE, SPRITE_SIZE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(fallback)
        draw.ellipse([(2, 2), (SPRITE_SIZE-2, SPRITE_SIZE-2)], fill=(100, 100, 120, 220))
        try:
            font = ImageFont.truetype(FONT_BOLD, 20)
        except Exception:
            font = ImageFont.load_default()
        letter = name[0].upper()
        bbox = draw.textbbox((0, 0), letter, font=font)
        tx = (SPRITE_SIZE - (bbox[2] - bbox[0])) // 2
        ty = (SPRITE_SIZE - (bbox[3] - bbox[1])) // 2
        draw.text((tx, ty), letter, font=font, fill=(255, 255, 255))
        return fallback

ITEM_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images", "items")

def _fetch_item_image(href: str, is_shiny: bool = False) -> Optional[Image.Image]:
    """Download item sprite from RealmEye wiki page, cached locally by slug.

    Shiny items are detected via background-position y ≥ 96 on the death page
    (shiny sprites sit lower in the sprite sheet than normal sprites).
    The wiki page shows a separate '(Shiny)' image for items that have one.
    """
    if not href:
        return None
    slug = href.strip("/").split("/")[-1]
    suffix = "_shiny" if is_shiny else ""
    os.makedirs(ITEM_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(ITEM_CACHE_DIR, f"{slug}{suffix}.png")

    if os.path.exists(cache_path):
        try:
            return Image.open(cache_path).convert("RGBA").resize((ITEM_SIZE, ITEM_SIZE), Image.NEAREST)
        except Exception:
            pass

    try:
        wiki_url = f"https://www.realmeye.com{href}"
        req = urllib.request.Request(wiki_url, headers={"User-Agent": "Magic Browser"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8")

        soup = BeautifulSoup(html, "html.parser")
        wiki_div = soup.find("div", id="d")
        if not wiki_div:
            return None

        target_img = None
        if is_shiny:
            for img in wiki_div.find_all("img"):
                if "(Shiny)" in img.get("alt", ""):
                    target_img = img
                    break
        if not target_img:
            target_img = wiki_div.find("img")   # normal, or fallback when no shiny variant exists

        if not target_img:
            return None

        img_src = target_img.get("src", "")
        if not img_src:
            return None

        img_url = f"https://www.realmeye.com{img_src}" if img_src.startswith("/") else img_src
        req2 = urllib.request.Request(img_url, headers={"User-Agent": "Magic Browser"})
        with urllib.request.urlopen(req2, timeout=10) as resp2:
            data = resp2.read()

        with open(cache_path, "wb") as f:
            f.write(data)

        return Image.open(cache_path).convert("RGBA").resize((ITEM_SIZE, ITEM_SIZE), Image.NEAREST)
    except Exception as e:
        print(f"Item fetch error for {href} (shiny={is_shiny}): {e}")
        return None


def build_death_card(death: dict, out_path: str = "./images/death_output.png"):
    """Build a death announcement card and save it."""
    card = Image.new("RGBA", (CARD_W, CARD_H), BG_COLOR)
    draw = ImageDraw.Draw(card)

    try:
        font_bold  = ImageFont.truetype(FONT_BOLD, 16)
        font_name  = ImageFont.truetype(FONT_BOLD, 18)
        font_small = ImageFont.truetype(FONT, 13)
        font_tiny  = ImageFont.truetype(FONT, 11)
    except Exception:
        font_bold  = ImageFont.load_default()
        font_name  = font_bold
        font_small = font_bold
        font_tiny  = font_bold

    # ── Red accent bar on left ────────────────────────────────────────────────
    draw.rectangle([(0, 0), (4, CARD_H)], fill=ACCENT_COLOR)

    # ── Character sprite ──────────────────────────────────────────────────────
    try:
        sprite = _draw_class_sprite(death.get("class_id", 0))
        card.paste(sprite, (12, 12), sprite)
    except Exception as e:
        print(f"Sprite error: {e}")

    # ── Player name + skull ───────────────────────────────────────────────────
    text_x = 12 + SPRITE_SIZE + 12
    draw.text((text_x, 10), f"☠ {death['player-name']}", font=font_name, fill=ACCENT_COLOR)

    # ── Killed by ─────────────────────────────────────────────────────────────
    def _inline(x: int, y: int, label: str, value: str, fl, fv) -> int:
        draw.text((x, y), label, font=fl, fill=TEXT_SECONDARY)
        lw = draw.textbbox((x, y), label, font=fl)[2]
        draw.text((lw, y), value, font=fv, fill=TEXT_SECONDARY)
        return draw.textbbox((lw, y), value, font=fv)[2]

    _inline(text_x, 32, "Killed by: ", death["killed_by"], font_bold, font_small)

    # ── Stats + Fame ─────────────────────────────────────────────────────────
    cx = text_x
    for lbl, val in [("Stats: ", death["stats"]),
                     ("   Base Fame: ", death["base_fame"]),
                     ("   Total Fame: ", death["total_fame"])]:
        draw.text((cx, 52), lbl, font=font_bold, fill=TEXT_SECONDARY)
        lw = draw.textbbox((cx, 52), lbl, font=font_bold)[2]
        draw.text((lw, 52), val, font=font_small, fill=TEXT_SECONDARY)
        cx = draw.textbbox((lw, 52), val, font=font_small)[2]

    # ── Time ─────────────────────────────────────────────────────────────────
    draw.text((text_x, 70), format_death_time(death["time"]), font=font_tiny, fill=TEXT_MUTED)

    # ── Divider ───────────────────────────────────────────────────────────────
    draw.rectangle([(12, 98), (CARD_W - 12, 99)], fill=(50, 50, 65))

    # ── Equipment row ────────────────────────────────────────────────────────
    draw.text((12, 101), "Equipment:", font=font_tiny, fill=TEXT_MUTED)
    item_y = 114

    for i, item in enumerate(death["equipment"][:5]):
        ix = 12 + i * ITEM_SPACING
        draw.rectangle(
            [(ix, item_y), (ix + ITEM_SIZE, item_y + ITEM_SIZE)],
            fill=(35, 35, 50), outline=(60, 60, 80)
        )
        rarity_color = RARITY_COLORS.get(item.get("rarity", ""))
        if rarity_color:
            overlay = Image.new("RGBA", (ITEM_SIZE, ITEM_SIZE), rarity_color)
            card.paste(overlay, (ix, item_y), overlay)
        try:
            item_img = _fetch_item_image(item.get("href", ""), item.get("shiny", False))
            if item_img:
                card.paste(item_img, (ix, item_y), item_img)
        except Exception as e:
            print(f"Item fetch error for {item['name']}: {e}")

    # ── Save ──────────────────────────────────────────────────────────────────
    os.makedirs("./images", exist_ok=True)
    card.save(out_path)
    return out_path
