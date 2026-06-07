import os
import urllib.request
from PIL import Image, ImageDraw, ImageFont
from typing import Optional

ITEM_CACHE = "./itempics"
REALMSCOPE_ASSET = "https://realmscope.gg/asset/{}.png"

_FONT_REGULAR: Optional[str] = None
_FONT_BOLD:    Optional[str] = None

def _resolve_fonts() -> None:
    global _FONT_REGULAR, _FONT_BOLD
    if _FONT_REGULAR is not None:
        return
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",           # Debian/Pi
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "arial.ttf",                                                   # Windows
    ]:
        try:
            ImageFont.truetype(path, 10)
            _FONT_REGULAR = path
            break
        except Exception:
            pass
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "arialbd.ttf",
    ]:
        try:
            ImageFont.truetype(path, 10)
            _FONT_BOLD = path
            break
        except Exception:
            pass

RARITY_COLORS = {
    "Common":    (180, 180, 180),
    "Uncommon":  (100, 220, 100),
    "Rare":      (80,  140, 255),
    "Legendary": (200, 160, 50),
    "Divine":    (200, 80,  220),
}

def fetch_item_image(item_id: int, item_name: str) -> Optional[Image.Image]:
    """Download item image from realmscope asset CDN."""
    cache_path = os.path.join(ITEM_CACHE, f"{item_id}.png")
    if os.path.exists(cache_path):
        try:
            return Image.open(cache_path).convert("RGBA")
        except Exception:
            pass
    url = REALMSCOPE_ASSET.format(item_id)
    req = urllib.request.Request(url, headers={"User-Agent": "Magic Browser"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
        os.makedirs(ITEM_CACHE, exist_ok=True)
        with open(cache_path, "wb") as f:
            f.write(data)
        return Image.open(cache_path).convert("RGBA")
    except Exception as e:
        print(f"Failed to fetch item {item_id} ({item_name}): {e}")
        return None

def build_tier_image(tier_label: str, items: dict, enchants: dict,
                     dps: float, total_dmg: float,
                     swap_items: dict = None, is_support: bool = False,
                     alt_enchants: dict = None,
                     stats_line: str = None) -> Image.Image:

    SLOT_ORDER  = ["Weapon", "Ability", "Armor", "Ring"]
    SLOT_COLORS = {
        "Weapon":  (100, 160, 255),
        "Ability": (100, 220, 150),
        "Armor":   (220, 160, 80),
        "Ring":    (200, 100, 220),
    }

    ITEM_SIZE    = 48
    ALT_SIZE     = 28
    PAD          = 14
    LABEL_H      = 20
    SLOT_W       = 250
    HEADER_H     = 50
    STATS_H      = 40
    ENC_SECTION  = 100
    ALT_SECTION  = 110
    SLOT_H       = LABEL_H + ITEM_SIZE + 16 + ENC_SECTION + ALT_SECTION
    IMG_W        = PAD + (SLOT_W + PAD) * 4
    IMG_H        = HEADER_H + STATS_H + SLOT_H + PAD * 3

    img  = Image.new("RGBA", (IMG_W, IMG_H), (18, 22, 32, 255))
    draw = ImageDraw.Draw(img)

    _resolve_fonts()
    try:
        font_sm   = ImageFont.truetype(_FONT_REGULAR, 12)
        font_med  = ImageFont.truetype(_FONT_REGULAR, 14)
        font_bold = ImageFont.truetype(_FONT_BOLD,    15)
        font_hdr  = ImageFont.truetype(_FONT_BOLD,    16)
    except Exception:
        font_sm = font_med = font_bold = font_hdr = ImageFont.load_default()

    # Header
    draw.rectangle([0, 0, IMG_W, HEADER_H], fill=(30, 36, 52, 255))
    clean_label = tier_label.replace("★", "*").replace("◈", "~")
    draw.text((PAD, 12), clean_label, fill=(220, 220, 255), font=font_hdr)

    # Stats line — bold red
    if stats_line is not None:
        draw.text((PAD, HEADER_H + 10), stats_line, fill=(220, 60, 60), font=font_bold)
    elif dps or total_dmg:
        stat_label = "HPS" if is_support else "DPS"
        prefix     = "Avg " if "AVERAGE" in tier_label else ""
        stats_text = (f"{prefix}{stat_label}: {dps:,.0f}"
                      f"     {prefix}Total Dmg: {total_dmg:,.0f}")
        draw.text((PAD, HEADER_H + 10), stats_text, fill=(220, 60, 60), font=font_bold)

    # Item slots
    for i, slot in enumerate(SLOT_ORDER):
        x = PAD + i * (SLOT_W + PAD)
        y = HEADER_H + STATS_H + PAD

        item_data = items.get(slot, {})
        item_id   = item_data.get("itemId")
        item_name = item_data.get("itemName", "Unknown")
        rarity    = item_data.get("rarity", "Common")
        color     = SLOT_COLORS[slot]

        # Card background
        draw.rectangle([x, y, x + SLOT_W, y + SLOT_H],
                       fill=(28, 34, 48, 255),
                       outline=(*color, 100), width=1)

        # Slot label
        draw.text((x + PAD, y + 5), slot.upper(),
                  fill=(*color, 200), font=font_sm)

        # Item image
        img_y    = y + LABEL_H + 4
        item_img = fetch_item_image(item_id, item_name) if item_id else None
        if item_img:
            resized = item_img.resize((ITEM_SIZE, ITEM_SIZE), Image.NEAREST)
            img.paste(resized, (x + PAD, img_y), resized)

        # Item name beside image
        name_x = x + PAD + ITEM_SIZE + 8
        name_y = img_y + 4
        words, lines_txt, cur = item_name.split(), [], ""
        for word in words:
            test = (cur + " " + word).strip()
            try:   w = draw.textlength(test, font=font_med)
            except: w = len(test) * 7
            if w < SLOT_W - ITEM_SIZE - PAD * 3:
                cur = test
            else:
                if cur: lines_txt.append(cur)
                cur = word
        if cur: lines_txt.append(cur)

        rarity_color = RARITY_COLORS.get(rarity, (180, 180, 180))
        for li, line in enumerate(lines_txt[:2]):
            draw.text((name_x, name_y + li * 15), line,
                      fill=rarity_color, font=font_med)

        # ── Main enchants ─────────────────────────────────────────────
        enc_y     = img_y + ITEM_SIZE + 10
        main_encs = enchants.get(slot, [])
        if main_encs:
            draw.text((x + PAD, enc_y), "Enchants:",
                      fill=(140, 140, 200), font=font_sm)
            enc_y += 13
            for enc in main_encs[:2]:
                draw.text((x + PAD + 4, enc_y), f"• {enc}",
                          fill=(160, 180, 255), font=font_sm)
                enc_y += 12

        # ── Alt enchants ──────────────────────────────────────────────
        if alt_enchants:
            alt_encs = alt_enchants.get(slot, [])
            if alt_encs:
                enc_y += 5
                draw.text((x + PAD, enc_y), "Alt Enchants:",
                          fill=(120, 120, 160), font=font_sm)
                enc_y += 13
                for enc in alt_encs[:2]:
                    draw.text((x + PAD + 4, enc_y), f"• {enc}",
                              fill=(120, 140, 200), font=font_sm)
                    enc_y += 12

        # ── Alt items with images ─────────────────────────────────────
        if swap_items:
            swaps = swap_items.get(slot, [])
            if swaps:
                alt_start = y + LABEL_H + ITEM_SIZE + 16 + ENC_SECTION
                draw.line(
                    [(x + PAD, alt_start), (x + SLOT_W - PAD, alt_start)],
                    fill=(60, 70, 90), width=1
                )
                alt_y = alt_start + 6
                draw.text((x + PAD, alt_y), "Alt Items:",
                          fill=(160, 160, 160), font=font_sm)
                alt_y += 14

                for sw in swaps[:2]:
                    sw_id   = sw.get("itemId")
                    sw_name = sw.get("itemName", "Unknown")
                    sw_img  = fetch_item_image(sw_id, sw_name) if sw_id else None
                    if sw_img:
                        sw_r = sw_img.resize((ALT_SIZE, ALT_SIZE), Image.NEAREST)
                        img.paste(sw_r, (x + PAD, alt_y), sw_r)
                    disp = sw_name if len(sw_name) <= 24 else sw_name[:22] + "…"
                    draw.text(
                        (x + PAD + ALT_SIZE + 6, alt_y + 8),
                        disp, fill=(120, 160, 120), font=font_sm
                    )
                    alt_y += ALT_SIZE + 4

    return img