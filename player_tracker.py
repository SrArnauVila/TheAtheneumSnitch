import urllib.request
from bs4 import BeautifulSoup
import json
import os
from typing import Optional
import time as time_module
TRACKED_PLAYERS_PATH = "./tracked_players.json"

def get_online_status(player_name: str) -> Optional[str]:
    url = f"https://realmscope.gg/player/{player_name}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Magic Browser'})
    try:
        page = urllib.request.urlopen(req, timeout=10)
        html = page.read().decode("utf-8")
    except Exception as e:
        print(f"Error fetching status for {player_name}: {e}")
        return None

    soup = BeautifulSoup(html, "html.parser")

    # Check realmscope status indicator
    status_container = soup.find("div", class_="status-container")
    if not status_container:
        return None

    realmscope_online = bool(status_container.find("div", class_="status-online"))

    # Cross-reference with last seen timestamp
    # Only trust "Online" if last seen was within the last 30 minutes
    if realmscope_online:
        stats_list = soup.find("ul", id="player-stats-list")
        if stats_list:
            try:
                last_seen_ts = int(stats_list.get("data-lastseen", 0))
                seconds_ago  = int(time_module.time()) - last_seen_ts
                if seconds_ago > 1800:  # 30 minutes
                    return "Offline"
            except (ValueError, TypeError):
                pass
        return "Online"

    return "Offline"

def load_tracked_players() -> dict:
    if not os.path.exists(TRACKED_PLAYERS_PATH):
        return {}
    try:
        with open(TRACKED_PLAYERS_PATH, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_tracked_players(data: dict) -> None:
    with open(TRACKED_PLAYERS_PATH, "w") as f:
        json.dump(data, f, indent=2)


def add_player(player_name: str) -> bool:
    """Returns False if already tracked, True if newly added."""
    data = load_tracked_players()
    if player_name.lower() in data:
        return False
    status = get_online_status(player_name)
    data[player_name.lower()] = {
        "display_name": player_name,
        "status": status
    }
    save_tracked_players(data)
    return True


def remove_player(player_name: str) -> bool:
    """Returns False if not found, True if removed."""
    data = load_tracked_players()
    if player_name.lower() not in data:
        return False
    del data[player_name.lower()]
    save_tracked_players(data)
    return True