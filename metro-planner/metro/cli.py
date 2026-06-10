"""Command-line interface.

Examples
--------
    python -m metro.cli --data data/shanghai_sample.json --from 莘庄 --to 陆家嘴 --depart 08:00
    python -m metro.cli --data data/shanghai_sample.json --from 莘庄 --to 四川北路 --depart 18:10
    python -m metro.cli --data data/shanghai_sample.json --list
    python -m metro.cli --data data/shanghai_sample.json --from 莘庄 --to 陆家嘴 --json
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys

from .model import Network, parse_hhmm, fmt_hhmm
from .planner import plan, render


def _default_data_path() -> str:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(here, "data", "shanghai_sample.json")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="metro",
        description="根据随申行式地铁数据，计算 A 站到 B 站的出行时间（含换乘预留与候车时间）。",
    )
    p.add_argument("--data", default=_default_data_path(),
                   help="线网数据 JSON 路径（默认使用内置上海示例数据）")
    p.add_argument("--from", dest="origin", help="起点站名，如 莘庄")
    p.add_argument("--to", dest="dest", help="终点站名，如 陆家嘴")
    p.add_argument("--depart", default="08:00",
                   help="出发时刻 HH:MM（默认 08:00）")
    p.add_argument("--wait-model", default="grid",
                   choices=["grid", "half", "full"],
                   help="候车模型：grid=按时刻表算下一班车(默认)，half=间隔/2，full=满间隔")
    p.add_argument("--list", action="store_true", help="列出所有线路与车站后退出")
    p.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = p.parse_args(argv)

    try:
        net = Network.from_json(args.data)
    except FileNotFoundError:
        print(f"找不到数据文件：{args.data}", file=sys.stderr)
        return 2

    if args.list:
        _print_listing(net, as_json=args.json)
        return 0

    if not args.origin or not args.dest:
        p.error("请用 --from 和 --to 指定起点与终点（或使用 --list 查看车站）")

    depart = parse_hhmm(args.depart)
    try:
        it = plan(net, args.origin, args.dest, depart, wait_model=args.wait_model)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    if it is None:
        print(f"在 {args.depart} 之后没有可行的车次到达【{args.dest}】（可能已过末班车）。",
              file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(_itinerary_to_dict(it), ensure_ascii=False, indent=2))
    else:
        print(render(it))
    return 0


def _print_listing(net: Network, as_json: bool) -> None:
    if as_json:
        out = {
            "lines": [
                {"id": l.id, "name": l.name, "stations": l.stations}
                for l in net.lines.values()
            ],
            "interchanges": sorted(
                st for st, ls in net.station_lines.items() if len(ls) > 1
            ),
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    for l in net.lines.values():
        print(f"{l.name}（{l.id}）：{' - '.join(l.stations)}")
    inter = sorted(st for st, ls in net.station_lines.items() if len(ls) > 1)
    print("\n换乘站：" + "、".join(inter))


def _itinerary_to_dict(it) -> dict:
    return {
        "origin": it.origin,
        "dest": it.dest,
        "depart": fmt_hhmm(it.depart_time),
        "arrive": fmt_hhmm(it.arrive_time),
        "total_minutes": round(it.total, 1),
        "in_vehicle_minutes": round(it.total_in_vehicle, 1),
        "wait_minutes": round(it.total_wait, 1),
        "transfer_walk_minutes": round(it.total_walk, 1),
        "num_transfers": it.num_transfers,
        "legs": [
            {
                **{k: v for k, v in dataclasses.asdict(leg).items()
                   if k not in ("board_time", "alight_time")},
                "board_time": fmt_hhmm(leg.board_time),
                "alight_time": fmt_hhmm(leg.alight_time),
            }
            for leg in it.legs
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
