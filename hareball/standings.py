"""Conference standings with the Big Ten's official tiebreaker procedure.

How the procedure is applied (from the 2025-26 Big Ten men's basketball seeding rules):

  Teams are ordered by conference winning percentage. Teams with the same percentage are tied,
  and each group of tied teams is separated with these steps, in order:

  1. Head-to-head: each tied team's winning percentage in games against the other tied teams.
     Teams that separate take their places; teams still level move on to step 2 together
     (they do NOT restart head-to-head among themselves).
  2. Walk down the standings from the top. At each stop, compare the tied teams' winning
     percentage against that team, or against a group of tied teams taken together (before
     that group's own tiebreakers). The first stop where the percentages differ separates them.
     A stop is skipped if any tied team didn't play there (2-0 is not better than 0-0).
  3. Winning percentage against all Division I opponents (regular season).
  4. NET ranking from the previous week. We can't download the NET, so you type it into the
     Sheet when needed. If it's missing, the tie is shown as UNRESOLVED.

Winning percentage decides comparisons even when the number of games differs
(2-0 beats 3-1, but 2-0 does not beat 1-0).
"""

import re
from fractions import Fraction

NOT_CONFERENCE_SEASON = re.compile(r"tournament|championship", re.IGNORECASE)

STEP_NAMES = {
    1: "head-to-head",
    2: "record against the standings, top down",
    3: "record against Division I opponents",
    4: "NET ranking",
}


def _pct(w, l):
    return Fraction(w, w + l) if w + l else None


def _rec_text(w, l):
    return f"{w}-{l}"


class ConferenceStandings:
    def __init__(self, games, conf_id, names=None, through_date=None, net_ranks=None, conf_name="",
                 restart_when_two_remain=False):
        """games: list of game rows for one season. through_date: 'YYYY-MM-DD' or None for all."""
        self.conf_id = conf_id
        # Interpretation switch: when a 3+ team tie is cut down to two teams at step 2 or later,
        # should those two restart at head-to-head? The 2025-26 rules don't say so; default is no.
        self.restart_when_two_remain = restart_when_two_remain
        # Games in the conference's own tournament never count (e.g. "Big Ten Tournament - Quarterfinal")
        own_tourney = re.compile(rf"{re.escape(conf_name)}.*(tournament|championship)", re.IGNORECASE) if conf_name else None
        self.net_ranks = net_ranks or {}
        self.names = dict(names or {})
        self.warnings = []

        # Members: every team listed in this conference in any game this season
        self.members = set()
        for g in games:
            for side in ("home", "away"):
                if g[f"{side}_conf_id"] == conf_id and g[f"{side}_id"]:
                    self.members.add(g[f"{side}_id"])
                    self.names.setdefault(g[f"{side}_id"], g[f"{side}_team"])

        self.wins = {t: 0 for t in self.members}
        self.losses = {t: 0 for t in self.members}
        self.h2h = {}  # (a, b) -> [wins of a over b, losses of a to b]
        self.d1 = {t: [0, 0] for t in self.members}
        self.overall = {t: [0, 0] for t in self.members}

        for g in games:
            if not g["completed"] or g.get("season_type") != "Regular":
                continue
            if through_date and g["date_local"] > through_date:
                continue
            if str(g["home_score"]) == "" or str(g["away_score"]) == "":
                continue
            if own_tourney and own_tourney.search(g.get("note", "")):
                continue
            h, a = g["home_id"], g["away_id"]
            home_won = int(g["home_score"]) > int(g["away_score"])
            winner, loser = (h, a) if home_won else (a, h)

            for t in (h, a):
                if t in self.members:
                    self.overall[t][0 if t == winner else 1] += 1
                    if g["home_d1"] and g["away_d1"]:
                        self.d1[t][0 if t == winner else 1] += 1

            if h in self.members and a in self.members and not NOT_CONFERENCE_SEASON.search(g.get("note", "")):
                if not g["conference_game"]:
                    self.warnings.append(f"Game {g['game_id']} between two members isn't flagged as a conference game; counted anyway")
                self.wins[winner] += 1
                self.losses[loser] += 1
                self.h2h.setdefault((winner, loser), [0, 0])[0] += 1
                self.h2h.setdefault((loser, winner), [0, 0])[1] += 1

        self.notes = {t: "" for t in self.members}
        self.unresolved = set()

    # ------------------------------------------------------------ helpers
    def name(self, t):
        return self.names.get(t, t)

    def conf_pct(self, t):
        p = _pct(self.wins[t], self.losses[t])
        return p if p is not None else Fraction(1, 2)  # 0-0 sorts with .500 teams

    def record_vs(self, t, opponents):
        w = l = 0
        for o in opponents:
            if o == t:
                continue
            ww, ll = self.h2h.get((t, o), [0, 0])
            w += ww
            l += ll
        return w, l

    def _unit_name(self, unit):
        names = sorted(self.name(t) for t in unit)
        if len(names) == 1:
            return names[0]
        return "the tied group of " + ", ".join(names)

    @staticmethod
    def _partition(teams, key, reverse=True):
        """Split teams into groups with equal key, best first. Ties broken by name for display only."""
        values = sorted({key(t) for t in teams}, reverse=reverse)
        return [sorted(t for t in teams if key(t) == v) for v in values]

    def _add_note(self, t, text):
        self.notes[t] = (self.notes[t] + "; " if self.notes[t] else "") + text

    # ------------------------------------------------------------ ordering
    def order(self):
        """Return team ids in standings order (seed 1 first)."""
        self.notes = {t: "" for t in self.members}
        self.unresolved = set()
        if not any(self.wins.values()):
            return sorted(self.members, key=self.name)  # no conference games yet
        groups = self._partition(self.members, self.conf_pct)
        result = []
        for i, grp in enumerate(groups):
            if len(grp) == 1:
                result.append(grp[0])
                continue
            w, l = self.wins[grp[0]], self.losses[grp[0]]
            for t in grp:
                others = ", ".join(sorted(self.name(o) for o in grp if o != t))
                self._add_note(t, f"Tied at {_rec_text(w, l)} with {others}")
            above = [set(g) for g in groups[:i]]
            below = [set(g) for g in groups[i + 1:]]
            result += self._break(grp, above, below, step=1)
        return result

    def _break(self, tied, above, below, step, walk_from=0):
        tied = list(tied)
        if len(tied) == 1:
            return tied

        if step == 1:
            recs = {t: self.record_vs(t, set(tied)) for t in tied}
            if any(w + l == 0 for w, l in recs.values()):
                return self._break(tied, above, below, 2)
            parts = self._partition(tied, lambda t: _pct(*recs[t]))
            if len(parts) == 1:
                return self._break(tied, above, below, 2)
            out = []
            for i, part in enumerate(parts):
                for t in part:
                    self._add_note(t, f"head-to-head among tied teams {_rec_text(*recs[t])}")
                if len(part) == 1:
                    out.append(part[0])
                else:
                    sub_above = above + [{x} for x in out]
                    sub_below = [set(p) for p in parts[i + 1:]] + below
                    out += self._break(part, sub_above, sub_below, 2)
            return out

        if step == 2:
            stops = above + below
            for si in range(walk_from, len(stops)):
                unit = stops[si] - set(tied)
                if not unit:
                    continue
                recs = {t: self.record_vs(t, unit) for t in tied}
                if any(w + l == 0 for w, l in recs.values()):
                    continue
                parts = self._partition(tied, lambda t: _pct(*recs[t]))
                if len(parts) == 1:
                    continue
                out = []
                for part in parts:
                    for t in part:
                        self._add_note(t, f"record vs {self._unit_name(unit)} {_rec_text(*recs[t])}")
                    if len(part) == 1:
                        out.append(part[0])
                    elif len(part) == 2 and len(tied) > 2 and self.restart_when_two_remain:
                        out += self._break(part, above, below, 1)
                    else:
                        out += self._break(part, above, below, 2, walk_from=si + 1)
                return out
            return self._break(tied, above, below, 3)

        if step == 3:
            parts = self._partition(tied, lambda t: _pct(*self.d1[t]) or Fraction(0))
            if len(parts) == 1:
                return self._break(tied, above, below, 4)
            out = []
            for part in parts:
                for t in part:
                    self._add_note(t, f"record vs Division I {_rec_text(*self.d1[t])}")
                out += part if len(part) == 1 else self._break(part, above, below, 4)
            return out

        # step 4: NET ranking (lower is better), typed into the Sheet
        if all(self.net_ranks.get(t) for t in tied):
            out = sorted(tied, key=lambda t: self.net_ranks[t])
            for t in out:
                self._add_note(t, f"NET rank {self.net_ranks[t]}")
            return out
        for t in tied:
            self.unresolved.add(t)
            self._add_note(t, "UNRESOLVED: needs NET rankings in the Sheet")
        return sorted(tied, key=self.name)

    # ------------------------------------------------------------ output
    def table(self):
        """Standings rows in order, with games back and tiebreaker notes."""
        order = self.order()
        if not order:
            return []
        lead = order[0]
        rows = []
        for pos, t in enumerate(order, start=1):
            gb = ((self.wins[lead] - self.wins[t]) + (self.losses[t] - self.losses[lead])) / 2
            rows.append({
                "position": pos,
                "team_id": t,
                "team": self.name(t),
                "conf_w": self.wins[t],
                "conf_l": self.losses[t],
                "conf_pct": f"{float(_pct(self.wins[t], self.losses[t]) or 0):.3f}",
                "games_back": "-" if gb == 0 else (f"{gb:g}"),
                "overall": _rec_text(*self.overall[t]),
                "vs_d1": _rec_text(*self.d1[t]),
                "tiebreaker": self.notes[t],
                "unresolved": t in self.unresolved,
            })
        return rows
