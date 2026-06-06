import json
import os
import time
from datetime import datetime, timezone
from typing import Optional

SNAPSHOTS_PATH = "./guild_snapshots.json"

def load_snapshots() -> dict:
    if not os.path.exists(SNAPSHOTS_PATH):
        return {"snapshots": [], "season_start": None}
    try:
        with open(SNAPSHOTS_PATH, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"snapshots": [], "season_start": None}

def save_snapshots(data: dict) -> None:
    with open(SNAPSHOTS_PATH, "w") as f:
        json.dump(data, f, indent=2)

def take_snapshot(members: list, fetch_shinies: bool = False) -> dict:
    """
    Takes a snapshot of current guild state.
    fetch_shinies: if True, fetches each player's shiny count individually (slow).
    """
    import realmscope_scraper as rs

    snapshot = {
        "timestamp": int(time.time()),
        "date":      datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "members":   {}
    }

    for m in members:
        shinies = 0
        if fetch_shinies:
            try:
                shinies = rs.get_player_shiny_count(m["name"])
            except Exception:
                pass

        snapshot["members"][m["name"].lower()] = {
            "name":          m["name"],
            "rank":          m["rank"],
            "fame":          m.get("fame", 0),
            "active_fame":   m.get("active_fame", 0),
            "seasonal_fame": m.get("seasonal_fame", 0),
            "stars":         m.get("stars", 0),
            "shinies":       shinies,
        }

    return snapshot

def store_snapshot(snapshot: dict) -> None:
    data = load_snapshots()
    data["snapshots"].append(snapshot)
    # Keep last 90 days of snapshots (one per day = 90 entries max)
    data["snapshots"] = data["snapshots"][-90:]
    save_snapshots(data)

def get_latest_snapshot() -> Optional[dict]:
    data = load_snapshots()
    if not data["snapshots"]:
        return None
    return data["snapshots"][-1]

def get_snapshot_before(hours_ago: int) -> Optional[dict]:
    """Returns the snapshot closest to N hours ago."""
    data = load_snapshots()
    if not data["snapshots"]:
        return None
    target = int(time.time()) - (hours_ago * 3600)
    best = None
    best_diff = float("inf")
    for snap in data["snapshots"]:
        diff = abs(snap["timestamp"] - target)
        if diff < best_diff:
            best_diff = diff
            best = snap
    return best

def delta_leaderboard(snap_old: dict, snap_new: dict, stat: str, top_n: int = 10) -> list:
    """
    Computes the delta of a stat between two snapshots.
    Returns sorted list of (name, old_val, new_val, delta).
    """
    results = []
    for key, new_data in snap_new["members"].items():
        old_data = snap_old["members"].get(key, {})
        new_val = new_data.get(stat, 0)
        old_val = old_data.get(stat, 0)
        delta = new_val - old_val
        if delta > 0:
            results.append((new_data["name"], old_val, new_val, delta))
    results.sort(key=lambda x: x[3], reverse=True)
    return results[:top_n]

def current_leaderboard(snap: dict, stat: str, top_n: int = 10) -> list:
    """Returns sorted leaderboard of current values for a stat."""
    results = []
    for key, data in snap["members"].items():
        val = data.get(stat, 0)
        if val > 0:
            results.append((data["name"], val))
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_n]

def set_season_start() -> None:
    """Marks the current snapshot as the start of a new season."""
    data = load_snapshots()
    data["season_start"] = int(time.time())
    save_snapshots(data)

def get_season_start_snapshot() -> Optional[dict]:
    """Returns the snapshot closest to when the season started."""
    data = load_snapshots()
    if not data.get("season_start"):
        return None
    return get_snapshot_before_timestamp(data["season_start"])

def get_snapshot_before_timestamp(ts: int) -> Optional[dict]:
    data = load_snapshots()
    if not data["snapshots"]:
        return None
    best = None
    best_diff = float("inf")
    for snap in data["snapshots"]:
        diff = abs(snap["timestamp"] - ts)
        if diff < best_diff:
            best_diff = diff
            best = snap
    return best