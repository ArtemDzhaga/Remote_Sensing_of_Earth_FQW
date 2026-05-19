# -*- coding: utf-8 -*-
"""Поиск сцен Sentinel-1 SLC через ASF Search API (общая логика для пар и загрузки)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

ASF_SEARCH_URL = "https://api.daac.asf.alaska.edu/services/search/param"


@dataclass
class SlcScene:
    file_id: str
    start_time: str
    stop_time: str
    platform: str
    flight_direction: str
    path_number: int
    frame_number: int
    polarization: str
    beam_mode: str
    download_url: str
    size_mb: float | None = None
    absolute_orbit: int | None = None
    perpendicular_baseline_m: float | None = None


def iso_to_dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def bbox_to_wkt_polygon(region: dict) -> str:
    w, s, e, n = region["west"], region["south"], region["east"], region["north"]
    return f"POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))"


def _orbit_path_number(p: dict[str, Any]) -> int:
    for k in ("pathNumber", "relativeOrbit", "track"):
        v = p.get(k)
        if v is None or v == "":
            continue
        try:
            return int(v)
        except (TypeError, ValueError):
            continue
    return -1


def _frame_number(p: dict[str, Any]) -> int:
    for k in ("frameNumber", "firstFrame", "finalFrame"):
        v = p.get(k)
        if v is None or v == "":
            continue
        try:
            return int(v)
        except (TypeError, ValueError):
            continue
    return -1


def _int_field(p: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for k in keys:
        v = p.get(k)
        if v is None or v == "":
            continue
        try:
            return int(v)
        except (TypeError, ValueError):
            continue
    return None


def _float_field(p: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for k in keys:
        v = p.get(k)
        if v is None or v == "":
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _scene_from_json_row(p: dict[str, Any]) -> SlcScene | None:
    fid = p.get("product_file_id") or p.get("fileID") or p.get("sceneId") or p.get("granuleName")
    url = p.get("downloadUrl") or p.get("url") or ""
    if not fid or not url:
        return None
    try:
        sz = p.get("sizeMB")
        size_mb = float(sz) if sz is not None else None
    except (TypeError, ValueError):
        size_mb = None
    try:
        return SlcScene(
            file_id=str(fid),
            start_time=str(p.get("startTime", "")),
            stop_time=str(p.get("stopTime", "")),
            platform=str(p.get("platform", "")),
            flight_direction=str(p.get("flightDirection", "")),
            path_number=_orbit_path_number(p),
            frame_number=_frame_number(p),
            polarization=str(p.get("polarization", "")),
            beam_mode=str(p.get("beamModeType") or p.get("beamMode") or ""),
            download_url=str(url),
            size_mb=size_mb,
            absolute_orbit=_int_field(p, ("absoluteOrbit", "absoluteOrbitNumber", "orbit")),
            perpendicular_baseline_m=_float_field(
                p,
                (
                    "perpendicularBaseline",
                    "perpendicularBaselineMeters",
                    "perpendicularBaseline_m",
                    "perpendicular_baseline",
                    "baselinePerpendicular",
                    "bperp",
                ),
            ),
        )
    except Exception:
        return None


def fetch_slc_scenes(
    *,
    region: dict,
    date_from: str,
    date_to: str,
    max_results: int,
    beam_mode: str | None = None,
    timeout_sec: int = 180,
    retries: int = 3,
    retry_delay_sec: float = 5.0,
) -> list[SlcScene]:
    params: dict[str, str] = {
        "platform": "SENTINEL-1A,SENTINEL-1B,SENTINEL-1C",
        "processingLevel": "SLC",
        "intersectsWith": bbox_to_wkt_polygon(region),
        "start": f"{date_from}T00:00:00Z",
        "end": f"{date_to}T23:59:59Z",
        "output": "json",
        "maxResults": str(max_results),
    }
    if beam_mode:
        params["beamMode"] = beam_mode
    last_err: Exception | None = None
    data: Any = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(ASF_SEARCH_URL, params=params, timeout=timeout_sec)
            r.raise_for_status()
            data = r.json()
            last_err = None
            break
        except Exception as e:
            last_err = e
            if attempt < retries:
                import time

                time.sleep(retry_delay_sec)
            else:
                raise last_err
    rows: list[dict[str, Any]] = []
    if isinstance(data, list):
        if data and isinstance(data[0], list):
            rows = data[0]
        elif data and isinstance(data[0], dict):
            rows = data  # type: ignore[assignment]
    scenes: list[SlcScene] = []
    for p in rows:
        if not isinstance(p, dict):
            continue
        s = _scene_from_json_row(p)
        if s:
            scenes.append(s)
    scenes.sort(key=lambda x: x.start_time)
    return scenes


def fetch_slc_scenes_yearly(
    *,
    region: dict,
    date_from: str,
    date_to: str,
    max_results_per_chunk: int,
    beam_mode: str | None = "IW",
) -> list[SlcScene]:
    """Несколько запросов ASF по годам (лимит ``maxResults`` действует на каждый интервал)."""

    from datetime import date as date_cls

    def _parse(d: str) -> date_cls:
        y, m, dd = (int(x) for x in d.split("-", 2))
        return date_cls(y, m, dd)

    a = _parse(date_from)
    b = _parse(date_to)
    if b < a:
        return []
    scenes_by_id: dict[str, SlcScene] = {}
    y = a.year
    while y <= b.year:
        chunk_a = date_cls(y, 1, 1)
        if chunk_a < a:
            chunk_a = a
        chunk_b = date_cls(y, 12, 31)
        if chunk_b > b:
            chunk_b = b
        part = fetch_slc_scenes(
            region=region,
            date_from=chunk_a.isoformat(),
            date_to=chunk_b.isoformat(),
            max_results=max_results_per_chunk,
            beam_mode=beam_mode,
        )
        for s in part:
            scenes_by_id[s.file_id] = s
        y += 1
    return sorted(scenes_by_id.values(), key=lambda s: s.start_time)


def _pair_perpendicular_baseline_m(master: SlcScene, slave: SlcScene) -> float | None:
    if master.perpendicular_baseline_m is None or slave.perpendicular_baseline_m is None:
        return None
    return abs(slave.perpendicular_baseline_m - master.perpendicular_baseline_m)


def _baseline_status(bperp_m: float | None, *, min_m: float, max_m: float) -> str:
    if bperp_m is None:
        return "unknown"
    if bperp_m < min_m:
        return "too_small"
    if bperp_m > max_m:
        return "too_large"
    return "ok"


def _pair_score(
    *,
    temporal_baseline_days: float,
    perpendicular_baseline_m: float | None,
    min_perpendicular_baseline_m: float,
    max_perpendicular_baseline_m: float,
    target_temporal_baseline_days: float,
) -> float:
    temporal_target = max(float(target_temporal_baseline_days), 1.0)
    temporal_score = abs(temporal_baseline_days - temporal_target) / temporal_target
    if perpendicular_baseline_m is None:
        baseline_score = 2.0
    elif perpendicular_baseline_m < min_perpendicular_baseline_m:
        baseline_score = 1.0 + (min_perpendicular_baseline_m - perpendicular_baseline_m) / max(
            min_perpendicular_baseline_m, 1.0
        )
    elif perpendicular_baseline_m > max_perpendicular_baseline_m:
        baseline_score = 1.0 + (perpendicular_baseline_m - max_perpendicular_baseline_m) / max(
            max_perpendicular_baseline_m, 1.0
        )
    else:
        baseline_score = 0.0
    return round(temporal_score + 2.0 * baseline_score, 6)


def build_slc_pairs(
    scenes: list[SlcScene],
    min_days: int,
    max_days: int,
    *,
    min_perpendicular_baseline_m: float = 0.0,
    max_perpendicular_baseline_m: float = 1_000_000.0,
    target_temporal_baseline_days: float = 12.0,
    require_perpendicular_baseline: bool = False,
) -> list[dict]:
    pairs: list[dict] = []
    groups: dict[tuple, list[SlcScene]] = {}
    for s in scenes:
        key = (s.path_number, s.frame_number, s.flight_direction, s.polarization, s.beam_mode)
        groups.setdefault(key, []).append(s)

    for key, group in groups.items():
        group.sort(key=lambda x: x.start_time)
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                m = group[i]
                sl = group[j]
                dt_days = (iso_to_dt(sl.start_time) - iso_to_dt(m.start_time)).total_seconds() / 86400.0
                if dt_days < min_days or dt_days > max_days:
                    continue
                bperp_m = _pair_perpendicular_baseline_m(m, sl)
                status = _baseline_status(
                    bperp_m,
                    min_m=min_perpendicular_baseline_m,
                    max_m=max_perpendicular_baseline_m,
                )
                if require_perpendicular_baseline and status != "ok":
                    continue
                score = _pair_score(
                    temporal_baseline_days=dt_days,
                    perpendicular_baseline_m=bperp_m,
                    min_perpendicular_baseline_m=min_perpendicular_baseline_m,
                    max_perpendicular_baseline_m=max_perpendicular_baseline_m,
                    target_temporal_baseline_days=target_temporal_baseline_days,
                )
                pairs.append(
                    {
                        "master_id": m.file_id,
                        "slave_id": sl.file_id,
                        "master_time": m.start_time,
                        "slave_time": sl.start_time,
                        "temporal_baseline_days": round(dt_days, 3),
                        "master_perpendicular_baseline_m": m.perpendicular_baseline_m,
                        "slave_perpendicular_baseline_m": sl.perpendicular_baseline_m,
                        "perpendicular_baseline_m": None if bperp_m is None else round(bperp_m, 3),
                        "baseline_status": status,
                        "pair_score": score,
                        "path_number": key[0],
                        "frame_number": key[1],
                        "flight_direction": key[2],
                        "polarization": key[3],
                        "beam_mode": key[4],
                        "master_url": m.download_url,
                        "slave_url": sl.download_url,
                    }
                )
    status_rank = {"ok": 0, "unknown": 1, "too_small": 2, "too_large": 3}
    pairs.sort(
        key=lambda x: (
            status_rank.get(str(x.get("baseline_status")), 9),
            x.get("pair_score", 999.0),
            x["temporal_baseline_days"],
            x["master_time"],
        )
    )
    return pairs
