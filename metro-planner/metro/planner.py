"""Earliest-arrival journey planner (time-dependent Dijkstra).

Graph model.  Each node is a *ride state* ``("R", station, line, direction)``
meaning "you are at ``station`` aboard ``line`` heading ``direction``".  Plus a
virtual origin ``("O", station)`` and destination ``("D", station)``.

Edges (all edge costs are time-dependent because boarding waits depend on the
clock):

  * board at origin   O(s0) -> R(s0, L, d)     cost = wait for next train
  * ride one stop     R(s, L, d) -> R(s', L, d) cost = segment run time (NO wait)
  * transfer          R(s, La, da) -> R(s, Lb, db)
                                      cost = walk(预留) + wait for next train
  * alight at dest    R(dest, L, d) -> D(dest)  cost = 0 (+ optional egress)

Because riding stays on the same train (no re-wait) while every board/transfer
pays the realistic wait, the shortest path in arrival time = the fastest real
journey.  The "next train" function is FIFO (waiting longer never arrives
earlier), so Dijkstra is correct.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass

from .model import Network, fmt_hhmm


@dataclass
class Leg:
    line_id: str
    line_name: str
    direction: int
    terminal: str               # destination terminal of this direction (开往 X 方向)
    board_station: str
    alight_station: str
    board_time: float
    alight_time: float
    stops: int
    in_vehicle: float
    wait_before: float          # boarding wait before this leg (initial or transfer wait)
    walk_before: float          # transfer walk before this leg (0 for the first leg)


@dataclass
class Itinerary:
    origin: str
    dest: str
    depart_time: float
    arrive_time: float
    legs: list[Leg]

    @property
    def total(self) -> float:
        return self.arrive_time - self.depart_time

    @property
    def total_wait(self) -> float:
        return sum(l.wait_before for l in self.legs)

    @property
    def total_walk(self) -> float:
        return sum(l.walk_before for l in self.legs)

    @property
    def total_in_vehicle(self) -> float:
        return sum(l.in_vehicle for l in self.legs)

    @property
    def num_transfers(self) -> int:
        return max(0, len(self.legs) - 1)


def _expand(net: Network, node, t: float, dest: str, wait_model: str):
    """Yield (neighbor_node, arrival_time) pairs reachable from ``node`` at ``t``."""
    kind = node[0]

    if kind == "O":
        _, s0 = node
        for lid in sorted(net.lines_at(s0)):
            for d in (0, 1):
                dep = net.next_departure(lid, s0, d, t, wait_model)
                if dep is not None:
                    yield ("R", s0, lid, d), dep
        return

    if kind == "R":
        _, s, lid, d = node
        line = net.lines[lid]
        i = line.index[s]

        # 1) stay on the train, ride to the next stop (no extra wait)
        ni = line.neighbor_index(i, d)
        if ni is not None:
            yield ("R", line.stations[ni], lid, d), t + line.segment_time(i, d)

        # 2) alight here -> reach destination
        if s == dest:
            egress = net.defaults.get("egress_minutes", 0)
            yield ("D", s), t + egress

        # 3) transfer to another line/direction at this station
        for lid2 in sorted(net.lines_at(s)):
            line2 = net.lines[lid2]
            for d2 in (0, 1):
                if lid2 == lid and d2 == d:
                    continue  # same train, same direction -> not a transfer
                walk = net.transfer_time(s, lid, lid2)
                dep = net.next_departure(lid2, s, d2, t + walk, wait_model)
                if dep is not None:
                    yield ("R", s, lid2, d2), dep
        return
    # kind == "D": terminal node, no outgoing edges


def plan(net: Network, origin: str, dest: str, depart: float,
         wait_model: str = "grid") -> Itinerary | None:
    """Compute the earliest-arrival itinerary from ``origin`` to ``dest``.

    ``depart`` is minutes since midnight.  Returns None if unreachable (e.g. no
    more service today).
    """
    if not net.has_station(origin):
        raise ValueError(f"未知车站：{origin}")
    if not net.has_station(dest):
        raise ValueError(f"未知车站：{dest}")
    if origin == dest:
        return Itinerary(origin, dest, depart, depart, [])

    start = ("O", origin)
    best: dict = {start: depart}
    prev: dict = {start: None}
    counter = 0
    pq: list = [(depart, counter, start)]

    while pq:
        t, _, node = heapq.heappop(pq)
        if t > best.get(node, float("inf")):
            continue
        if node == ("D", dest):
            return _reconstruct(net, prev, best, origin, dest, depart)
        for nb, nt in _expand(net, node, t, dest, wait_model):
            if nt < best.get(nb, float("inf")):
                best[nb] = nt
                prev[nb] = node
                counter += 1
                heapq.heappush(pq, (nt, counter, nb))

    return None


def _reconstruct(net: Network, prev: dict, best: dict, origin: str, dest: str,
                 depart: float) -> Itinerary:
    # rebuild the node sequence O -> R... -> D
    seq = []
    node = ("D", dest)
    while node is not None:
        seq.append(node)
        node = prev[node]
    seq.reverse()

    ride_nodes = [n for n in seq if n[0] == "R"]
    legs: list[Leg] = []
    if not ride_nodes:
        return Itinerary(origin, dest, depart, best[("D", dest)], legs)

    def start_leg(rn, prev_alight_time, walk_before):
        _, s, lid, d = rn
        line = net.lines[lid]
        return {
            "lid": lid, "name": line.name, "dir": d,
            "terminal": line.terminal_name(d),
            "board_station": s, "board_time": best[rn],
            "alight_station": s, "alight_time": best[rn],
            "board_idx": line.index[s], "alight_idx": line.index[s],
            "wait_before": best[rn] - prev_alight_time - walk_before,
            "walk_before": walk_before,
        }

    # first leg: boarded from the origin
    cur = start_leg(ride_nodes[0], depart, 0.0)

    for rn in ride_nodes[1:]:
        _, s, lid, d = rn
        if lid == cur["lid"] and d == cur["dir"]:
            # continued ride on the same train
            cur["alight_station"] = s
            cur["alight_time"] = best[rn]
            cur["alight_idx"] = net.lines[lid].index[s]
        else:
            # a transfer happened at cur["alight_station"]
            walk = net.transfer_time(cur["alight_station"], cur["lid"], lid)
            legs.append(_finalize(cur))
            cur = start_leg(rn, cur["alight_time"], walk)

    legs.append(_finalize(cur))
    return Itinerary(origin, dest, depart, best[("D", dest)], legs)


def _finalize(c: dict) -> Leg:
    stops = abs(c["alight_idx"] - c["board_idx"])
    return Leg(
        line_id=c["lid"], line_name=c["name"], direction=c["dir"],
        terminal=c["terminal"], board_station=c["board_station"],
        alight_station=c["alight_station"], board_time=c["board_time"],
        alight_time=c["alight_time"], stops=stops,
        in_vehicle=c["alight_time"] - c["board_time"],
        wait_before=max(0.0, c["wait_before"]), walk_before=c["walk_before"],
    )


def render(it: Itinerary) -> str:
    """Human-readable Chinese itinerary."""
    if not it.legs:
        return f"{it.origin} 与 {it.dest} 为同一车站，无需乘车。"

    lines = []
    lines.append(f"🚇 从【{it.origin}】到【{it.dest}】")
    lines.append(f"   出发 {fmt_hhmm(it.depart_time)}  →  到达 {fmt_hhmm(it.arrive_time)}")
    lines.append(
        f"   全程约 {round(it.total)} 分钟"
        f"（乘车 {round(it.total_in_vehicle)} + 候车 {round(it.total_wait)} +"
        f" 换乘步行 {round(it.total_walk)}），换乘 {it.num_transfers} 次"
    )
    lines.append("")

    for idx, leg in enumerate(it.legs):
        if idx == 0:
            lines.append(
                f"  [候车 {round(leg.wait_before)} 分] {fmt_hhmm(leg.board_time)} "
                f"在【{leg.board_station}】上车"
            )
        else:
            lines.append(
                f"  ↳ 换乘：步行 {round(leg.walk_before)} 分 + 候车 "
                f"{round(leg.wait_before)} 分"
            )
        lines.append(
            f"     乘 {leg.line_name}（开往 {leg.terminal} 方向）"
            f" {leg.stops} 站，约 {round(leg.in_vehicle)} 分"
        )
        lines.append(
            f"     {fmt_hhmm(leg.alight_time)} 到达【{leg.alight_station}】"
        )
    return "\n".join(lines)
