import urllib.request
from bs4 import BeautifulSoup
from typing import Optional

try:
    from curl_cffi import requests as _cffi_req
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False

REALMSCOPE_BASE = "https://realmscope.gg"

def get_player_characters(player_name: str) -> Optional[list]:
    """
    Scrapes character data from realmscope.gg/player/{player_name}
    Returns a list of character dicts, or None if the page couldn't be fetched.
    """
    url = f"{REALMSCOPE_BASE}/player/{player_name}"
    try:
        if _HAS_CURL_CFFI:
            resp = _cffi_req.get(url, impersonate="chrome120", timeout=15)
            resp.raise_for_status()
            html = resp.text
        else:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Connection": "keep-alive",
            })
            html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8")
    except Exception as e:
        print(f"Error fetching realmscope page for {player_name}: {e}")
        return None

    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("tbody tr")

    characters = []
    for row in rows:
        tds = row.find_all("td")
        if len(tds) < 8:
            continue
        
        row_style = row.get("style", "")
        is_seasonal = "#2d4a3e" in row_style
        # Skin and pet asset IDs from the img src
        pet_img = tds[0].find("img")
        skin_img = tds[1].find("img")
        pet_id = _extract_asset_id(pet_img)
        skin_id = _extract_asset_id(skin_img)

        # Class name
        class_name = tds[2].get_text(strip=True)

        # Level and fame
        level = tds[3].get_text(strip=True)
        fame = tds[4].get_text(strip=True)

        # Stats (e.g. "6/8")
        stats_span = tds[7].select_one("div.stats-popup-wrapper > span")
        stats_text = stats_span.get_text(strip=True) if stats_span else "?"

        # Last seen and server
        last_seen = tds[8].get_text(strip=True) if len(tds) > 8 else ""
        server = tds[9].get_text(strip=True) if len(tds) > 9 else ""

        # Equipment — only real item wrappers, skip placeholders
        equipment = []
        wrappers = tds[6].select("div.character-equipment-item-wrapper")
        for wrapper in wrappers:
            item_id = wrapper.get("data-item-id")
            item_name = wrapper.get("data-item-name")
            if item_id and item_name:
                equipment.append({
                    "id": int(item_id),
                    "name": item_name
                })

        characters.append({
            "seasonal": is_seasonal,
            "class": class_name,
            "level": level,
            "fame": fame,
            "stats": stats_text,
            "last_seen": last_seen,
            "server": server,
            "skin_id": skin_id,
            "pet_id": pet_id,
            "equipment": equipment
        })

    return characters


def _extract_asset_id(img_tag) -> Optional[int]:
    """Pulls the numeric ID from an /asset/{id}.png src."""
    if not img_tag:
        return None
    src = img_tag.get("src", "")
    try:
        return int(src.strip("/").split("/")[-1].replace(".png", ""))
    except ValueError:
        return None