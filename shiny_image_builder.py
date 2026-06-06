import urllib.request
import os
from PIL import Image

REALMSCOPE_BASE = "https://realmscope.gg"
ITEM_SIZE = 48
PADDING = 6
ITEMS_PER_ROW = 8
BG_COLOR = (30, 30, 40, 255)

def _download_asset(asset_id: int, dest: str) -> bool:
    url = f"{REALMSCOPE_BASE}/asset/{asset_id}.png"
    req = urllib.request.Request(url, headers={'User-Agent': 'Magic Browser'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            with open(dest, 'wb') as f:
                f.write(r.read())
        return True
    except Exception as e:
        print(f"Failed to download shiny asset {asset_id}: {e}")
        return False



def build_shiny_image(seasons: list, player_name: str, output_path: str = "./images/shinies_output.png") -> bool:
    os.makedirs("./shiny_cache", exist_ok=True)

    # Collect all obtained items, deduplicated by asset_id
    seen_ids = set()
    all_items = []
    for season in seasons:
        for item in season["items"]:
            if item["asset_id"] and item["asset_id"] not in seen_ids:
                seen_ids.add(item["asset_id"])
                all_items.append(item)

    if not all_items:
        return False

    # Download and load images
    loaded = []
    for item in all_items:
        cache_path = f"./shiny_cache/{item['asset_id']}.png"
        if not os.path.exists(cache_path):
            _download_asset(item["asset_id"], cache_path)
        if os.path.exists(cache_path):
            try:
                img = Image.open(cache_path).convert("RGBA").resize((ITEM_SIZE, ITEM_SIZE))
                loaded.append(img)
            except Exception:
                pass

    if not loaded:
        return False

    cols = min(len(loaded), ITEMS_PER_ROW)
    rows = (len(loaded) + cols - 1) // cols
    width  = cols * (ITEM_SIZE + PADDING) + PADDING
    height = rows * (ITEM_SIZE + PADDING) + PADDING

    canvas = Image.new("RGBA", (width, height), BG_COLOR)

    for i, img in enumerate(loaded):
        row = i // cols
        col = i % cols
        x = PADDING + col * (ITEM_SIZE + PADDING)
        y = PADDING + row * (ITEM_SIZE + PADDING)
        canvas.paste(img, (x, y), img)

    canvas.save(output_path)
    return True