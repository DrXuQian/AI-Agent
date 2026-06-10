"""Online provider: Baidu Maps (百度地图) transit routing.

This adapter fetches a *real* (live, schedule-accurate) A->B transit plan from
Baidu Maps instead of computing it from local sample data.  It:

  1. geocodes the station names to BD-09 coordinates via Place Search, then
  2. calls the lightweight transit routing API
     ``GET https://api.map.baidu.com/directionlite/v1/transit``

Baidu returns an *integrated* ``duration`` (seconds) that already folds in
walking, waiting and riding -- which is exactly "the real overall time".  Note
Baidu does NOT expose per-leg waiting time separately, so unlike the offline
engine we report the authoritative total + per-leg ride times rather than a
synthetic 候车 breakdown.

Stdlib only (urllib).  Requires an AK from the 百度地图开放平台:
set ``BAIDU_MAP_AK`` or pass ``--ak``.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass

from ..model import fmt_hhmm

BASE = "https://api.map.baidu.com"
_VEHICLE_TYPE = {0: "公交", 1: "地铁", 2: "火车", 3: "飞机", 4: "轮船"}


class BaiduError(Exception):
    """Raised on missing AK, network failure, or a non-zero Baidu status."""


@dataclass
class OnlineLeg:
    mode: str          # "transit" | "walk"
    vehicle: str       # "地铁" / "公交" / "步行" ...
    line: str          # line name for transit, "" for walking
    board: str
    alight: str
    stops: int
    minutes: float
    meters: float
    board_time: float | None = None    # absolute minutes, if a depart base is given
    alight_time: float | None = None


@dataclass
class OnlineItinerary:
    provider: str
    origin: str
    dest: str
    total_minutes: float
    walk_minutes: float
    walk_meters: float
    price: float
    legs: list[OnlineLeg]
    depart: float | None = None
    arrive: float | None = None

    @property
    def num_transfers(self) -> int:
        return max(0, sum(1 for l in self.legs if l.mode == "transit") - 1)

    def to_dict(self) -> dict:
        d = {
            "provider": self.provider,
            "origin": self.origin,
            "dest": self.dest,
            "total_minutes": round(self.total_minutes, 1),
            "walk_minutes": round(self.walk_minutes, 1),
            "walk_meters": round(self.walk_meters),
            "price_yuan": self.price,
            "num_transfers": self.num_transfers,
            "legs": [
                {**asdict(l),
                 "minutes": round(l.minutes, 1),
                 "meters": round(l.meters),
                 "board_time": fmt_hhmm(l.board_time) if l.board_time is not None else None,
                 "alight_time": fmt_hhmm(l.alight_time) if l.alight_time is not None else None}
                for l in self.legs
            ],
        }
        if self.depart is not None:
            d["depart"] = fmt_hhmm(self.depart)
            d["arrive"] = fmt_hhmm(self.arrive)
        return d


class BaiduProvider:
    def __init__(self, ak: str | None = None, city: str = "上海", timeout: int = 8):
        self.ak = ak or os.environ.get("BAIDU_MAP_AK") or os.environ.get("BAIDU_MAP_API_KEY")
        if not self.ak:
            raise BaiduError("缺少百度地图 AK：请设置环境变量 BAIDU_MAP_AK 或使用 --ak 传入。")
        self.city = city
        self.timeout = timeout
        self._geo_cache: dict[tuple[str, str], tuple[float, float]] = {}

    # -- low-level HTTP -----------------------------------------------------
    def _get(self, path: str, params: dict) -> dict:
        q = urllib.parse.urlencode({**params, "ak": self.ak, "output": "json"})
        url = f"{BASE}{path}?{q}"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:                      # network / parse errors
            raise BaiduError(f"请求百度接口失败：{e}") from e
        if data.get("status") != 0:
            raise BaiduError(
                f"百度接口返回错误：{data.get('message')} (status={data.get('status')})"
            )
        return data

    # -- station name -> BD-09 coordinate -----------------------------------
    def geocode(self, station: str, city: str | None = None) -> tuple[float, float]:
        city = city or self.city
        key = (station, city)
        if key in self._geo_cache:
            return self._geo_cache[key]
        for query in (f"{station}地铁站", station):
            data = self._get("/place/v2/search",
                             {"query": query, "region": city, "city_limit": "true"})
            results = data.get("results") or []
            if results:
                loc = results[0]["location"]
                latlng = (loc["lat"], loc["lng"])
                self._geo_cache[key] = latlng
                return latlng
        raise BaiduError(f"找不到车站坐标：{station}（{city}）")

    # -- plan ---------------------------------------------------------------
    def plan(self, origin: str, dest: str, depart: float | None = None,
             city: str | None = None) -> OnlineItinerary | None:
        city = city or self.city
        o_lat, o_lng = self.geocode(origin, city)
        d_lat, d_lng = self.geocode(dest, city)
        data = self._get("/directionlite/v1/transit", {
            "origin": f"{o_lat:.6f},{o_lng:.6f}",
            "destination": f"{d_lat:.6f},{d_lng:.6f}",
            "steps_info": "1",
        })
        routes = (data.get("result") or {}).get("routes") or []
        if not routes:
            return None
        return self._to_itinerary(origin, dest, routes[0], depart)

    # -- response normalization ---------------------------------------------
    @staticmethod
    def _flatten_steps(steps: list) -> list[dict]:
        """Baidu nests steps as a list-of-lists in some responses; flatten it."""
        flat: list[dict] = []
        for s in steps:
            if isinstance(s, list):
                flat.extend(x for x in s if isinstance(x, dict))
            elif isinstance(s, dict):
                flat.append(s)
        return flat

    def _to_itinerary(self, origin: str, dest: str, route: dict,
                      depart: float | None) -> OnlineItinerary:
        total_min = route.get("duration", 0) / 60.0
        legs: list[OnlineLeg] = []
        walk_min = 0.0
        walk_m = 0.0
        clock = depart

        for step in self._flatten_steps(route.get("steps", [])):
            minutes = step.get("duration", 0) / 60.0
            meters = step.get("distance", 0)
            v = step.get("vehicle") or {}
            board_t = clock
            if clock is not None:
                clock = clock + minutes
            if v.get("name"):                       # transit segment
                legs.append(OnlineLeg(
                    mode="transit",
                    vehicle=_VEHICLE_TYPE.get(v.get("type"), "公交"),
                    line=v.get("name", ""),
                    board=v.get("start_name", ""),
                    alight=v.get("end_name", ""),
                    stops=v.get("stop_num", 0),
                    minutes=minutes, meters=meters,
                    board_time=board_t, alight_time=clock,
                ))
            else:                                   # walking segment
                walk_min += minutes
                walk_m += meters
                legs.append(OnlineLeg(
                    mode="walk", vehicle="步行", line="", board="", alight="",
                    stops=0, minutes=minutes, meters=meters,
                    board_time=board_t, alight_time=clock,
                ))

        arrive = (depart + total_min) if depart is not None else None
        return OnlineItinerary(
            provider="baidu", origin=origin, dest=dest,
            total_minutes=total_min, walk_minutes=walk_min, walk_meters=walk_m,
            price=route.get("price", 0), legs=legs, depart=depart, arrive=arrive,
        )


def render_online(it: OnlineItinerary) -> str:
    lines = [
        f"🚇 从【{it.origin}】到【{it.dest}】  · 百度地图实时方案",
        f"   全程约 {round(it.total_minutes)} 分钟"
        f"（含步行 {round(it.walk_minutes)} 分 / {round(it.walk_meters)} 米，"
        f"换乘 {it.num_transfers} 次"
        + (f"，票价 {it.price} 元" if it.price else "") + "）",
    ]
    if it.depart is not None:
        lines.append(f"   ETA：以 {fmt_hhmm(it.depart)} 出发估算约 {fmt_hhmm(it.arrive)} 到达"
                     f"（实际发车以百度实时为准）")
    lines.append("")
    for leg in it.legs:
        clock = f"{fmt_hhmm(leg.board_time)} " if leg.board_time is not None else ""
        if leg.mode == "walk":
            lines.append(f"  🚶 {clock}步行 {round(leg.minutes)} 分（{round(leg.meters)} 米）")
        else:
            lines.append(
                f"  🚆 {clock}乘 {leg.line}：{leg.board} → {leg.alight}"
                f"（{leg.stops} 站，约 {round(leg.minutes)} 分）"
            )
    lines.append("\n   注：百度的耗时已包含候车，未单独拆分每段候车时间。")
    return "\n".join(lines)
