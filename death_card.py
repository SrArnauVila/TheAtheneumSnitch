import urllib.request
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
import os

FONT      = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

CARD_W, CARD_H = 500, 160
BG_COLOR        = (20, 20, 30)
ACCENT_COLOR    = (200, 60, 60)
TEXT_PRIMARY    = (255, 255, 255)
TEXT_SECONDARY  = (180, 180, 200)
TEXT_MUTED      = (120, 120, 140)

SPRITE_SIZE = 50
ITEM_SIZE   = 40
ITEM_SPACING = 44


def fetch_latest_deaths(guild_name: str) -> list:
    """Returns a list of death dicts, skipping private deaths."""
    url = f"https://www.realmeye.com/recent-deaths-in-guild/{guild_name}"
    req = urllib.request.Request(url, headers={"User-Agent": "Magic Browser"})
    try:
        page = urllib.request.urlopen(req, timeout=10)
        html = page.read().decode("utf-8")
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

        # Equipment
        equipment = []
        for a_tag in tds[5].find_all("a"):
            span = a_tag.find("span")
            if not span:
                continue
            title = span.get("title", "")
            item_name = title.split("\n")[0].strip() if title else "Unknown"
            style = span.get("style", "")
            try:
                bp2 = style.split("background-position:")[1].strip()
                ix = abs(int(bp2.split("px")[0].strip()))
                iy = abs(int(bp2.split("px")[1].strip().split("px")[0].strip()))
            except Exception:
                continue
            equipment.append({"name": item_name, "x": ix, "y": iy})

        # Stats — "2/8" format
        stats_span = tds[6].find("span", class_="player-stats")
        stats_text = "?/8"
        if stats_span:
            data = stats_span.get("data-stats", "")
            try:
                parts = data.strip("[]").split(",")
                maxed = int(parts[0])
                stats_text = f"{maxed}/8"
            except Exception:
                stats_text = stats_span.get_text(strip=True).split("\n")[0]

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

def _crop_item(x: int, y: int) -> Image.Image:
    """Crop item sprite from renders.png."""
    renders = Image.open("./images/renders.png").convert("RGBA")
    left   = x
    top    = y
    right  = left + 40
    bottom = top  + 40
    rw, rh = renders.size
    right  = min(right,  rw)
    bottom = min(bottom, rh)
    return renders.crop((left, top, right, bottom)).resize(
        (ITEM_SIZE, ITEM_SIZE), Image.NEAREST
    )


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
    draw.text((text_x, 32), f"Killed by: {death['killed_by']}", font=font_small, fill=TEXT_SECONDARY)

    # ── Stats + Fame ─────────────────────────────────────────────────────────
    stats_line = f"Stats: {death['stats']}   Base Fame: {death['base_fame']}   Total Fame: {death['total_fame']}"
    draw.text((text_x, 52), stats_line, font=font_small, fill=TEXT_SECONDARY)

    # ── Time ─────────────────────────────────────────────────────────────────
    draw.text((text_x, 70), death["time"], font=font_tiny, fill=TEXT_MUTED)

    # ── Divider ───────────────────────────────────────────────────────────────
    draw.rectangle([(12, 98), (CARD_W - 12, 99)], fill=(50, 50, 65))

    # ── Equipment row ────────────────────────────────────────────────────────
    item_y = 108
    draw.text((12, item_y - 14), "Equipment:", font=font_tiny, fill=TEXT_MUTED)

    for i, item in enumerate(death["equipment"][:5]):
        ix = 12 + i * ITEM_SPACING
        # Dark slot background
        draw.rectangle(
            [(ix, item_y), (ix + ITEM_SIZE, item_y + ITEM_SIZE)],
            fill=(35, 35, 50), outline=(60, 60, 80)
        )
        try:
            item_img = _crop_item(item["x"], item["y"])
            card.paste(item_img, (ix, item_y), item_img)
        except Exception as e:
            print(f"Item crop error for {item['name']}: {e}")

    # ── Save ──────────────────────────────────────────────────────────────────
    os.makedirs("./images", exist_ok=True)
    card.save(out_path)
    return out_path
