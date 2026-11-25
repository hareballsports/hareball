"""Step 2 of each run: rebuild conference standings from the game files.

For each kept season and the focus conference (the Big Ten), this writes:
  data/<sport>/<season>/standings_conf<id>.csv          standings today (or final), with tiebreakers
  data/<sport>/<season>/standings_history_conf<id>.csv  the standings as of every day of the season
  data/<sport>/<season>/bracket_conf<id>.csv            the tournament bracket if the season ended today

Standings come straight from game results, so they're rebuilt from scratch each run.
That way a corrected score or a late game is always reflected everywhere, including the history.
It also checks seasons with known official seeds and reports any mismatch.
"""

import csv
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hareball import config, formats, seasons, storage  # noqa: E402
from hareball.standings import ConferenceStandings  # noqa: E402


def load_net_ranks(sport_key, season):
    """NET ranks typed into the Sheet: {team_id: rank} for this season."""
    path = storage.INPUTS_DIR / f"{sport_key}_net_ranks.csv"
    if not path.exists():
        return {}
    ranks = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                if str(row.get("season", "")).strip() in (str(season), seasons_label_cache.get(season, "")):
                    ranks[row["team_id"].strip()] = int(float(row["net_rank"]))
            except (KeyError, ValueError, TypeError):
                continue
    return ranks


seasons_label_cache = {}


def build_bracket(fmt, seeds):
    """Bracket rows for the format, filled with today's seeds."""
    rows = []
    for gid, rnd, top, bottom in fmt["games"]:
        row = {"game": gid, "round": fmt["round_names"][rnd]}
        for name, slot in (("top", top), ("bottom", bottom)):
            if slot[0] == "seed":
                n = slot[1]
                row[f"{name}_seed"] = n
                row[f"{name}_team"] = seeds[n - 1] if n <= len(seeds) else ""
            else:
                row[f"{name}_seed"] = ""
                row[f"{name}_team"] = f"Winner of {slot[1]}"
        rows.append(row)
    return rows


def main():
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    today = now.date()
    checks = {}

    for key, sport in config.SPORTS.items():
        if not sport.get("enabled") or not sport.get("focus_conference_id"):
            continue
        conf = sport["focus_conference_id"]
        teams = storage.load_teams(key)
        names = {tid: t["team"] for tid, t in teams.items()}

        for season in seasons.kept_seasons(sport, today):
            seasons_label_cache[season] = seasons.label(sport, season)
            # Only games involving a conference member matter here (much faster)
            games = [g for g in storage.load_games(key, season).values()
                     if conf in (g["home_conf_id"], g["away_conf_id"])]
            if not games:
                continue
            start, end = seasons.window(sport, season)
            last_day = min(today, end)
            net = load_net_ranks(key, season)
            fmt = formats.tournament_format(key, conf, season)
            opts = formats.tiebreak_options(key, conf)

            # ---- standings now (or final)
            st = ConferenceStandings(games, conf, names=names, net_ranks=net, conf_name=sport["focus_conference_name"], **opts)
            rows = st.table()
            for r in rows:
                r["seed_note"] = formats.seed_note(fmt, r["position"]) if fmt else ""
            storage.write_rows(storage.standings_path(key, season, conf, "standings"),
                               storage.STANDINGS_FIELDS, rows)
            for w in sorted(set(st.warnings))[:5]:
                print("WARNING:", w)

            # ---- data check: every team should end with the full number of conference games
            expected_games = formats.CONFERENCE_GAMES_PER_TEAM.get(key, {}).get(conf)
            season_over = today > end

            # ---- bracket if the season ended today
            if fmt:
                seeds = [r["team"] for r in rows]
                storage.write_rows(storage.standings_path(key, season, conf, "bracket"),
                                   storage.BRACKET_FIELDS, build_bracket(fmt, seeds))

            # ---- standings as of every day, from the first conference game on
            conf_dates = sorted({g["date_local"] for g in games
                                 if g["completed"] and g["home_conf_id"] == conf and g["away_conf_id"] == conf
                                 and g.get("season_type") == "Regular"})
            history = []
            if conf_dates:
                d = date.fromisoformat(conf_dates[0])
                while d <= last_day:
                    ds = d.isoformat()
                    day = ConferenceStandings(games, conf, names=names, through_date=ds, net_ranks=net,
                                             conf_name=sport["focus_conference_name"], **opts)
                    for pos, t in enumerate(day.order(), start=1):
                        history.append({"date": ds, "position": pos, "team_id": t, "team": day.name(t),
                                        "conf_w": day.wins[t], "conf_l": day.losses[t]})
                    d += timedelta(days=1)
            storage.write_rows(storage.standings_path(key, season, conf, "standings_history"),
                               storage.HISTORY_FIELDS, history)

            # ---- compare with official seeds when we know them
            official = formats.OFFICIAL_SEEDS.get(key, {}).get(conf, {}).get(season)
            label = seasons.label(sport, season)
            if official:
                check_rows, matches = [], 0
                for i, expected in enumerate(official):
                    got = rows[i]["team"] if i < len(rows) else ""
                    ok = got.lower() == expected.lower()
                    matches += ok
                    check_rows.append([i + 1, expected, got, "✓" if ok else "✗ MISMATCH",
                                       f"{rows[i]['conf_w']}-{rows[i]['conf_l']}" if i < len(rows) else "",
                                       rows[i]["tiebreaker"] if i < len(rows) else ""])
                checks[f"{key}|{conf}|{season}"] = {
                    "sport": key, "label": label, "matches": matches, "total": len(official), "rows": check_rows,
                }
                print(f"[{sport['label']}] {label} official seed check: {matches}/{len(official)} match")

            short = [r["team"] for r in rows if expected_games and season_over
                     and r["conf_w"] + r["conf_l"] != expected_games]
            if short:
                print(f"[{sport['label']}] WARNING {label}: teams without {expected_games} conference games: {', '.join(short)}")
            unresolved = [r["team"] for r in rows if r["unresolved"]]
            if unresolved:
                print(f"[{sport['label']}] {label}: ties needing NET rankings: {', '.join(unresolved)}")
            print(f"[{sport['label']}] {label}: standings built ({len(rows)} teams, {len(history)} history rows)")

    storage.RUN_DIR.mkdir(exist_ok=True)
    (storage.RUN_DIR / "standings_checks.json").write_text(json.dumps(checks, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
