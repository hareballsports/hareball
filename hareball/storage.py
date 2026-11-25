"""Read and write the data files kept in the repository (data/<sport>/...).

These CSV files are the master copy of the data. The Google Sheet is a mirror
for viewing, plus a few tabs you edit by hand (Settings, Overrides, Posting).
"""

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = ROOT / "data"
RUN_DIR = ROOT / "run"  # scratch area for one run; never saved to the repository

GAME_FIELDS = [
    "season", "game_id", "date_local", "time_local", "status", "completed", "on_schedule",
    "season_type", "neutral_site", "conference_game", "periods",
    "home_id", "home_team", "home_conf_id", "home_d1", "home_score",
    "away_id", "away_team", "away_conf_id", "away_d1", "away_score",
    "venue", "note",
]

BOX_FIELDS = [
    "season", "game_id", "date_local", "team_id", "team", "opp_id", "opp",
    "site", "conference_game", "periods", "pts", "opp_pts",
    "fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "orb", "drb", "trb",
    "ast", "stl", "blk", "tov", "pf",
]

TEAM_FIELDS = [
    "team_id", "team", "full_name", "abbreviation", "conf_id", "conference",
    "color", "alt_color",
]

BOOL_FIELDS = {"completed", "on_schedule", "neutral_site", "conference_game", "home_d1", "away_d1", "unresolved"}


def sport_dir(sport_key):
    return DATA_ROOT / sport_key


def _read_csv(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        for key in BOOL_FIELDS & row.keys():
            row[key] = row[key] in ("True", "TRUE", "true", "1")
    return rows


def _write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})


# --- games: kept as {game_id: row}
def load_games(sport_key, season):
    rows = _read_csv(sport_dir(sport_key) / str(season) / "games.csv")
    for r in rows:
        r.setdefault("on_schedule", True)  # files saved before this column existed
    return {r["game_id"]: r for r in rows}


def save_games(sport_key, season, games):
    rows = sorted(games.values(), key=lambda r: (r["date_local"], r["time_local"], r["game_id"]))
    _write_csv(sport_dir(sport_key) / str(season) / "games.csv", GAME_FIELDS, rows)


# --- box scores: one row per team per game
def load_box(sport_key, season):
    return _read_csv(sport_dir(sport_key) / str(season) / "team_box.csv")


def save_box(sport_key, season, rows):
    rows = sorted(rows, key=lambda r: (r["date_local"], r["game_id"], r["site"]))
    _write_csv(sport_dir(sport_key) / str(season) / "team_box.csv", BOX_FIELDS, rows)


# --- teams (latest list)
def load_teams(sport_key):
    return {r["team_id"]: r for r in _read_csv(sport_dir(sport_key) / "teams.csv")}


def save_teams(sport_key, teams):
    rows = sorted(teams.values(), key=lambda r: r["team"])
    _write_csv(sport_dir(sport_key) / "teams.csv", TEAM_FIELDS, rows)


# --- bookkeeping: box score attempts that failed
def load_state(sport_key):
    path = sport_dir(sport_key) / "state.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"box_failures": {}}


def save_state(sport_key, state):
    path = sport_dir(sport_key) / "state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")


# --- run summary, passed from the data step to the Sheet step (not saved to the repo)
def save_run_summary(summary):
    RUN_DIR.mkdir(exist_ok=True)
    (RUN_DIR / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")


def load_run_summary():
    path = RUN_DIR / "summary.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# --- standings files (rebuilt from games each run)
STANDINGS_FIELDS = [
    "position", "seed_note", "team_id", "team", "conf_w", "conf_l", "conf_pct", "games_back",
    "overall", "vs_d1", "tiebreaker", "unresolved",
]
HISTORY_FIELDS = ["date", "position", "team_id", "team", "conf_w", "conf_l"]
BRACKET_FIELDS = ["game", "round", "top_seed", "top_team", "bottom_seed", "bottom_team"]


def standings_path(sport_key, season, conf_id, kind):
    """kind: 'standings', 'standings_history' or 'bracket'."""
    return sport_dir(sport_key) / str(season) / f"{kind}_conf{conf_id}.csv"


def write_rows(path, fields, rows):
    _write_csv(path, fields, rows)


def read_rows(path):
    return _read_csv(path)


# --- inputs typed into the Google Sheet, copied into the repository each run
INPUTS_DIR = DATA_ROOT / "inputs"


def load_json_run(name):
    """Read a file another step of this run left in run/ (or None)."""
    path = RUN_DIR / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
