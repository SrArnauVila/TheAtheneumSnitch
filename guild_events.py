import json
import os
from datetime import datetime, timezone
from typing import Optional
import guild_stats as gs

EVENTS_PATH    = "./guild_events.json"
VALID_STATS = {
    "fame":          "Total Character Fame",
    "active_fame":   "Active Fame (last 14 days)",
    "seasonal_fame": "Seasonal Fame",
    "stars":         "Star Count",
    "shinies":       "Total Shinies",
}

def load_events() -> dict:
    if not os.path.exists(EVENTS_PATH):
        return {"events": [], "next_id": 1}
    try:
        with open(EVENTS_PATH, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"events": [], "next_id": 1}

def save_events(data: dict) -> None:
    with open(EVENTS_PATH, "w") as f:
        json.dump(data, f, indent=2)

def add_event(name: str, description: str, end_date: str,
              prize: str, stat: str) -> Optional[dict]:
    """
    Creates a new auto-tracked event.
    stat must be one of VALID_STATS keys.
    Snapshots the current values as the baseline.
    """
    if stat not in VALID_STATS:
        return None

    # Take a baseline from the latest snapshot
    baseline = {}
    snap = gs.get_latest_snapshot()
    if snap:
        for key, member in snap["members"].items():
            baseline[key] = member.get(stat, 0)

    data = load_events()
    event = {
        "id":           data["next_id"],
        "name":         name,
        "description":  description,
        "end_date":     end_date,
        "prize":        prize,
        "stat":         stat,
        "stat_label":   VALID_STATS[stat],
        "created":      datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "active":       True,
        "baseline":     baseline,
        "winner":       None,
    }
    data["events"].append(event)
    data["next_id"] += 1
    save_events(data)
    return event

def get_active_events() -> list:
    return [e for e in load_events()["events"] if e["active"]]

def get_all_events() -> list:
    return load_events()["events"]

def get_event_by_id(event_id: int) -> Optional[dict]:
    for e in load_events()["events"]:
        if e["id"] == event_id:
            return e
    return None

def get_event_leaderboard(event: dict) -> list:
    """
    Computes current standings by diffing latest snapshot against baseline.
    Returns sorted list of (name, baseline_val, current_val, delta).
    """
    snap = gs.get_latest_snapshot()
    if not snap:
        return []

    stat     = event["stat"]
    baseline = event.get("baseline", {})
    results  = []

    for key, member in snap["members"].items():
        current_val  = member.get(stat, 0)
        baseline_val = baseline.get(key, current_val)
        delta        = current_val - baseline_val
        if delta >= 0:
            results.append((member["name"], baseline_val, current_val, delta))

    results.sort(key=lambda x: x[3], reverse=True)
    return results

def auto_determine_winner(event: dict) -> Optional[str]:
    """Returns the name of the current leader."""
    board = get_event_leaderboard(event)
    if board:
        return board[0][0]
    return None

def end_event(event_id: int, winner: Optional[str] = None) -> bool:
    """
    Ends an event. If winner is None, auto-determines from leaderboard.
    """
    data = load_events()
    for event in data["events"]:
        if event["id"] == event_id:
            event["active"] = False
            event["winner"] = winner or auto_determine_winner(event)
            save_events(data)
            return True
    return False