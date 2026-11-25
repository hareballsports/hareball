"""Download and tidy data from ESPN's public (unofficial) data feeds.

ESPN does not document these feeds, so every field is read defensively:
if something is missing we leave a blank instead of crashing.
"""

import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from . import config

SITE_BASE = "https://site.api.espn.com/apis/site/v2/sports/"
STANDINGS_BASE = "https://site.api.espn.com/apis/v2/sports/"

_session = requests.Session()
_session.headers["User-Agent"] = "Mozilla/5.0 (Hareball data updater)"

LOCAL_TZ = ZoneInfo(config.TIMEZONE)


def get_json(url, params=None, tries=4):
    """Fetch a URL and return its JSON. Retries a few times; returns None on 404."""
    for attempt in range(tries):
        try:
            resp = _session.get(url, params=params, timeout=30)
            if resp.status_code == 200:
                time.sleep(config.REQUEST_DELAY)
                return resp.json()
            if resp.status_code == 404:
                return None
        except (requests.RequestException, ValueError):
            pass
        time.sleep(2 ** attempt)
    raise RuntimeError(f"ESPN request kept failing: {url} {params}")


# ---------------------------------------------------------------- teams

def fetch_teams(sport):
    """Return {team_id: info} for every team ESPN lists in the sport's group (Division I)."""
    url = SITE_BASE + sport["espn_path"] + "/teams"
    data = get_json(url, {"limit": 1000, "groups": sport["espn_groups"]}) or {}
    teams = {}
    for league in _first(data.get("sports"), {}).get("leagues", []):
        for entry in league.get("teams", []):
            t = entry.get("team", {})
            tid = str(t.get("id", ""))
            if not tid:
                continue
            teams[tid] = {
                "team_id": tid,
                "team": t.get("location") or t.get("displayName", ""),
                "full_name": t.get("displayName", ""),
                "abbreviation": t.get("abbreviation", ""),
                "color": t.get("color", ""),
                "alt_color": t.get("alternateColor", ""),
            }
    return teams


def fetch_conference_names(sport):
    """Return {conference_id: name}. Empty if ESPN doesn't answer."""
    url = STANDINGS_BASE + sport["espn_path"] + "/standings"
    try:
        data = get_json(url) or {}
    except RuntimeError:
        return {}
    names = {}
    for child in data.get("children", []):
        cid = str(child.get("id", ""))
        if cid:
            names[cid] = child.get("abbreviation") or child.get("name", "")
    return names


# ---------------------------------------------------------------- scoreboard

def fetch_day(sport, day):
    """Return the list of raw ESPN events for one date (a datetime.date)."""
    url = SITE_BASE + sport["espn_path"] + "/scoreboard"
    params = {"dates": day.strftime("%Y%m%d"), "groups": sport["espn_groups"], "limit": 1000}
    return (get_json(url, params) or {}).get("events", [])


def parse_event(ev, season, d1_ids):
    """Turn one ESPN event into a flat row for the Games table."""
    comp = _first(ev.get("competitions"), {})
    status = comp.get("status") or ev.get("status") or {}
    stype = status.get("type", {})

    home, away = {}, {}
    for c in comp.get("competitors", []):
        if c.get("homeAway") == "home":
            home = c
        else:
            away = c

    start = _parse_time(ev.get("date") or comp.get("date"))
    completed = bool(stype.get("completed"))
    notes = comp.get("notes") or []

    row = {
        "season": season,
        "game_id": str(ev.get("id", "")),
        "date_local": start.strftime("%Y-%m-%d") if start else "",
        "time_local": start.strftime("%I:%M %p").lstrip("0") if start else "",
        "status": stype.get("description") or stype.get("name", ""),
        "completed": completed,
        "on_schedule": True,
        "season_type": {1: "Preseason", 2: "Regular", 3: "Postseason"}.get(
            (ev.get("season") or {}).get("type"), ""),
        "neutral_site": bool(comp.get("neutralSite")),
        "conference_game": bool(comp.get("conferenceCompetition")),
        "periods": status.get("period", "") if completed else "",
        "venue": (comp.get("venue") or {}).get("fullName", ""),
        "note": _first(notes, {}).get("headline", ""),
    }
    for prefix, c in (("home", home), ("away", away)):
        t = c.get("team", {})
        tid = str(t.get("id", ""))
        row[f"{prefix}_id"] = tid
        row[f"{prefix}_team"] = t.get("location") or t.get("shortDisplayName") or t.get("displayName", "")
        row[f"{prefix}_conf_id"] = str(t.get("conferenceId", "") or "")
        row[f"{prefix}_d1"] = tid in d1_ids
        row[f"{prefix}_score"] = _score(c.get("score")) if completed else ""
    return row


# ---------------------------------------------------------------- box scores (basketball)

# ESPN stat name -> our column name(s). "Made-Attempted" stats split into two columns.
STAT_COLUMNS = {
    "fieldGoalsMade-fieldGoalsAttempted": ("fgm", "fga"),
    "threePointFieldGoalsMade-threePointFieldGoalsAttempted": ("fg3m", "fg3a"),
    "freeThrowsMade-freeThrowsAttempted": ("ftm", "fta"),
    "offensiveRebounds": ("orb",),
    "defensiveRebounds": ("drb",),
    "totalRebounds": ("trb",),
    "assists": ("ast",),
    "steals": ("stl",),
    "blocks": ("blk",),
    "turnovers": ("tov",),
    "totalTurnovers": ("tov_total",),
    "fouls": ("pf",),
}
BOX_STATS = ["fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "orb", "drb", "trb",
             "ast", "stl", "blk", "tov", "pf"]


def fetch_box(sport, game_id):
    """Return {team_id: {stat: value}} for one game, or None if ESPN has no box score."""
    url = SITE_BASE + sport["espn_path"] + "/summary"
    data = get_json(url, {"event": game_id})
    if not data:
        return None
    out = {}
    for team_block in (data.get("boxscore") or {}).get("teams", []):
        tid = str((team_block.get("team") or {}).get("id", ""))
        stats = {}
        for s in team_block.get("statistics", []):
            cols = STAT_COLUMNS.get(s.get("name", ""))
            if not cols:
                continue
            parts = str(s.get("displayValue", "")).split("-")
            if len(parts) == len(cols):
                for col, val in zip(cols, parts):
                    stats[col] = _int(val)
        # Prefer total team turnovers when ESPN gives both
        if stats.get("tov_total") not in (None, ""):
            stats["tov"] = stats["tov_total"]
        stats.pop("tov_total", None)
        if tid and stats.get("fga") not in (None, ""):
            out[tid] = stats
    return out if len(out) == 2 else None


# ---------------------------------------------------------------- helpers

def _first(seq, default):
    return seq[0] if seq else default


def _parse_time(text):
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(LOCAL_TZ)
    except ValueError:
        return None


def _score(value):
    if isinstance(value, dict):
        value = value.get("value", value.get("displayValue"))
    return _int(value)


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return ""
