"""Tests for the metro journey planner.

Run with either:
    python -m pytest tests/
    python tests/test_planner.py        # no pytest needed
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from metro.model import Network, parse_hhmm  # noqa: E402
from metro.planner import plan  # noqa: E402


def _synthetic() -> Network:
    """Two lines crossing at station X, fixed headways for predictable waits.

        Line A: A1 - A2 - X - A3   segments [2, 3, 2]
        Line B: B1 - X - B2        segments [4, 5]
    Both lines: trains every 10 min, terminal departures on :00, service all day.
    Transfer A<->B at X takes 4 min.
    """
    data = {
        "defaults": {
            "transfer_minutes": 4,
            "service": {
                "0": {"first": "00:00", "last": "23:50", "headway": 10},
                "1": {"first": "00:00", "last": "23:50", "headway": 10},
            },
        },
        "lines": [
            {"id": "A", "name": "A线", "stations": ["A1", "A2", "X", "A3"],
             "segments": [2, 3, 2]},
            {"id": "B", "name": "B线", "stations": ["B1", "X", "B2"],
             "segments": [4, 5]},
        ],
        "transfers": [{"station": "X", "between": ["A", "B"], "minutes": 4}],
    }
    return Network.from_dict(data)


def test_no_transfer_single_line():
    net = _synthetic()
    # Depart A1 at 08:00. Line A dir0 train departs A1 at 08:00 (grid on :00).
    # A1->A2 (2) ->X (3): arrive X at 08:05. No wait beyond the initial board.
    it = plan(net, "A1", "X", parse_hhmm("08:00"))
    assert it is not None
    assert len(it.legs) == 1
    assert it.arrive_time == parse_hhmm("08:05")
    assert it.total_in_vehicle == 5
    assert it.total_wait == 0           # boarded exactly on departure
    assert it.num_transfers == 0


def test_initial_wait_counts():
    net = _synthetic()
    # Depart A1 at 08:03 -> next departure is 08:10 -> wait 7 min.
    it = plan(net, "A1", "X", parse_hhmm("08:03"))
    assert it.total_wait == 7
    assert it.arrive_time == parse_hhmm("08:15")   # 08:10 + 5 run time


def test_transfer_adds_walk_and_wait():
    net = _synthetic()
    # A1 -> B2 must transfer A->B at X.
    # Board A1 08:00, arrive X 08:05. Transfer walk 4 -> ready 08:09.
    # Line B trains leave terminal B1 on :00,:10,... and B1->X takes 4 min, so
    # they pass X on :04,:14,... -> next departure from X is 08:14 (wait 5).
    # X->B2 segment = 5 -> arrive 08:19.
    it = plan(net, "A1", "B2", parse_hhmm("08:00"))
    assert it is not None
    assert it.num_transfers == 1
    assert it.total_walk == 4
    # initial wait 0 + transfer wait 5
    assert it.total_wait == 5
    assert it.arrive_time == parse_hhmm("08:19")
    assert it.total_in_vehicle == 5 + 5   # A1->X is 5, X->B2 is 5


def test_same_station_zero():
    net = _synthetic()
    it = plan(net, "X", "X", parse_hhmm("08:00"))
    assert it is not None
    assert it.total == 0
    assert it.legs == []


def test_unreachable_after_service_ends():
    net = _synthetic()
    # last terminal departure 23:50; depart 23:55 -> no train.
    it = plan(net, "A1", "A3", parse_hhmm("23:55"))
    assert it is None


def test_wait_model_half_vs_full():
    net = _synthetic()
    half = plan(net, "A1", "X", parse_hhmm("08:03"), wait_model="half")
    full = plan(net, "A1", "X", parse_hhmm("08:03"), wait_model="full")
    assert half.total_wait == 5     # headway 10 / 2
    assert full.total_wait == 10    # full headway


def test_sample_data_loads_and_plans():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    net = Network.from_json(os.path.join(here, "data", "shanghai_sample.json"))
    # 莘庄 (Line 1) -> 陆家嘴 (Line 2): exactly one transfer at 人民广场.
    it = plan(net, "莘庄", "陆家嘴", parse_hhmm("08:00"))
    assert it is not None
    assert it.num_transfers == 1
    assert it.legs[0].line_id == "1"
    assert it.legs[1].line_id == "2"
    assert it.legs[0].alight_station == "人民广场"
    # 莘庄 -> 四川北路 (Line 10): needs two transfers (1->2->10).
    it2 = plan(net, "莘庄", "四川北路", parse_hhmm("18:10"))
    assert it2 is not None
    assert it2.num_transfers == 2
    assert [l.line_id for l in it2.legs] == ["1", "2", "10"]


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} tests passed.")


if __name__ == "__main__":
    _run_all()
