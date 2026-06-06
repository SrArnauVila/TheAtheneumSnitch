import urllib.request
import urllib.parse
import io
import os
from typing import Optional
from PIL import Image, ImageDraw, ImageFont
from bs4 import BeautifulSoup


def fetch_sprite(obj_id: int, size: int = 44) -> Optional[Image.Image]:
    """Fetch event monster sprite from realm.wiki by object ID."""
    url = f"https://realm.wiki/Sprite/ByObjectId?id={obj_id}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Magic Browser"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read()
        sprite = Image.open(io.BytesIO(data)).convert("RGBA")
        sprite = sprite.resize((size, size), Image.NEAREST)
        return sprite
    except Exception:
        return None

def score_color(score: int) -> tuple:
    if score >= 90: return (80, 220, 100)
    if score >= 70: return (220, 200, 80)
    if score >= 50: return (220, 140, 60)
    return (200, 80, 80)

def server_short(server: str) -> str:
    return (server
        .replace("USEast2",    "USE2")
        .replace("USEast",     "USE")
        .replace("USWest4",    "USW4")
        .replace("USWest3",    "USW3")
        .replace("USWest",     "USW")
        .replace("USMidWest2", "USMW2")
        .replace("USMidWest",  "USMW")
        .replace("USNorthWest","USNW")
        .replace("USSouth3",   "USS3")
        .replace("USSouth",    "USS")
        .replace("USSouthWest","USSW")
        .replace("EUEast",     "EUE")
        .replace("EUWest2",    "EUW2")
        .replace("EUSouthWest","EUSW")
        .replace("EUNorth",    "EUN")
        .replace("EUWest",     "EUW")
        .replace("Australia",  "AUS")
        .replace("Asia",       "ASIA")
    )

REALMEYE_IMG_BASE = "https://www.realmeye.com/s/a/img/wiki/i/"

import urllib.request
import urllib.parse
import io
import re

REALMEYE_BASE  = "https://www.realmeye.com"
REALMEYE_WIKI  = "https://www.realmeye.com/wiki/"

# In-memory caches so we don't re-fetch on every !find call
_item_sprite_cache:   dict = {}
_portal_sprite_cache: dict = {}


def _name_to_slug(name: str) -> str:
    """Convert an item/dungeon name to a RealmEye wiki slug."""
    slug = name.lower()
    slug = slug.replace("'", "-")
    slug = slug.replace(" ", "-")
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def _fetch_realmeye_page(slug: str) -> Optional[str]:
    """Fetch a RealmEye wiki page HTML. Uses undetected_chromedriver if needed."""
    url = REALMEYE_WIKI + slug
    # Try plain urllib first — RealmEye wiki pages are mostly server-rendered
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html",
                "Referer": "https://www.realmeye.com/",
            }
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            if len(html) > 5000:  # real page, not a redirect/error
                return html
    except Exception:
        pass
    return None


REALMEYE_BASE = "https://www.realmeye.com"
_sprite_cache: dict = {}

def _fetch_realmeye_cdn(src: str, size: int) -> Optional[Image.Image]:
    """
    Fetch an image directly from RealmEye's static CDN.
    These are plain image files — not blocked, no browser needed.
    src is like: /s/a/img/wiki/i/WzJqBbb.png
    """
    cache_key = f"{src}_{size}"
    if cache_key in _sprite_cache:
        return _sprite_cache[cache_key]

    url = REALMEYE_BASE + src if src.startswith("/") else src
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Magic Browser",
                "Referer": REALMEYE_BASE,
            }
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = resp.read()
        if len(data) < 50:
            _sprite_cache[cache_key] = None
            return None
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        img = img.resize((size, size), Image.NEAREST)
        _sprite_cache[cache_key] = img
        return img
    except Exception:
        _sprite_cache[cache_key] = None
        return None


def fetch_item_sprite_by_name(item_name: str, drops_data: dict, size: int = 32) -> Optional[Image.Image]:
    """Fetch item sprite using the src URL saved in event_drops.json."""
    # drops_data is the full drops dict for the event e.g.
    # {"whites": [{"name": "...", "src": "..."}], "dungeon": [...]}
    for item in drops_data.get("whites", []):
        if item.get("name") == item_name:
            src = item.get("src", "")
            if src:
                return _fetch_realmeye_cdn(src, size)
    return None


def fetch_portal_sprite(dungeon_name: str, drops_data: dict, size: int = 32) -> Optional[Image.Image]:
    """Fetch portal sprite using the src URL saved in event_drops.json."""
    for dung in drops_data.get("dungeon", []):
        if dung.get("name") == dungeon_name:
            src = dung.get("src", "")
            if src:
                return _fetch_realmeye_cdn(src, size)
    return None

_O3_BANNER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images", "o3.png")

def build_event_image(results: list[dict], title: str,
                      is_o3: bool = False,
                      drops: Optional[dict] = None,
                      search_mode: str = "event",
                      possible_events: Optional[list] = None) -> Image.Image:
    PAD      = 16
    ROW_H    = 64
    SPRITE   = 30

    whites  = drops.get("whites",  []) if drops else []
    dungeon = drops.get("dungeon", []) if drops else []
    has_drops = not is_o3 and (whites or dungeon)

    LEFT_W  = 520
    DROPS_W = 200 if has_drops else 0
    IMG_W   = LEFT_W + DROPS_W

    display = results[:3] if not is_o3 else results[:7]

    # ── O3 banner — ~2 row heights tall, aspect ratio preserved, centered ───────
    o3_banner: Optional[Image.Image] = None
    BANNER_H  = 0
    _banner_x = 0
    if is_o3:
        try:
            raw = Image.open(_O3_BANNER_PATH).convert("RGBA")
            bw, bh   = raw.size
            target_h = 2 * (ROW_H + 8)           # height of two list rows
            target_w = int(bw * target_h / bh)   # proportional width
            if target_w > IMG_W:                  # too wide — scale to fit width
                target_w = IMG_W
                target_h = int(bh * IMG_W / bw)
            BANNER_H  = target_h
            _banner_x = (IMG_W - target_w) // 2  # center horizontally
            o3_banner = raw.resize((target_w, target_h), Image.LANCZOS)
        except Exception:
            o3_banner = None
            BANNER_H  = 0

    # Calculate height — drops panel may need more space than event rows
    rows_h  = PAD + len(display) * (ROW_H + 8) + PAD
    drops_h = 0
    if has_drops:
        drops_h = PAD + 20  # header
        if whites:
            drops_h += 14 + len(whites) * (SPRITE + 6) + 8
        if dungeon:
            drops_h += 14 + len(dungeon) * (SPRITE + 6)
        drops_h += PAD

    # Also add space for "no active events" message
    no_active = len(display) == 0 and possible_events
    if no_active:
        rows_h = PAD + 60 + PAD  # just enough for the message

    IMG_H = BANNER_H + max(rows_h, drops_h)

    img  = Image.new("RGBA", (IMG_W, IMG_H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)

    if o3_banner:
        img.paste(o3_banner, (_banner_x, 0), o3_banner)

    try:
        font_name  = ImageFont.truetype("arialbd.ttf", 15)
        font_med   = ImageFont.truetype("arial.ttf",   13)
        font_sm    = ImageFont.truetype("arial.ttf",   11)
        font_score = ImageFont.truetype("arialbd.ttf", 16)
        font_tiny  = ImageFont.truetype("arial.ttf",   10)
    except Exception:
        font_name = font_med = font_sm = font_score = font_tiny = ImageFont.load_default()

    # Pre-fetch event sprites
    sprites = {}
    if not is_o3:
        for ev in display:
            oid = ev["obj_id"]
            if oid not in sprites:
                sprites[oid] = fetch_sprite(oid, size=44)

    whites  = drops.get("whites",  []) if drops else []
    dungeon = drops.get("dungeon", []) if drops else []
    # Extract just names for display
    white_names  = [w["name"] if isinstance(w, dict) else w for w in whites]
    dungeon_names = [d["name"] if isinstance(d, dict) else d for d in dungeon]

    item_sprites   = {}
    portal_sprites = {}
    if has_drops:
        for item in white_names:
            item_sprites[item] = fetch_item_sprite_by_name(item, drops, size=SPRITE)
        for dung in dungeon_names:
            portal_sprites[dung] = fetch_portal_sprite(dung, drops, size=SPRITE)

    # ── Event rows ────────────────────────────────────────────────────────────
    BASE_Y = BANNER_H  # all content drawn below the banner
    if no_active:
        draw.text((PAD, BASE_Y + PAD), "No active events dropping this right now.",
                  fill=(200, 160, 100), font=font_med)
        draw.text((PAD, BASE_Y + PAD + 20), "Events that can drop it:",
                  fill=(140, 160, 180), font=font_sm)
        for j, ev_name in enumerate(possible_events[:5]):
            draw.text((PAD + 8, BASE_Y + PAD + 36 + j * 13), f"• {ev_name}",
                      fill=(180, 180, 200), font=font_tiny)
    else:
        for i, ev in enumerate(display):
            row_y    = BASE_Y + PAD + i * (ROW_H + 8)
            card_col = (14, 14, 14) if i % 2 == 0 else (20, 20, 20)
            draw.rounded_rectangle([0, row_y, LEFT_W - 4, row_y + ROW_H],
                                   radius=6, fill=card_col)

            sc      = ev["score"]
            sc_col  = score_color(sc) if sc >= 0 else (120, 120, 120)
            pop     = ev["population"]

            if not is_o3:
                sprite   = sprites.get(ev["obj_id"])
                sprite_x = PAD
                sprite_y = row_y + (ROW_H - 44) // 2
                if sprite:
                    img.paste(sprite, (sprite_x, sprite_y), sprite)
                else:
                    draw.rectangle([sprite_x, sprite_y, sprite_x+44, sprite_y+44],
                                   fill=(30, 30, 30))

                text_x = sprite_x + 44 + 12
                name   = ev["name"]
                if len(name) > 26: name = name[:24] + "…"
                draw.text((text_x, row_y + 10), name, fill=(230, 230, 255), font=font_name)
                draw.text((text_x, row_y + 32),
                          f"{server_short(ev['server'])}  {ev['realm']}",
                          fill=(120, 160, 120), font=font_sm)

                score_x = LEFT_W - 85
                draw.text((score_x, row_y + 10),
                          f"{sc}%" if sc >= 0 else "?%", fill=sc_col, font=font_score)
                pop_col = (100, 220, 100) if pop < 50 else (220, 200, 80) if pop < 70 else (200, 100, 100)
                draw.text((score_x, row_y + 34),
                          f"{min(pop, 85)}/85", fill=pop_col, font=font_sm)
            else:
                # O3 row: rank | server | realm | score | population
                rank_label = f"#{i+1}"
                mid_y      = row_y + ROW_H // 2 - 8
                pop_col    = (100, 220, 100) if pop < 50 else (220, 200, 80) if pop < 70 else (200, 100, 100)
                sc_col2    = score_color(sc) if sc >= 0 else (120, 120, 120)
                draw.text((PAD,       mid_y), rank_label,                   fill=(160, 160, 160), font=font_sm)
                draw.text((PAD + 36,  mid_y), server_short(ev["server"]),   fill=(160, 200, 255), font=font_med)
                draw.text((PAD + 160, mid_y), ev["realm"],                  fill=(200, 200, 200), font=font_med)
                draw.text((PAD + 300, mid_y), f"{sc}%" if sc >= 0 else "?%", fill=sc_col2,        font=font_score)
                draw.text((PAD + 390, mid_y), f"{min(pop, 85)}/85",         fill=pop_col,          font=font_med)

    # ── Drops panel ───────────────────────────────────────────────────────────
    if has_drops:
        DX = LEFT_W + 8
        DY = BASE_Y + PAD

        draw.line([(LEFT_W + 4, BASE_Y + PAD), (LEFT_W + 4, IMG_H - PAD)],
                  fill=(35, 35, 35), width=1)

        # Header label depends on search mode
        if search_mode == "dungeon":
            header = "Drops Portal"
        elif search_mode == "item":
            header = "Drops Item"
        else:
            header = "Notable Drops"
        draw.text((DX, DY), header, fill=(180, 180, 230), font=font_name)
        DY += 22

        if whites:
            draw.text((DX, DY), "WHITES / UTs", fill=(200, 180, 80), font=font_tiny)
            DY += 14
            for item in whites:
                name = item["name"] if isinstance(item, dict) else item
                sp   = item_sprites.get(name)
                if sp:
                    img.paste(sp, (DX, DY), sp)
                    tx = DX + SPRITE + 5
                else:
                    draw.ellipse([DX + 2, DY + 10, DX + 12, DY + 20], fill=(80, 80, 80))
                    tx = DX + 18
                label = name if len(name) <= 20 else name[:18] + "…"
                draw.text((tx, DY + (SPRITE - 10) // 2),
                        label, fill=(230, 230, 200), font=font_tiny)
                DY += SPRITE + 6

        if dungeon:
            DY += 4
            draw.text((DX, DY), "DUNGEON PORTAL", fill=(120, 180, 230), font=font_tiny)
            DY += 14
            for dung in dungeon:
                name = dung["name"] if isinstance(dung, dict) else dung
                sp   = portal_sprites.get(name)
                if sp:
                    img.paste(sp, (DX, DY), sp)
                    tx = DX + SPRITE + 5
                else:
                    draw.ellipse([DX + 2, DY + 10, DX + 12, DY + 20], fill=(60, 80, 140))
                    tx = DX + 18
                label = name if len(name) <= 20 else name[:18] + "…"
                draw.text((tx, DY + (SPRITE - 10) // 2),
                        label, fill=(160, 200, 230), font=font_tiny)
                DY += SPRITE + 6

    return img

def debug_sprite_fetch(item_name="Corruption Tether", dungeon_name="The Shatters"):
    print(f"\n--- Testing item sprite: {item_name} ---")
    slug = _name_to_slug(item_name)
    print(f"Slug: {slug}")
    html = _fetch_realmeye_page(slug)
    if html:
        print(f"Got HTML: {len(html)} chars")
        soup = BeautifulSoup(html, "html.parser")
        wp = soup.find("div", class_="wiki-page")
        print(f"wiki-page div found: {wp is not None}")
        if wp:
            t = wp.find("table")
            print(f"First table found: {t is not None}")
            if t:
                td = t.find("td", attrs={"width": "50"})
                print(f"td[width=50] found: {td is not None}")
                if td:
                    img = td.find("img")
                    print(f"img found: {img}")
    else:
        print("HTML fetch FAILED — likely blocked by RealmEye")

    print(f"\n--- Testing portal sprite: {dungeon_name} ---")
    slug2 = _name_to_slug(dungeon_name)
    print(f"Slug: {slug2}")
    html2 = _fetch_realmeye_page(slug2)
    if html2:
        print(f"Got HTML: {len(html2)} chars")
        soup2 = BeautifulSoup(html2, "html.parser")
        wp2 = soup2.find("div", class_="wiki-page")
        print(f"wiki-page div found: {wp2 is not None}")
        if wp2:
            for tbl in wp2.find_all("table", class_="table-striped"):
                td = tbl.find("td", attrs={"align": "center"})
                if td:
                    img = td.find("img", title=lambda t: t and "Portal" in t)
                    if img:
                        print(f"Portal img found: {img.get('src')}")
                        break
    else:
        print("HTML fetch FAILED — likely blocked by RealmEye")

if __name__ == "__main__":
    debug_sprite_fetch()