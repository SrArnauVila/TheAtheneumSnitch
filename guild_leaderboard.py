"""
guild_leaderboard.py — Seasonal fame and shiny leaderboard system
for The Atheneum Discord bot.

Data sources:
  - Seasonal fame:  realmscope_scraper.get_guild_seasonal_fame()
  - Shiny data:     realmscope_scraper.get_shiny_data()
  - Guild members:  realmscope_scraper.get_guild_roster()

Snapshot file: guild_fame_snapshots.json
  {
    "YYYY-MM-DD": {
      "playername": {
        "seasonal_fame": int,
        "seasonal_shinies": int,
        "shinies": { "item name": "YYYY-MM-DD", ... }
      }
    }
  }
"""

import json
import os
import asyncio
import datetime
import pytz
from typing import Optional

SNAPSHOT_FILE  = "guild_fame_snapshots.json"
PST            = pytz.timezone("America/New_York")  # Eastern — "PST New York" = ET


# ── Snapshot helpers ───────────────────────────────────────────────────────────

def load_snapshots() -> dict:
    if not os.path.exists(SNAPSHOT_FILE):
        return {}
    try:
        with open(SNAPSHOT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_snapshots(data: dict):
    with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def today_str() -> str:
    return datetime.datetime.now(PST).strftime("%Y-%m-%d")


def days_ago_str(n: int) -> str:
    dt = datetime.datetime.now(PST) - datetime.timedelta(days=n)
    return dt.strftime("%Y-%m-%d")


def save_daily_snapshot(members_data: list):
    """
    Save today's snapshot.
    members_data: list of dicts with keys:
      name, seasonal_fame, seasonal_shinies, shiny_items (dict name->date)
    """
    snapshots = load_snapshots()
    today     = today_str()
    entry     = {}
    for m in members_data:
        name = m["name"].lower()
        entry[name] = {
            "seasonal_fame":    m.get("seasonal_fame", 0),
            "seasonal_shinies": m.get("seasonal_shinies", 0),
            "shinies":          m.get("shiny_items", {}),
        }
    snapshots[today] = entry

    # Keep only last 30 days to prevent the file growing forever
    cutoff = (datetime.datetime.now(PST) - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
    snapshots = {k: v for k, v in snapshots.items() if k >= cutoff}

    save_snapshots(snapshots)


def get_snapshot_for_date(date_str: str) -> dict:
    snapshots = load_snapshots()
    return snapshots.get(date_str, {})


def get_fame_gains(members_data: list, since_date: str) -> list:
    """
    Compare current fame against snapshot from since_date.
    Returns list of {name, current, previous, gained} sorted by gained desc.
    """
    snapshot = get_snapshot_for_date(since_date)
    results  = []
    for m in members_data:
        name    = m["name"].lower()
        current = m.get("seasonal_fame", 0) or m.get("current_total", 0)
        prev    = snapshot.get(name, {}).get("seasonal_fame", 0)
        gained  = max(0, current - prev)
        results.append({
            "name":    m["name"],
            "current": current,
            "previous": prev,
            "gained":  gained,
        })
    results.sort(key=lambda x: x["gained"], reverse=True)
    return results


def get_new_shinies_since(current_members: list, since_date: str) -> list:
    """
    Find shinies obtained since since_date.
    Returns list of {name, item, obtained_date} sorted by obtained_date.
    """
    snapshot   = get_snapshot_for_date(since_date)
    new_shinies = []
    for m in current_members:
        name         = m["name"].lower()
        current_shiny = m.get("shiny_items", {})
        old_shiny    = snapshot.get(name, {}).get("shinies", {})
        for item, date in current_shiny.items():
            if item not in old_shiny:
                new_shinies.append({
                    "name":  m["name"],
                    "item":  item,
                    "date":  date or since_date,
                })
    new_shinies.sort(key=lambda x: x["date"])
    return new_shinies


# ── Data fetching ─────────────────────────────────────────────────────────────

async def fetch_guild_leaderboard_data(guild_name: str, guild_members: set) -> list:
    """
    Fetch seasonal fame + shiny data for all guild members concurrently.
    Returns list of member dicts ready for leaderboard use.
    """
    import realmscope_scraper as rs
    import concurrent.futures

    loop    = asyncio.get_event_loop()
    members = list(guild_members)

    # Fetch seasonal fame history for all members
    fame_data = await loop.run_in_executor(
        None, rs.get_guild_seasonal_fame, members
    )
    fame_by_name = {d["name"].lower(): d for d in fame_data}

    # Fetch shiny data concurrently with a thread pool
    def fetch_shiny(name):
        try:
            return name, rs.get_shiny_data(name)
        except Exception:
            return name, None

    shiny_results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(fetch_shiny, m): m for m in members}
        for fut in concurrent.futures.as_completed(futures):
            name, data = fut.result()
            shiny_results[name.lower()] = data

    # Merge into unified member list
    result = []
    for name in members:
        key        = name.lower()
        fame       = fame_by_name.get(key, {})
        shiny      = shiny_results.get(key)

        # Extract flat shiny item dict {item_name: obtained_date}
        shiny_items = {}
        seasonal_shinies = 0
        if shiny:
            for season in shiny.get("seasons", []):
                is_current = "current" in season.get("season", "").lower() or \
                             str(datetime.datetime.now(PST).year) in season.get("season", "")
                for item in season.get("items", []):
                    item_name = item.get("name", "")
                    item_date = item.get("obtained_date", "")
                    shiny_items[item_name] = item_date
                    if is_current:
                        seasonal_shinies += 1
            # Prefer the rank page's seasonal count if available
            try:
                ss = int(shiny.get("season_rank", "0").replace(",", "").split()[0])
                if ss > 0:
                    seasonal_shinies = ss
            except Exception:
                pass

        result.append({
            "name":             name,
            "seasonal_fame":    fame.get("current_total", 0),
            "daily_fame":       fame.get("daily", 0),
            "weekly_fame":      fame.get("weekly", 0),
            "seasonal_shinies": seasonal_shinies,
            "shiny_items":      shiny_items,
            "failed":           fame.get("failed", False),
        })

    return result


# ── Leaderboard builders ──────────────────────────────────────────────────────

def build_seasonal_leaderboard(members: list) -> list:
    """Sort by seasonal fame descending."""
    return sorted(
        [m for m in members if not m.get("failed")],
        key=lambda x: x["seasonal_fame"],
        reverse=True
    )


def build_daily_gainers(members: list, since_date: str) -> list:
    """Fame gained since since_date, sorted by gains."""
    return get_fame_gains(members, since_date)


def build_weekly_gainers(members: list) -> list:
    """Use realmscope's 7-day figure directly."""
    return sorted(
        [m for m in members if not m.get("failed")],
        key=lambda x: x["weekly_fame"],
        reverse=True
    )


def build_shiny_leaderboard(members: list) -> list:
    """Sort by seasonal shiny count descending."""
    return sorted(
        [m for m in members if not m.get("failed")],
        key=lambda x: x["seasonal_shinies"],
        reverse=True
    )


def build_specific_shiny_leaderboard(members: list, item_query: str) -> list:
    """
    Find all members who have a specific shiny item (partial name match).
    Returns list of {name, item, date} sorted by date ascending (earliest first).
    """
    q       = item_query.lower()
    matches = []
    for m in members:
        for item_name, date in m.get("shiny_items", {}).items():
            if q in item_name.lower():
                matches.append({
                    "name": m["name"],
                    "item": item_name,
                    "date": date or "Unknown",
                })
                break  # Only one match per player per query
    matches.sort(key=lambda x: x["date"])
    return matches


# ── PIL image generators ──────────────────────────────────────────────────────

from PIL import Image, ImageDraw, ImageFont
from typing import Optional as Opt

def _fonts():
    try:
        return {
            "hdr":   ImageFont.truetype("arialbd.ttf", 18),
            "bold":  ImageFont.truetype("arialbd.ttf", 14),
            "med":   ImageFont.truetype("arial.ttf",   13),
            "sm":    ImageFont.truetype("arial.ttf",   11),
            "tiny":  ImageFont.truetype("arial.ttf",   10),
        }
    except Exception:
        f = ImageFont.load_default()
        return {k: f for k in ("hdr", "bold", "med", "sm", "tiny")}


def _medal(rank: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")


def _fmt(n: int) -> str:
    return f"{n:,}"


def build_fame_leaderboard_image(
    rows:       list,
    title:      str,
    value_key:  str  = "seasonal_fame",
    value_label: str = "Seasonal Fame",
    subtitle:   str  = "",
    top_n:      int  = 15,
) -> Image.Image:
    """
    Generic ranked leaderboard image.
    rows: list of dicts, each needs "name" and value_key.
    """
    PAD     = 14
    ROW_H   = 38
    HDR_H   = 56
    IMG_W   = 480
    display = rows[:top_n]
    IMG_H   = HDR_H + PAD + len(display) * (ROW_H + 4) + PAD

    img  = Image.new("RGBA", (IMG_W, IMG_H), (8, 10, 18, 255))
    draw = ImageDraw.Draw(img)
    f    = _fonts()

    # Header
    draw.rectangle([0, 0, IMG_W, HDR_H], fill=(20, 24, 40, 255))
    draw.text((PAD, 10), title,    fill=(220, 220, 255), font=f["hdr"])
    if subtitle:
        draw.text((PAD, 32), subtitle, fill=(120, 140, 180), font=f["sm"])

    y = HDR_H + PAD
    for i, row in enumerate(display):
        rank     = i + 1
        name     = row.get("name", "?")
        value    = row.get(value_key, 0)
        row_y    = y + i * (ROW_H + 4)
        card_col = (16, 20, 34, 255) if i % 2 == 0 else (20, 26, 42, 255)

        draw.rounded_rectangle([0, row_y, IMG_W, row_y + ROW_H],
                               radius=5, fill=card_col)

        # Rank accent bar
        accent = (
            (255, 215, 0)  if rank == 1 else
            (192, 192, 192) if rank == 2 else
            (205, 127, 50)  if rank == 3 else
            (60, 80, 120)
        )
        draw.rectangle([0, row_y, 3, row_y + ROW_H], fill=(*accent, 255))

        # Rank number
        rank_txt = str(rank)
        draw.text((PAD + 4, row_y + 10), rank_txt,
                  fill=accent, font=f["bold"])

        # Name
        draw.text((PAD + 30, row_y + 10), name,
                  fill=(220, 220, 255), font=f["bold"])

        # Value right-aligned
        val_txt = _fmt(value)
        bbox    = draw.textbbox((0, 0), val_txt, font=f["bold"])
        val_w   = bbox[2] - bbox[0]
        draw.text((IMG_W - PAD - val_w, row_y + 10), val_txt,
                  fill=(100, 220, 140), font=f["bold"])

    return img


def build_gains_leaderboard_image(
    rows:    list,
    title:   str,
    subtitle: str = "",
    top_n:   int  = 15,
) -> Image.Image:
    """
    Leaderboard showing fame gained over a period.
    rows: list of {name, current, gained}
    """
    PAD     = 14
    ROW_H   = 38
    HDR_H   = 56
    IMG_W   = 520
    display = [r for r in rows if r.get("gained", 0) > 0][:top_n]

    if not display:
        display = rows[:1]  # at least show something

    IMG_H = HDR_H + PAD + len(display) * (ROW_H + 4) + PAD

    img  = Image.new("RGBA", (IMG_W, IMG_H), (8, 10, 18, 255))
    draw = ImageDraw.Draw(img)
    f    = _fonts()

    draw.rectangle([0, 0, IMG_W, HDR_H], fill=(20, 24, 40, 255))
    draw.text((PAD, 10), title,    fill=(220, 220, 255), font=f["hdr"])
    if subtitle:
        draw.text((PAD, 32), subtitle, fill=(120, 140, 180), font=f["sm"])

    y = HDR_H + PAD
    for i, row in enumerate(display):
        rank     = i + 1
        name     = row.get("name", "?")
        gained   = row.get("gained", 0)
        current  = row.get("current", 0)
        row_y    = y + i * (ROW_H + 4)
        card_col = (16, 20, 34, 255) if i % 2 == 0 else (20, 26, 42, 255)

        draw.rounded_rectangle([0, row_y, IMG_W, row_y + ROW_H],
                               radius=5, fill=card_col)

        accent = (
            (255, 215, 0)   if rank == 1 else
            (192, 192, 192) if rank == 2 else
            (205, 127, 50)  if rank == 3 else
            (60, 80, 120)
        )
        draw.rectangle([0, row_y, 3, row_y + ROW_H], fill=(*accent, 255))

        draw.text((PAD + 4,  row_y + 10), str(rank),   fill=accent,          font=f["bold"])
        draw.text((PAD + 30, row_y + 10), name,         fill=(220, 220, 255), font=f["bold"])

        # Gained (big, green) + total (small, grey)
        gain_txt  = f"+{_fmt(gained)}"
        total_txt = f"({_fmt(current)} total)"

        bbox    = draw.textbbox((0, 0), gain_txt, font=f["bold"])
        gain_w  = bbox[2] - bbox[0]
        draw.text((IMG_W - PAD - gain_w - 100, row_y + 10),
                  gain_txt,  fill=(100, 220, 100), font=f["bold"])
        draw.text((IMG_W - PAD - 95, row_y + 12),
                  total_txt, fill=(100, 120, 160), font=f["tiny"])

    return img


def build_shiny_leaderboard_image(
    rows:    list,
    title:   str,
    subtitle: str = "",
    top_n:   int  = 15,
) -> Image.Image:
    """
    rows: list of {name, seasonal_shinies} or {name, item, date} for specific item.
    Auto-detects format.
    """
    specific = "item" in (rows[0] if rows else {})
    PAD      = 14
    ROW_H    = 38
    HDR_H    = 56
    IMG_W    = 500
    display  = rows[:top_n]
    IMG_H    = HDR_H + PAD + len(display) * (ROW_H + 4) + PAD

    img  = Image.new("RGBA", (IMG_W, IMG_H), (8, 10, 18, 255))
    draw = ImageDraw.Draw(img)
    f    = _fonts()

    draw.rectangle([0, 0, IMG_W, HDR_H], fill=(20, 24, 40, 255))
    draw.text((PAD, 10), title,    fill=(220, 220, 255), font=f["hdr"])
    if subtitle:
        draw.text((PAD, 32), subtitle, fill=(120, 140, 180), font=f["sm"])

    y = HDR_H + PAD
    for i, row in enumerate(display):
        rank     = i + 1
        name     = row.get("name", "?")
        row_y    = y + i * (ROW_H + 4)
        card_col = (16, 20, 34, 255) if i % 2 == 0 else (20, 26, 42, 255)

        draw.rounded_rectangle([0, row_y, IMG_W, row_y + ROW_H],
                               radius=5, fill=card_col)

        accent = (
            (255, 215, 0)   if rank == 1 else
            (192, 192, 192) if rank == 2 else
            (205, 127, 50)  if rank == 3 else
            (80, 60, 120)
        )
        draw.rectangle([0, row_y, 3, row_y + ROW_H], fill=(*accent, 255))
        draw.text((PAD + 4,  row_y + 10), str(rank), fill=accent,          font=f["bold"])
        draw.text((PAD + 30, row_y + 10), name,       fill=(220, 220, 255), font=f["bold"])

        if specific:
            item = row.get("item", "?")
            date = row.get("date", "?")
            if len(item) > 24: item = item[:22] + "…"
            draw.text((PAD + 160, row_y + 10), item, fill=(180, 160, 220), font=f["med"])
            draw.text((PAD + 160, row_y + 24), date, fill=(100, 120, 160), font=f["tiny"])
        else:
            count     = row.get("seasonal_shinies", 0)
            count_txt = f"✦ {count}"
            bbox  = draw.textbbox((0, 0), count_txt, font=f["bold"])
            cw    = bbox[2] - bbox[0]
            draw.text((IMG_W - PAD - cw, row_y + 10),
                      count_txt, fill=(200, 160, 255), font=f["bold"])

    return img


def build_new_shinies_image(new_shinies: list, title: str) -> Image.Image:
    """Image showing newly obtained shinies since last snapshot."""
    PAD    = 14
    ROW_H  = 34
    HDR_H  = 50
    IMG_W  = 460

    display = new_shinies[:20]
    IMG_H   = HDR_H + PAD + max(len(display), 1) * (ROW_H + 4) + PAD

    img  = Image.new("RGBA", (IMG_W, IMG_H), (8, 10, 18, 255))
    draw = ImageDraw.Draw(img)
    f    = _fonts()

    draw.rectangle([0, 0, IMG_W, HDR_H], fill=(20, 24, 40, 255))
    draw.text((PAD, 14), title, fill=(220, 220, 255), font=f["hdr"])

    if not display:
        draw.text((PAD, HDR_H + PAD + 8), "No new shinies today.",
                  fill=(120, 140, 180), font=f["med"])
        return img

    y = HDR_H + PAD
    for i, entry in enumerate(display):
        row_y    = y + i * (ROW_H + 4)
        card_col = (16, 20, 34, 255) if i % 2 == 0 else (20, 26, 42, 255)
        draw.rounded_rectangle([0, row_y, IMG_W, row_y + ROW_H],
                               radius=5, fill=card_col)
        draw.rectangle([0, row_y, 3, row_y + ROW_H], fill=(200, 160, 255, 255))

        name = entry.get("name", "?")
        item = entry.get("item", "?")
        date = entry.get("date", "")
        if len(item) > 28: item = item[:26] + "…"

        draw.text((PAD + 6,  row_y + 8),  name, fill=(220, 220, 255), font=f["bold"])
        draw.text((PAD + 130, row_y + 8),  item, fill=(200, 160, 255), font=f["med"])
        if date:
            draw.text((IMG_W - PAD - 70, row_y + 10), date,
                      fill=(100, 120, 160), font=f["tiny"])

    return img