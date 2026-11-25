"""Step 0 of each run: copy the tabs you edit by hand from the Google Sheet into data/inputs/.

Keeping a copy in the repository means:
  - later steps don't depend on the Sheet being reachable, and
  - every change you make is saved with a date, so you can see what changed and when.

If the Sheet can't be reached, the previous copies are kept and the run carries on.
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hareball import config, sheets, storage  # noqa: E402

import gspread  # noqa: E402


def save(name, values):
    storage.INPUTS_DIR.mkdir(parents=True, exist_ok=True)
    with (storage.INPUTS_DIR / name).open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(values)


def main():
    envs = {}
    for key, sport in config.SPORTS.items():
        if sport.get("enabled"):
            envs.setdefault(sport["sheet_env"], []).append((key, sport))

    for env_name, members in envs.items():
        try:
            sheet = sheets.open_sheet(env_name)
        except Exception as err:  # keep going with the saved copies
            print(f"WARNING: couldn't open the Sheet ({err}); using saved inputs")
            continue
        tabs = {"Settings": "settings.csv", "Overrides": "overrides.csv"}
        for key, sport in members:
            tabs[f"{sport['label']} NET Ranks"] = f"{key}_net_ranks.csv"
        for title, filename in tabs.items():
            try:
                values = sheet.worksheet(title).get_all_values()
            except gspread.WorksheetNotFound:
                continue
            save(filename, values)
            print(f"Saved inputs from tab: {title}")


if __name__ == "__main__":
    main()
