"""Step 1 of each run: download new ESPN data into the repository's data/ folder.

When it runs (the workflow starts it every hour; this script decides what to do):
  - In season, hourly: download yesterday's and today's games (fast).
  - In season, 5 AM daily: re-download the whole current-season schedule and team list,
    to catch postponements, new tournament games and time changes.
  - Offseason: does nothing except one full check on Monday at 5 AM (new schedules appear
    over the summer and fall), plus a small "heartbeat" so GitHub keeps the job switched on.
  - Manual run: an hourly-style check in season, a full check in the offseason.
    Tick "full refresh" to re-download everything for every kept season.

Seasons are worked out from the date, so a new season starts on its own.
"""

import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hareball import config, espn, seasons, storage  # noqa: E402


def same_row(a, b, fields):
    if a is None or b is None:
        return False
    return all(str(a.get(k, "")) == str(b.get(k, "")) for k in fields)


def write_output(**values):
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            for k, v in values.items():
                f.write(f"{k}={v}\n")


def heartbeat(today):
    """Touch data/heartbeat.txt every few weeks so the repository never looks inactive."""
    path = storage.DATA_ROOT / "heartbeat.txt"
    try:
        last = date.fromisoformat(path.read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        last = None
    if last is None or (today - last).days >= config.HEARTBEAT_DAYS:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{today.isoformat()} last heartbeat (keeps GitHub's schedule switched on)\n",
                        encoding="utf-8")


def update_sport(key, sport, *, full, schedule_refresh, today_espn, today_local):
    """Download what's needed for one sport. Returns (changed, report_rows)."""
    report = []
    state = storage.load_state(key)
    failures = state.setdefault("box_failures", {})
    if full:
        failures.clear()  # a full refresh retries every missing box score

    # ---- team list (refreshed with the full schedule)
    teams = storage.load_teams(key)
    old_teams = {k: dict(v) for k, v in teams.items()}
    conf_names = {}
    if full or schedule_refresh or not teams:
        fresh = espn.fetch_teams(sport)
        print(f"[{sport['label']}] ESPN lists {len(fresh)} teams")
        if len(fresh) >= 0.9 * len(teams) and fresh:
            for tid, t in fresh.items():
                t["conf_id"] = teams.get(tid, {}).get("conf_id", "")
                t["conference"] = teams.get(tid, {}).get("conference", "")
            teams = fresh
        else:
            print(f"[{sport['label']}] WARNING: team list looks wrong; keeping the saved one")
        conf_names = espn.fetch_conference_names(sport)
    d1_ids = set(teams)

    kept = seasons.kept_seasons(sport, today_local)
    current = kept[0]
    box_budget = config.BOX_SCORES_PER_RUN
    changed = False
    all_games = {}

    for season in kept:  # current season first
        start, end = seasons.window(sport, season)
        name = seasons.label(sport, season)
        games = storage.load_games(key, season)
        before = {gid: dict(g) for gid, g in games.items()}

        whole_season = not games or full or (season == current and schedule_refresh)
        if whole_season:
            days = list(seasons.all_days(start, end))
        elif season == current:
            days = [d for d in (today_espn - timedelta(days=1), today_espn) if start <= d <= end]
        else:
            days = []

        fetched_ok, seen = set(), set()
        for d in days:
            try:
                events = espn.fetch_day(sport, d)
            except RuntimeError as err:
                print(f"[{sport['label']}] WARNING: skipped {d}: {err}")
                continue
            fetched_ok.add(d)
            for ev in events:
                row = espn.parse_event(ev, season, d1_ids)
                if row["game_id"]:
                    games[row["game_id"]] = row
                    seen.add(row["game_id"])

        # A scheduled game that vanished from ESPN's full schedule was cancelled or merged:
        # keep the row but mark it so future simulations ignore it.
        if whole_season:
            for gid, g in games.items():
                if gid in seen or g["completed"] or not g.get("date_local"):
                    continue
                d = date.fromisoformat(g["date_local"])
                if d in fetched_ok and d + timedelta(days=1) in fetched_ok and g.get("on_schedule", True):
                    g["on_schedule"] = False
                    g["status"] = "Removed from ESPN schedule"

        new_finals = [gid for gid, g in games.items()
                      if g["completed"] and not (before.get(gid) or {}).get("completed")]
        games_changed = len(games) != len(before) or any(
            not same_row(before.get(gid), g, storage.GAME_FIELDS) for gid, g in games.items())
        if games_changed:
            storage.save_games(key, season, games)

        # ---- box scores for finished Division I vs Division I games
        added = removed = 0
        need = []
        box_report = []
        if sport.get("box_scores"):
            box_rows = storage.load_box(key, season)
            by_game = {}
            for r in box_rows:
                by_game.setdefault(r["game_id"], []).append(r)
            # If ESPN corrected a final score after we saved the box score, download it again
            for gid, rows in list(by_game.items()):
                g = games.get(gid)
                if not g:
                    continue
                for r in rows:
                    expected = g["home_score"] if r["team_id"] == g["home_id"] else g["away_score"]
                    if str(r["pts"]) != str(expected):
                        del by_game[gid]
                        removed += 1
                        break
            box_rows = [r for rows in by_game.values() for r in rows]

            need = [g for g in games.values()
                    if g["completed"] and g["home_d1"] and g["away_d1"]
                    and g["game_id"] not in by_game
                    and failures.get(g["game_id"], 0) < config.MAX_BOX_ATTEMPTS]
            need.sort(key=lambda g: g["date_local"], reverse=True)
            batch = need[:max(box_budget, 0)]
            box_budget -= len(batch)
            for g in batch:
                gid = g["game_id"]
                try:
                    box = espn.fetch_box(sport, gid)
                except RuntimeError:
                    box = None
                if not box or g["home_id"] not in box or g["away_id"] not in box:
                    failures[gid] = failures.get(gid, 0) + 1
                    continue
                for side, opp in (("home", "away"), ("away", "home")):
                    tid = g[f"{side}_id"]
                    row = {
                        "season": season, "game_id": gid, "date_local": g["date_local"],
                        "team_id": tid, "team": g[f"{side}_team"],
                        "opp_id": g[f"{opp}_id"], "opp": g[f"{opp}_team"],
                        "site": "N" if g["neutral_site"] else ("H" if side == "home" else "A"),
                        "conference_game": g["conference_game"], "periods": g["periods"],
                        "pts": g[f"{side}_score"], "opp_pts": g[f"{opp}_score"],
                    }
                    row.update({k: box[tid].get(k, "") for k in espn.BOX_STATS})
                    box_rows.append(row)
                failures.pop(gid, None)
                added += 1
            if added or removed:
                storage.save_box(key, season, box_rows)
            have = len({r["game_id"] for r in box_rows})
            gave_up = sum(1 for g in games.values() if failures.get(g["game_id"], 0) >= config.MAX_BOX_ATTEMPTS)
            box_report = [
                [f"{sport['label']} {name} box scores saved", have],
                [f"{sport['label']} {name} box scores still to download", max(len(need) - added, 0)],
                [f"{sport['label']} {name} box scores ESPN never provided", gave_up],
            ]

        changed = changed or games_changed or added > 0 or removed > 0
        all_games[season] = games
        finished = sum(1 for g in games.values() if g["completed"])
        report += [
            [f"{sport['label']} {name} games on file", len(games)],
            [f"{sport['label']} {name} games finished", finished],
            [f"{sport['label']} {name} newly final this run", len(new_finals) if before else 0],
        ] + box_report
        print(f"[{sport['label']}] {name}: {len(games)} games, {len(new_finals)} newly final, "
              f"{added} box scores added, {max(len(need) - added, 0)} still to download")

    storage.save_state(key, state)

    # ---- each team's conference, taken from its most recent game
    for season in sorted(all_games):
        for g in sorted(all_games[season].values(), key=lambda r: r["date_local"]):
            for side in ("home", "away"):
                tid, conf = g[f"{side}_id"], g[f"{side}_conf_id"]
                if tid in teams and conf:
                    teams[tid]["conf_id"] = conf
    for t in teams.values():
        if conf_names.get(t.get("conf_id", "")):
            t["conference"] = conf_names[t["conf_id"]]
    teams_changed = teams.keys() != old_teams.keys() or any(
        not same_row(old_teams.get(tid), t, storage.TEAM_FIELDS) for tid, t in teams.items())
    if teams_changed:
        storage.save_teams(key, teams)

    return changed or teams_changed, report


def main():
    full = os.environ.get("FULL_REFRESH", "").lower() == "true"
    manual = os.environ.get("GITHUB_EVENT_NAME", "") == "workflow_dispatch"
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    today_local = now.date()
    today_espn = datetime.now(ZoneInfo(config.ESPN_DAY_TIMEZONE)).date()
    refresh_hour = now.hour == config.DAILY_REFRESH_HOUR
    weekly = refresh_hour and now.weekday() == config.OFFSEASON_WEEKDAY

    sports = {k: s for k, s in config.SPORTS.items() if s.get("enabled")}
    active = {k: seasons.in_season(s, today_local) for k, s in sports.items()}

    if not (full or manual or weekly or any(active.values())):
        print("Offseason for every sport: nothing to do this hour.")
        write_output(skip="true", changed="false")
        return

    heartbeat(today_local)
    any_changed = False
    summary = {"last_run": now.strftime("%Y-%m-%d %I:%M %p %Z"), "sports": {}}

    for key, sport in sports.items():
        if not (active[key] or full or manual or weekly):
            continue
        # Full current-season schedule: daily at 5 AM in season; on every (weekly/manual) run offseason
        schedule_refresh = refresh_hour or not active[key]
        if full:
            run_type = "full refresh (manual)"
        elif not active[key]:
            run_type = "offseason check"
        elif refresh_hour:
            run_type = "daily schedule refresh"
        else:
            run_type = "hourly check" + (" (manual)" if manual else "")
        print(f"[{sport['label']}] {run_type}, current season {seasons.label(sport, seasons.current_season(sport, today_local))}")
        changed, report = update_sport(key, sport, full=full, schedule_refresh=schedule_refresh,
                                       today_espn=today_espn, today_local=today_local)
        any_changed = any_changed or changed
        summary["sports"][key] = {"run_type": run_type, "changed": changed, "report": report}

    storage.save_run_summary(summary)
    write_output(skip="false", changed="true" if any_changed else "false")
    print("Done. Anything changed:", any_changed)


if __name__ == "__main__":
    main()
