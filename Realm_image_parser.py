from PIL import Image
import urllib.request
import os
import shutil

REALMSCOPE_ASSET_BASE = "https://realmscope.gg/asset/"

def _download_asset(asset_id: int, dest_path: str) -> bool:
    """Downloads a single asset PNG from realmscope by ID. Returns True on success."""
    url = f"{REALMSCOPE_ASSET_BASE}{asset_id}.png"
    req = urllib.request.Request(url, headers={'User-Agent': 'Magic Browser'})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            with open(dest_path, 'wb') as f:
                f.write(response.read())
        return True
    except Exception as e:
        print(f"Failed to download asset {asset_id}: {e}")
        return False

def item_image_parser(item_id: int, item_name: str):
    """Downloads item image from realmscope by asset ID."""
    os.makedirs("./itempics", exist_ok=True)
    # Sanitize name for use as filename
    safe_name = item_name.replace("/", "_").replace("\\", "_")
    dest = f"./itempics/{safe_name}.png"
    _download_asset(item_id, dest)

def skin_image_parser(skin_id: int, label: str):
    """Downloads skin image from realmscope by asset ID."""
    os.makedirs("./skinpics", exist_ok=True)
    dest = f"./skinpics/{label}.png"
    _download_asset(skin_id, dest)

def death_image_combiner(death_dict: dict):
    template = Image.open("./images/image-template.png")
    skin = Image.open(f"./skinpics/{death_dict['player-name']}.png")
    combined = Image.new('RGBA', (template.width, template.height), (0, 0, 0, 0))
    combined.paste(template, (0, 0), template)
    for i, item in enumerate(death_dict['equipment']):
        item_path = f"./itempics/{item['name']}.png"
        if os.path.exists(item_path):
            item_img = Image.open(item_path).convert("RGBA").resize((40, 40))
            combined.paste(item_img, (60 + (45 * i), 12), item_img)
    combined.paste(skin, (6, 7), skin)

def character_image_combiner(character_dict: dict, index: int):
    template = Image.open("./images/image-template.png")
    skin = Image.open(f"./skinpics/{character_dict['class']}_{index}.png")
    combined = Image.new('RGBA', (template.width, template.height), (0, 0, 0, 0))
    combined.paste(template, (0, 0), template)
    for i, item in enumerate(character_dict['equipment']):
        safe_name = item['name'].replace("/", "_").replace("\\", "_")
        item_path = f"./itempics/{safe_name}.png"
        if os.path.exists(item_path):
            item_img = Image.open(item_path).convert("RGBA").resize((40, 40))
            combined.paste(item_img, (60 + (45 * i), 12), item_img)
    combined.paste(skin, (6, 7), skin)
    combined.save("./images/alive_output.png")

def skin_image_parser_legacy(x: int, y: int, player_name: str):
    """Legacy sprite-crop version for guild_graveyard (realmeye-based deaths)."""
    im = Image.open("./images/sheets.png")
    left = x
    top = y - 250
    right = x + 50
    bottom = y - 200
    im1 = im.crop((left, top, right, bottom))
    os.makedirs("./skinpics", exist_ok=True)
    im1.save(f"./skinpics/{player_name}.png")

def item_image_parser_legacy(x: int, y: int, item_name: str):
    """Legacy sprite-crop version for guild_graveyard (realmeye-based deaths)."""
    im = Image.open("./images/renders.png")
    left = x
    top = y
    right = x + 40
    bottom = y + 40
    im1 = im.crop((left, top, right, bottom))
    os.makedirs("./itempics", exist_ok=True)
    im1.save(f"./itempics/{item_name}.png")

def delete_all_files_in_folder(folder_path):
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            print(f'Failed to delete {file_path}. Reason: {e}')