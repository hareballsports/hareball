# Hareball

College sports by the numbers. Starting with Big Ten men's basketball.

## How the data job works

A GitHub Actions job (`.github/workflows/update-data.yml`) starts every hour.

1. **`scripts/update_data.py`** decides what to do and downloads data from ESPN into `data/`:
   - **In season, hourly:** yesterday's and today's games.
   - **In season, 5 AM Central:** the whole current-season schedule and the team list.
   - **Offseason:** nothing, except a full check every Monday at 5 AM.
   - Box scores for finished Division I vs Division I games, a batch per run until caught up.
2. The job saves any changed files in `data/` back to this repository.
3. **`scripts/sync_sheet.py`** mirrors the data into the Google Sheet, rewriting only tabs that changed.

Seasons are worked out from the date (`hareball/seasons.py`), so a new season starts on its own.

## Files

| Path | What it is |
|---|---|
| `hareball/config.py` | Settings: sports, seasons kept, timing |
| `hareball/seasons.py` | Season dates and labels from the calendar |
| `hareball/espn.py` | Downloads and tidies ESPN data |
| `hareball/storage.py` | Reads and writes the CSV files in `data/` |
| `hareball/sheets.py` | Writes to the Google Sheet |
| `data/<sport>/<season>/games.csv` | Every game: schedule, status and scores |
| `data/<sport>/<season>/team_box.csv` | One row per team per game: box score stats |
| `data/<sport>/teams.csv` | Team list with conference and colors |

## Common changes

- **Keep more past seasons for testing:** raise `HISTORY_SEASONS` in `hareball/config.py`.
- **Re-download everything:** Actions → Update data → Run workflow → tick "Full refresh".
- **Add a sport:** add an entry to `SPORTS` in `hareball/config.py`.

## Secrets (Settings → Secrets and variables → Actions)

- `GOOGLE_CREDENTIALS`: the Google service account key (JSON)
- `SHEET_ID`: the Google Sheet's id
