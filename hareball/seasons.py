"""Work out seasons from the calendar, so nothing needs editing each year."""

from datetime import date, timedelta

from . import config


def window(sport, season):
    """First and last day of a season, e.g. 2027 -> (2026-11-01, 2027-04-15)."""
    sm, sd = sport["season_start"]
    em, ed = sport["season_end"]
    crosses_new_year = (sm, sd) > (em, ed)
    if sport["season_named_by"] == "end_year":
        start_year, end_year = (season - 1, season) if crosses_new_year else (season, season)
    else:  # named by the year it starts (ESPN does this for football)
        start_year, end_year = (season, season + 1) if crosses_new_year else (season, season)
    return date(start_year, sm, sd), date(end_year, em, ed)


def current_season(sport, today):
    """The season in progress, or the next one if we're between seasons."""
    for season in range(today.year - 1, today.year + 3):
        _, end = window(sport, season)
        if today <= end:
            return season
    raise ValueError("could not work out the current season")


def kept_seasons(sport, today):
    """Current season first, then the past seasons we keep for testing."""
    cur = current_season(sport, today)
    return [cur - i for i in range(config.HISTORY_SEASONS + 1)]


def in_season(sport, today):
    start, end = window(sport, current_season(sport, today))
    return (start - timedelta(days=config.PRESEASON_LEAD_DAYS)
            <= today <= end + timedelta(days=config.POSTSEASON_TAIL_DAYS))


def label(sport, season):
    """2027 -> '2026-27' for basketball."""
    start, end = window(sport, season)
    if start.year == end.year:
        return str(start.year)
    return f"{start.year}-{end.year % 100:02d}"


def all_days(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)
