"""Step 2 of each run: mirror the data files into the Google Sheet.

Only tabs whose contents changed are rewritten. Tabs you edit by hand
(Settings, Overrides, Posting) are created once and never overwritten.
Data tabs for seasons we no longer keep are removed (the files stay in the repository).
"""

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hareball import config, seasons, sheets, storage  # noqa: E402


def sport_tables(key, sport, today):
    """Build {tab title: (header, rows)} for one sport."""
    L = sport["label"]
    kept = seasons.kept_seasons(sport, today)
    cur = kept[0]
    cur_name = seasons.label(sport, cur)
    teams = storage.load_teams(key)
    tables = {}

    games_by_season = {s: storage.load_games(key, s) for s in kept}
    cur_games = games_by_season[cur]

    # Teams, with this season's overall record
    record = {tid: [0, 0] for tid in teams}
    for g in cur_games.values():
        if g["completed"] and str(g["home_score"]) != "" and str(g["away_score"]) != "":
            home_won = int(g["home_score"]) > int(g["away_score"])
            if g["home_id"] in record:
                record[g["home_id"]][0 if home_won else 1] += 1
            if g["away_id"] in record:
                record[g["away_id"]][1 if home_won else 0] += 1
    header = storage.TEAM_FIELDS + [f"{cur_name} W", f"{cur_name} L"]
    rows = [[t.get(h, "") for h in storage.TEAM_FIELDS] + record[tid]
            for tid, t in sorted(teams.items(), key=lambda kv: kv[1]["team"])]
    tables[f"{L} Teams"] = (header, rows)

    # Focus conference schedule for the current season
    fid = sport.get("focus_conference_id")
    if fid:
        rows = [g for g in sorted(cur_games.values(), key=lambda r: (r["date_local"], r["time_local"]))
                if fid in (g["home_conf_id"], g["away_conf_id"])]
        header = ["date_local", "time_local", "away_team", "away_score", "home_team", "home_score",
                  "status", "conference_game", "neutral_site", "note", "game_id"]
        tables[f"{L} {sport['focus_conference_name']} Schedule"] = (header, rows)

    # Every game, one tab per kept season
    for s, games in games_by_season.items():
        rows = sorted(games.values(), key=lambda r: (r["date_local"], r["time_local"]))
        tables[f"{L} Games {seasons.label(sport, s)}"] = (storage.GAME_FIELDS, rows)

    # Box scores, current season only (older seasons stay in the repository files)
    if sport.get("box_scores"):
        tables[f"{L} Team Box {cur_name}"] = (storage.BOX_FIELDS, storage.load_box(key, cur))

    # Conference standings and projected bracket, current season
    if fid:
        conf_name = sport["focus_conference_name"]
        rows = storage.read_rows(storage.standings_path(key, cur, fid, "standings"))
        header = ["position", "team", "conf_w", "conf_l", "conf_pct", "games_back", "overall",
                  "vs_d1", "seed_note", "tiebreaker"]
        tables[f"{L} {conf_name} Standings"] = (header, rows)
        bracket = storage.read_rows(storage.standings_path(key, cur, fid, "bracket"))
        if bracket:
            tables[f"{L} {conf_name} Bracket"] = (storage.BRACKET_FIELDS, bracket)

    # Official seed checks (seasons where we know the real answer)
    checks = storage.load_json_run("standings_checks.json") or {}
    check_rows = []
    for c in checks.values():
        if c["sport"] != key:
            continue
        check_rows.append([f"{c['label']}: {c['matches']} of {c['total']} seeds match", "", "", "", "", ""])
        check_rows += c["rows"]
        check_rows.append(["", "", "", "", "", ""])
    if check_rows:
        tables[f"{L} Standings Check"] = (["seed", "official", "ours", "match", "conf record", "tiebreaker"], check_rows)

    return tables


def main():
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    summary = storage.load_run_summary()
    sports = {k: s for k, s in config.SPORTS.items() if s.get("enabled")}

    # Group sports by which Google Sheet they live in
    by_sheet = {}
    for key, sport in sports.items():
        by_sheet.setdefault(sport["sheet_env"], []).append((key, sport))

    for env_name, members in by_sheet.items():
        sheet = sheets.open_sheet(env_name)
        existing = {ws.title: ws for ws in sheet.worksheets()}
        sync = sheets.read_sync(sheet)

        for key, sport in members:
            L = sport["label"]
            tables = sport_tables(key, sport, now.date())
            for title, (header, rows) in tables.items():
                values = sheets.to_values(header, rows)
                fp = sheets.fingerprint(values)
                if sync.get(title) != fp or title not in existing:
                    print(f"Writing tab: {title} ({len(values) - 1} rows)")
                    sheets.write_values(sheet, title, values)
                    sync[title] = fp
            # Remove this sport's data tabs for seasons we no longer keep
            for title, ws in existing.items():
                is_season_tab = title.startswith(f"{L} Games ") or title.startswith(f"{L} Team Box ")
                if is_season_tab and title not in tables:
                    print(f"Removing old tab: {title}")
                    sheet.del_worksheet(ws)
                    sync.pop(title, None)

        # Tabs you edit by hand (created once, never overwritten)
        starter = []
        for key, sport in members:
            starter += [
                [key, "nonconference_fade_k", 5, "Phase 4: how fast non-conference games fade in the conference rating"],
            ]
        starter.append(["all", "posting_paused", "FALSE", "Phase 6: set to TRUE to stop all automatic graphics"])
        sheets.ensure_table(sheet, "Settings", ["sport", "setting", "value", "notes"], starter)
        sheets.ensure_table(sheet, "Overrides", ["sport", "game_id", "field", "value", "notes"])
        sheets.ensure_table(sheet, "Posting", ["sport", "date", "graphic", "file", "status", "notes"])
        for key, sport in members:
            cur = seasons.current_season(sport, now.date())
            fid = sport.get("focus_conference_id")
            standing_rows = storage.read_rows(storage.standings_path(key, cur, fid, "standings")) if fid else []
            starter_net = [[seasons.label(sport, cur), r["team_id"], r["team"], "", ""]
                           for r in sorted(standing_rows, key=lambda r: r["team"])]
            sheets.ensure_table(sheet, f"{sport['label']} NET Ranks",
                                ["season", "team_id", "team", "net_rank", "notes"], starter_net)

        # Status tab: always refreshed, so you can see the job is alive
        status = [["Sheet last updated", now.strftime("%Y-%m-%d %I:%M %p %Z")]]
        if summary:
            status.append(["Data last downloaded", summary.get("last_run", "")])
            for key, sport in members:
                info = (summary.get("sports") or {}).get(key)
                if not info:
                    status.append([f"{sport['label']} this run", "not checked (offseason hour)"])
                    continue
                status.append([f"{sport['label']} run type", info["run_type"]])
                status.append([f"{sport['label']} anything changed", "TRUE" if info["changed"] else "FALSE"])
                status += info["report"]
            checks = storage.load_json_run("standings_checks.json") or {}
            for c in checks.values():
                if c["sport"] in dict(members):
                    status.append([f"{config.SPORTS[c['sport']]['label']} {c['label']} official seeds matched",
                                   f"{c['matches']} of {c['total']}"])
        else:
            status.append(["Data step", "did not finish this run; see the run log on GitHub"])
        sheets.write_values(sheet, "Status", sheets.to_values(["item", "value"], status))

        sheets.write_sync(sheet, sync)
    print("Sheet updated.")


if __name__ == "__main__":
    main()
