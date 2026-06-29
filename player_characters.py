from bs4 import BeautifulSoup
from typing import Optional
from realmscope_scraper import fetch_page

REALMSCOPE_BASE = "https://realmscope.gg"

def get_player_characters(player_name: str) -> Optional[list]:
    """
    Scrapes character data from realmscope.gg/player/{player_name}
    Returns a list of character dicts, or None if the page couldn't be fetched.
    """
    url = f"{REALMSCOPE_BASE}/player/{player_name}"
    soup = fetch_page(url)
    if not soup:
        return None

    rows = soup.select("tbody tr")

    characters = []
    for row in rows:
        tds = row.find_all("td")
        if len(tds) < 8:
            continue

        row_style = row.get("style", "")
        is_seasonal = "#2d4a3e" in row_style
        pet_img = tds[0].find("img")
        skin_img = tds[1].find("img")
        pet_id = _extract_asset_id(pet_img)
        skin_id = _extract_asset_id(skin_img)

        class_name = tds[2].get_text(strip=True)
        level = tds[3].get_text(strip=True)
        fame = tds[4].get_text(strip=True)

        stats_span = tds[7].select_one("div.stats-popup-wrapper > span")
        stats_text = stats_span.get_text(strip=True) if stats_span else "?"

        last_seen = tds[8].get_text(strip=True) if len(tds) > 8 else ""
        server = tds[9].get_text(strip=True) if len(tds) > 9 else ""

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
