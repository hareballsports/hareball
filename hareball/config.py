"""Settings for the Hareball data job.

You should rarely need to edit this file:
  - Seasons roll over on their own (worked out from today's date).
  - To keep more past seasons for testing, raise HISTORY_SEASONS.
  - To add a sport later, add an entry to SPORTS.
"""

SPORTS = {
    "mbb": {
        "label": "MBB",                      # short tag used in Sheet tab names and folders
        "name": "Men's college basketball",
        "enabled": True,
        "espn_path": "basketball/mens-college-basketball",
        "espn_groups": 50,                   # ESPN code for "all of Division I"
        # Season calendar as (month, day). The season is named by the year it ENDS (2027 = 2026-27).
        "season_start": (11, 1),
        "season_end": (4, 15),
        "season_named_by": "end_year",
        "focus_conference_id": "7",          # ESPN's id for the Big Ten
        "focus_conference_name": "Big Ten",
        "sheet_env": "SHEET_ID",             # which GitHub secret holds this sport's Google Sheet id
        "box_scores": True,
    },
}

# How many finished seasons to keep collecting alongside the current one (used for testing models)
HISTORY_SEASONS = 1

# Hourly checks run from this many days before the season starts until this many days after it ends.
# Outside that window the job only does one full check a week.
PRESEASON_LEAD_DAYS = 14
POSTSEASON_TAIL_DAYS = 3

# Local time zone, the hour of the daily full schedule refresh, and the offseason weekly check day
TIMEZONE = "America/Chicago"
DAILY_REFRESH_HOUR = 5
OFFSEASON_WEEKDAY = 0  # 0 = Monday

# ESPN's scoreboard "day" follows US Eastern time
ESPN_DAY_TIMEZONE = "America/New_York"

# Box scores to download per run; the first runs catch up on older games a batch at a time
BOX_SCORES_PER_RUN = 1500
MAX_BOX_ATTEMPTS = 3

# Pause between ESPN requests, in seconds
REQUEST_DELAY = 0.25

# GitHub pauses scheduled jobs after 60 days with no repository activity.
# The job saves a small "heartbeat" file at least this often so that never happens in the offseason.
HEARTBEAT_DAYS = 25
