"""Metro network model: lines, stations, transfers, and timetable generation.

Time is represented internally as *minutes since midnight* (float allowed, so a
1.5-minute segment is fine).  Directions are encoded as integers:

    dir 0  ->  traveling in the order stations are listed (index 0 -> N-1),
               i.e. "toward the last station" (stations[-1]).
    dir 1  ->  traveling in reverse (index N-1 -> 0), "toward stations[0]".

The "next train" wait time can be computed three ways (see ``next_departure``):

    grid  : a coherent timetable is generated from (first, last, headway) with a
            per-station phase offset equal to the run time from the originating
            terminal.  Wait = exact time until the next scheduled departure.
    half  : wait = headway/2 (expected wait for a memoryless arrival).
    full  : wait = headway   (conservative / worst case).
"""

from __future__ import annotations

import json
from bisect import bisect_left
from dataclasses import dataclass, field


def parse_hhmm(s: str) -> int:
    """'08:30' -> 510 (minutes since midnight)."""
    h, m = s.strip().split(":")
    return int(h) * 60 + int(m)


def fmt_hhmm(t: float) -> str:
    """510 -> '08:30'.  Rounds to the nearest minute for clock display."""
    t = int(round(t))
    return f"{(t // 60) % 24:02d}:{t % 60:02d}"


@dataclass
class Service:
    """Operating hours + headway schedule for one direction of a line."""

    first: int                       # first terminal departure (min since midnight)
    last: int                        # last terminal departure
    periods: list[tuple[int, int, float]]  # (from, to, headway_minutes), sorted

    def headway_at(self, t: float) -> float | None:
        """Applicable headway at time ``t`` (None if outside service hours)."""
        for a, b, h in self.periods:
            if a <= t < b:
                return h
        if self.periods and self.periods[0][0] <= t <= self.last:
            # t lands exactly on the closing boundary -> use the last period.
            return self.periods[-1][2]
        return None

    def terminal_departures(self) -> list[int]:
        """All terminal departure times between ``first`` and ``last``."""
        deps: list[int] = []
        cur = float(self.first)
        while cur <= self.last:
            deps.append(int(round(cur)))
            h = self.headway_at(cur)
            if not h or h <= 0:
                break
            cur += h
        return deps


@dataclass
class Line:
    id: str
    name: str
    stations: list[str]
    segments: list[float]            # len == len(stations) - 1; segments[j] = time j<->j+1
    service: dict[int, Service]      # keyed by direction 0 / 1

    index: dict[str, int] = field(default_factory=dict)
    _cum: dict[int, list[float]] = field(default_factory=dict)      # cumulative run time from terminal
    _deps: dict[tuple[int, int], list[int]] = field(default_factory=dict)  # (dir, station_idx) -> sorted departures

    def __post_init__(self) -> None:
        self.index = {name: i for i, name in enumerate(self.stations)}
        n = len(self.stations)
        # Cumulative run time from the originating terminal of each direction.
        cum0 = [0.0] * n
        for i in range(1, n):
            cum0[i] = cum0[i - 1] + self.segments[i - 1]
        cum1 = [0.0] * n
        for i in range(n - 2, -1, -1):
            cum1[i] = cum1[i + 1] + self.segments[i]
        self._cum = {0: cum0, 1: cum1}

    # -- topology -----------------------------------------------------------
    def neighbor_index(self, i: int, direction: int) -> int | None:
        if direction == 0:
            return i + 1 if i + 1 < len(self.stations) else None
        return i - 1 if i - 1 >= 0 else None

    def segment_time(self, i: int, direction: int) -> float:
        """Run time from station ``i`` to its neighbor in ``direction``."""
        return self.segments[i] if direction == 0 else self.segments[i - 1]

    def terminal_name(self, direction: int) -> str:
        return self.stations[-1] if direction == 0 else self.stations[0]

    # -- timetable ----------------------------------------------------------
    def station_departures(self, direction: int, i: int) -> list[int]:
        """Sorted departure times of trains *from* station ``i`` in ``direction``."""
        key = (direction, i)
        cached = self._deps.get(key)
        if cached is None:
            offset = self._cum[direction][i]
            cached = [d + offset for d in self.service[direction].terminal_departures()]
            self._deps[key] = cached
        return cached


class Network:
    """A metro network: a set of lines plus interchange (transfer) walk times."""

    def __init__(self, lines: dict[str, Line], transfers: dict, defaults: dict,
                 meta: dict | None = None):
        self.lines = lines
        self.defaults = defaults
        self.meta = meta or {}
        # transfers keyed by (station, frozenset({line_a, line_b})) -> minutes
        self.transfers: dict[tuple[str, frozenset], float] = transfers
        # station -> set of line ids that serve it
        self.station_lines: dict[str, set[str]] = {}
        for lid, line in lines.items():
            for st in line.stations:
                self.station_lines.setdefault(st, set()).add(lid)

    # -- queries ------------------------------------------------------------
    def has_station(self, station: str) -> bool:
        return station in self.station_lines

    def lines_at(self, station: str) -> set[str]:
        return self.station_lines.get(station, set())

    def transfer_time(self, station: str, line_a: str, line_b: str) -> float:
        if line_a == line_b:
            return self.defaults.get("same_line_reverse_minutes", 3)
        key = (station, frozenset({line_a, line_b}))
        if key in self.transfers:
            return self.transfers[key]
        return self.defaults.get("transfer_minutes", 4)

    def next_departure(self, line_id: str, station: str, direction: int,
                       t: float, wait_model: str = "grid") -> float | None:
        """Earliest departure time >= ``t`` from ``station`` toward ``direction``.

        Returns None if the station is a terminal in that direction (no onward
        train) or if there is no more service.
        """
        line = self.lines[line_id]
        i = line.index[station]
        if line.neighbor_index(i, direction) is None:
            return None  # terminal: cannot travel further this way
        if wait_model in ("half", "full"):
            h = line.service[direction].headway_at(t)
            if h is None:
                return None
            return t + (h / 2 if wait_model == "half" else h)
        # grid model: exact next scheduled departure
        deps = line.station_departures(direction, i)
        idx = bisect_left(deps, t)
        return deps[idx] if idx < len(deps) else None

    # -- loading ------------------------------------------------------------
    @classmethod
    def from_dict(cls, data: dict) -> "Network":
        defaults = data.get("defaults", {})
        default_service_raw = defaults.get("service")

        def build_service(raw: dict) -> dict[int, Service]:
            out: dict[int, Service] = {}
            for d in (0, 1):
                spec = raw[str(d)] if str(d) in raw else raw.get(str(0))
                first = parse_hhmm(spec["first"])
                last = parse_hhmm(spec["last"])
                if "periods" in spec:
                    periods = [
                        (parse_hhmm(p["from"]), parse_hhmm(p["to"]), float(p["headway"]))
                        for p in spec["periods"]
                    ]
                    periods.sort()
                else:
                    periods = [(first, last, float(spec["headway"]))]
                out[d] = Service(first=first, last=last, periods=periods)
            return out

        lines: dict[str, Line] = {}
        for ld in data["lines"]:
            raw_service = ld.get("service", default_service_raw)
            if raw_service is None:
                raise ValueError(f"Line {ld['id']} has no service and no defaults.service")
            lines[ld["id"]] = Line(
                id=ld["id"],
                name=ld.get("name", ld["id"]),
                stations=list(ld["stations"]),
                segments=[float(x) for x in ld["segments"]],
                service=build_service(raw_service),
            )
            if len(lines[ld["id"]].segments) != len(lines[ld["id"]].stations) - 1:
                raise ValueError(
                    f"Line {ld['id']}: segments must have len(stations)-1 entries"
                )

        transfers: dict[tuple[str, frozenset], float] = {}
        for tr in data.get("transfers", []):
            station = tr["station"]
            members = tr["between"]
            minutes = float(tr["minutes"])
            # store pairwise so frozenset lookup works for any two of the members
            for a in members:
                for b in members:
                    if a < b:
                        transfers[(station, frozenset({a, b}))] = minutes

        return cls(lines=lines, transfers=transfers, defaults=defaults,
                   meta=data.get("meta", {}))

    @classmethod
    def from_json(cls, path: str) -> "Network":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
