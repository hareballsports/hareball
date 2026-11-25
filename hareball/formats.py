"""Conference tournament formats and known results used to check our work.

A format applies from its `first_season` onward until a newer format replaces it.
If the conference changes its bracket, add a new entry here instead of editing the old one.
Seasons are named by the year they end (2026 = 2025-26).
"""

# Big Ten men's basketball, 18-team bracket (first used 2025-26, from the official 2026 bracket)
# Each game: (game id, round number, top slot, bottom slot)
# A slot is ("seed", n) or ("winner", game id).
BIG_TEN_MBB_18 = {
    "first_season": 2026,
    "teams": 18,
    "round_names": ["First round", "Second round", "Third round", "Quarterfinals", "Semifinals", "Championship"],
    "games": [
        ("G1", 0, ("seed", 17), ("seed", 16)),
        ("G2", 0, ("seed", 18), ("seed", 15)),
        ("G3", 1, ("seed", 9), ("winner", "G1")),
        ("G4", 1, ("seed", 13), ("seed", 12)),
        ("G5", 1, ("seed", 10), ("winner", "G2")),
        ("G6", 1, ("seed", 14), ("seed", 11)),
        ("G7", 2, ("winner", "G3"), ("seed", 8)),
        ("G8", 2, ("winner", "G4"), ("seed", 5)),
        ("G9", 2, ("winner", "G5"), ("seed", 7)),
        ("G10", 2, ("winner", "G6"), ("seed", 6)),
        ("G11", 3, ("seed", 1), ("winner", "G7")),
        ("G12", 3, ("winner", "G8"), ("seed", 4)),
        ("G13", 3, ("winner", "G9"), ("seed", 2)),
        ("G14", 3, ("winner", "G10"), ("seed", 3)),
        ("G15", 4, ("winner", "G11"), ("winner", "G12")),
        ("G16", 4, ("winner", "G13"), ("winner", "G14")),
        ("Final", 5, ("winner", "G15"), ("winner", "G16")),
    ],
}

TOURNAMENT_FORMATS = {
    "mbb": {"7": [BIG_TEN_MBB_18]},
}

# Official seeds, used to test the standings and tiebreaker code (seed 1 first)
OFFICIAL_SEEDS = {
    "mbb": {
        "7": {
            2026: ["Michigan", "Nebraska", "Michigan State", "Illinois", "Wisconsin", "UCLA",
                   "Purdue", "Ohio State", "Iowa", "Indiana", "Minnesota", "Washington",
                   "USC", "Rutgers", "Northwestern", "Oregon", "Maryland", "Penn State"],
        },
    },
}

# Regular-season conference games each team plays (used as a data check)
CONFERENCE_GAMES_PER_TEAM = {"mbb": {"7": 20}}


def tournament_format(sport_key, conf_id, season):
    """The format in use for a season, or None if we don't have one."""
    best = None
    for fmt in TOURNAMENT_FORMATS.get(sport_key, {}).get(conf_id, []):
        if fmt["first_season"] <= season and (best is None or fmt["first_season"] > best["first_season"]):
            best = fmt
    return best


def entry_round(fmt, seed):
    """Round number in which a seed plays its first game."""
    for _, rnd, top, bottom in fmt["games"]:
        if ("seed", seed) in (top, bottom):
            return rnd
    return None


def seed_note(fmt, seed):
    """Plain-English bye description for a seed, e.g. 'Bye to the quarterfinals'."""
    if fmt is None:
        return ""
    if seed > fmt["teams"]:
        return "Does not qualify"
    rnd = entry_round(fmt, seed)
    if rnd is None:
        return ""
    if rnd == 0:
        return "Plays in the first round"
    return f"Bye to the {fmt['round_names'][rnd].lower()}"


# How to read parts of the tiebreaker rules that aren't spelled out.
# restart_when_two_remain: when a tie of 3+ teams is cut to two teams at step 2 or later,
#   do those two go back to head-to-head? The 2025-26 rules don't say so, so the default is False.
TIEBREAK_OPTIONS = {
    "mbb": {"7": {"restart_when_two_remain": False}},
}


def tiebreak_options(sport_key, conf_id):
    return TIEBREAK_OPTIONS.get(sport_key, {}).get(conf_id, {})
