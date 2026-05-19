# -*- coding: utf-8 -*-
"""
Подбор набора InSAR-пар по региону с ограничением суммарного объёма скачиваемых SLC.

ASF Search отдаёт ``sizeMB`` только для ``output=json`` (см. ``fetch_slc_scenes``).
Sentinel-1 реально доступен с апреля 2014; более ранние даты автоматически поднимаются до 2014-04-01.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from dem.config import DEFAULT_REGION, REGIONS
from dem.ingest.asf_slc import SlcScene, build_slc_pairs, fetch_slc_scenes_yearly


SENTINEL1_START = date(2014, 4, 1)


def _parse_date(d: str) -> date:
    y, m, dd = (int(x) for x in d.split("-", 2))
    return date(y, m, dd)


def _clamp_sentinel_dates(date_from: str, date_to: str) -> tuple[str, str, list[str]]:
    notes: list[str] = []
    a = _parse_date(date_from)
    b = _parse_date(date_to)
    if b < SENTINEL1_START:
        notes.append("Дата окончания раньше начала миссии Sentinel-1: результат будет пустым.")
    if a < SENTINEL1_START:
        notes.append(f"Дата начала поднята с {date_from} до {SENTINEL1_START.isoformat()} (запуск Sentinel-1).")
        a = SENTINEL1_START
    if b < a:
        b = a
    return a.isoformat(), b.isoformat(), notes


def _filter_iw_vv(scenes: list[SlcScene]) -> list[SlcScene]:
    out: list[SlcScene] = []
    for s in scenes:
        if (s.beam_mode or "").upper() != "IW":
            continue
        pol = (s.polarization or "").upper()
        if "VV" not in pol:
            continue
        out.append(s)
    return out


def _scene_download_bytes(s: SlcScene, *, default_size_mb: float) -> int:
    mb = float(s.size_mb) if s.size_mb is not None else float(default_size_mb)
    return int(mb * 1024 * 1024)


def _scene_year(s: SlcScene) -> int:
    return int(s.start_time[:4])


def _pair_master_year(p: dict) -> int:
    return int(str(p["master_time"])[:4])


def _evenly_spaced(items: list[dict], limit: int) -> list[dict]:
    if limit <= 0 or not items:
        return []
    if len(items) <= limit:
        return list(items)
    if limit == 1:
        return [items[0]]
    indexes = [round(i * (len(items) - 1) / (limit - 1)) for i in range(limit)]
    out: list[dict] = []
    seen: set[int] = set()
    for idx in indexes:
        if idx in seen:
            continue
        seen.add(idx)
        out.append(items[idx])
    return out


def _sum_download_bytes(scenes: list[SlcScene], *, default_size_mb: float) -> int:
    return sum(_scene_download_bytes(s, default_size_mb=default_size_mb) for s in scenes)


def select_pairs_under_budget(
    scenes: list[SlcScene],
    *,
    min_days: int,
    max_days: int,
    target_days: float = 12.0,
    min_perp_baseline: float = 80.0,
    max_perp_baseline: float = 450.0,
    require_perp_baseline: bool = False,
    budget_gb: float,
    default_size_mb: float,
) -> tuple[list[dict], int, list[SlcScene]]:
    """Жадный выбор пар: суммарный объём уникальных сцен ≤ ``budget_gb`` (GiB)."""

    usable = _filter_iw_vv(scenes)
    by_id = {s.file_id: s for s in usable}
    pairs = build_slc_pairs(
        usable,
        min_days=min_days,
        max_days=max_days,
        target_temporal_baseline_days=target_days,
        min_perpendicular_baseline_m=min_perp_baseline,
        max_perpendicular_baseline_m=max_perp_baseline,
        require_perpendicular_baseline=require_perp_baseline,
    )
    budget_b = int(budget_gb * (1024**3))
    used: set[str] = set()
    total_b = 0
    chosen: list[dict] = []
    for p in pairs:
        mids = (p["master_id"], p["slave_id"])
        add = 0
        for fid in mids:
            if fid not in used:
                sc = by_id.get(fid)
                if sc is None:
                    add = budget_b + 1
                    break
                add += _scene_download_bytes(sc, default_size_mb=default_size_mb)
        if total_b + add <= budget_b:
            chosen.append(p)
            for fid in mids:
                if fid not in used and fid in by_id:
                    used.add(fid)
                    total_b += _scene_download_bytes(by_id[fid], default_size_mb=default_size_mb)
    uniq_scenes = [by_id[i] for i in sorted(used)]
    return chosen, total_b, uniq_scenes


def select_yearly_scenes_from_pairs(
    scenes: list[SlcScene],
    *,
    year_from: int,
    year_to: int,
    scenes_per_year: int,
    pairs_per_year: int,
    min_days: int,
    max_days: int,
    target_days: float = 12.0,
    min_perp_baseline: float = 80.0,
    max_perp_baseline: float = 450.0,
    require_perp_baseline: bool = False,
    default_size_mb: float,
) -> tuple[list[dict], int, list[SlcScene], list[dict]]:
    """Выбрать до N уникальных SLC-сцен на год из равномерно распределённых пар."""

    usable = _filter_iw_vv(scenes)
    by_id = {s.file_id: s for s in usable}
    pairs = build_slc_pairs(
        usable,
        min_days=min_days,
        max_days=max_days,
        target_temporal_baseline_days=target_days,
        min_perpendicular_baseline_m=min_perp_baseline,
        max_perpendicular_baseline_m=max_perp_baseline,
        require_perpendicular_baseline=require_perp_baseline,
    )
    pairs_by_year: dict[int, list[dict]] = {y: [] for y in range(year_from, year_to + 1)}
    for pair in pairs:
        y = _pair_master_year(pair)
        if year_from <= y <= year_to:
            pairs_by_year.setdefault(y, []).append(pair)

    selected_pairs: list[dict] = []
    selected_ids_global: set[str] = set()
    year_summaries: list[dict] = []
    for y in range(year_from, year_to + 1):
        year_pairs = sorted(pairs_by_year.get(y, []), key=lambda p: (p["master_time"], p["slave_time"]))
        candidate_pairs = _evenly_spaced(year_pairs, pairs_per_year)
        selected_ids_year: set[str] = set()
        selected_pairs_year: list[dict] = []
        for pair in candidate_pairs:
            pair_ids = {pair["master_id"], pair["slave_id"]}
            if len(selected_ids_year | pair_ids) > scenes_per_year:
                continue
            selected_pairs_year.append(pair)
            selected_ids_year.update(pair_ids)
            selected_ids_global.update(pair_ids)
            if len(selected_ids_year) >= scenes_per_year:
                break
        selected_pairs.extend(selected_pairs_year)
        year_summaries.append(
            {
                "year": y,
                "candidate_pair_count": len(year_pairs),
                "sampled_pair_count": len(candidate_pairs),
                "selected_pair_count": len(selected_pairs_year),
                "selected_scene_count": len(selected_ids_year),
            }
        )

    uniq_scenes = sorted((by_id[i] for i in selected_ids_global if i in by_id), key=lambda s: (s.start_time, s.file_id))
    total_b = _sum_download_bytes(uniq_scenes, default_size_mb=default_size_mb)
    return selected_pairs, total_b, uniq_scenes, year_summaries


def apply_scene_budget_to_pairs(
    pairs: list[dict],
    scenes: list[SlcScene],
    *,
    budget_gb: float,
    default_size_mb: float,
) -> tuple[list[dict], int, list[SlcScene]]:
    """Оставить пары, пока объём уникальных сцен не превысит бюджет."""

    if budget_gb <= 0:
        total_b = _sum_download_bytes(scenes, default_size_mb=default_size_mb)
        return pairs, total_b, scenes

    by_id = {s.file_id: s for s in scenes}
    budget_b = int(budget_gb * (1024**3))
    used: set[str] = set()
    selected_pairs: list[dict] = []
    total_b = 0
    for pair in pairs:
        ids = (pair["master_id"], pair["slave_id"])
        add_b = 0
        missing = False
        for fid in ids:
            if fid in used:
                continue
            scene = by_id.get(fid)
            if scene is None:
                missing = True
                break
            add_b += _scene_download_bytes(scene, default_size_mb=default_size_mb)
        if missing:
            continue
        if total_b + add_b > budget_b:
            continue
        selected_pairs.append(pair)
        for fid in ids:
            if fid in used:
                continue
            used.add(fid)
            total_b += _scene_download_bytes(by_id[fid], default_size_mb=default_size_mb)

    selected_scenes = sorted((by_id[i] for i in used if i in by_id), key=lambda s: (s.start_time, s.file_id))
    return selected_pairs, total_b, selected_scenes


def main() -> None:
    p = argparse.ArgumentParser(description="План SLC-пар под бюджет диска (ASF).")
    p.add_argument(
        "--strategy",
        type=str,
        default="budget",
        choices=["budget", "yearly"],
        help="budget: старый отбор под объём; yearly: до N уникальных SLC-сцен на каждый год.",
    )
    p.add_argument("--region", type=str, default=DEFAULT_REGION, choices=sorted(REGIONS.keys()))
    p.add_argument("--date-from", type=str, default="2010-01-01")
    p.add_argument("--date-to", type=str, default="2025-12-31")
    p.add_argument("--budget-gb", type=float, default=200.0, help="Максимум суммарного объёма уникальных ZIP, ГиБ.")
    p.add_argument(
        "--enforce-budget",
        action="store_true",
        help="Применить --budget-gb к итоговому manifest; особенно полезно для --strategy yearly.",
    )
    p.add_argument("--year-from", type=int, default=2014, help="Первый год для --strategy yearly.")
    p.add_argument("--year-to", type=int, default=2026, help="Последний год для --strategy yearly.")
    p.add_argument("--scenes-per-year", type=int, default=10, help="Максимум уникальных SLC-сцен на год для yearly.")
    p.add_argument("--pairs-per-year", type=int, default=30, help="Сколько пар равномерно пробовать внутри года для yearly.")
    p.add_argument("--min-days", type=int, default=6)
    p.add_argument("--max-days", type=int, default=36)
    p.add_argument("--target-days", type=float, default=12.0)
    p.add_argument("--min-perp-baseline", type=float, default=80.0)
    p.add_argument("--max-perp-baseline", type=float, default=450.0)
    p.add_argument(
        "--require-perp-baseline",
        action="store_true",
        help="Оставлять только пары с известным baseline внутри заданного диапазона.",
    )
    p.add_argument("--max-per-year", type=int, default=4000, help="ASF maxResults на каждый календарный год.")
    p.add_argument("--default-size-mb", type=float, default=4200.0, help="Если ASF не дал sizeMB для сцены.")
    p.add_argument("--out", type=str, required=True, help="Путь к manifest.json для sar_slc_download --from-manifest.")
    args = p.parse_args()

    region_key = args.region
    region = REGIONS[region_key]
    df, dt, warnings = _clamp_sentinel_dates(args.date_from, args.date_to)

    scenes = fetch_slc_scenes_yearly(
        region=region,
        date_from=df,
        date_to=dt,
        max_results_per_chunk=args.max_per_year,
        beam_mode="IW",
    )
    yearly_summary: list[dict] = []
    if args.strategy == "yearly":
        y_from = max(args.year_from, _parse_date(df).year)
        y_to = min(args.year_to, _parse_date(dt).year)
        pairs_sel, total_b, uniq, yearly_summary = select_yearly_scenes_from_pairs(
            scenes,
            year_from=y_from,
            year_to=y_to,
            scenes_per_year=args.scenes_per_year,
            pairs_per_year=args.pairs_per_year,
            min_days=args.min_days,
            max_days=args.max_days,
            target_days=args.target_days,
            min_perp_baseline=args.min_perp_baseline,
            max_perp_baseline=args.max_perp_baseline,
            require_perp_baseline=args.require_perp_baseline,
            default_size_mb=args.default_size_mb,
        )
        if args.enforce_budget:
            pairs_sel, total_b, uniq = apply_scene_budget_to_pairs(
                pairs_sel,
                uniq,
                budget_gb=args.budget_gb,
                default_size_mb=args.default_size_mb,
            )
            selected_by_year: dict[int, set[str]] = {}
            pair_count_by_year: dict[int, int] = {}
            for scene in uniq:
                selected_by_year.setdefault(_scene_year(scene), set()).add(scene.file_id)
            for pair in pairs_sel:
                y = _pair_master_year(pair)
                pair_count_by_year[y] = pair_count_by_year.get(y, 0) + 1
            for row in yearly_summary:
                y = int(row["year"])
                row["selected_scene_count_after_budget"] = len(selected_by_year.get(y, set()))
                row["selected_pair_count_after_budget"] = pair_count_by_year.get(y, 0)
    else:
        pairs_sel, total_b, uniq = select_pairs_under_budget(
            scenes,
            min_days=args.min_days,
            max_days=args.max_days,
            target_days=args.target_days,
            min_perp_baseline=args.min_perp_baseline,
            max_perp_baseline=args.max_perp_baseline,
            require_perp_baseline=args.require_perp_baseline,
            budget_gb=args.budget_gb,
            default_size_mb=args.default_size_mb,
        )
    known_pair_baselines = sum(1 for pair in pairs_sel if pair.get("perpendicular_baseline_m") is not None)

    manifest = {
        "region": region_key,
        "strategy": args.strategy,
        "date_from": df,
        "date_to": dt,
        "requested_date_from": args.date_from,
        "requested_date_to": args.date_to,
        "budget_gb": args.budget_gb,
        "selection": {
            "min_days": args.min_days,
            "max_days": args.max_days,
            "target_days": args.target_days,
            "min_perp_baseline_m": args.min_perp_baseline,
            "max_perp_baseline_m": args.max_perp_baseline,
            "require_perp_baseline": args.require_perp_baseline,
            "pairs_with_perpendicular_baseline": known_pair_baselines,
            "year_from": args.year_from,
            "year_to": args.year_to,
            "scenes_per_year": args.scenes_per_year,
            "pairs_per_year": args.pairs_per_year,
            "enforce_budget": args.enforce_budget,
        },
        "estimated_download_bytes": total_b,
        "estimated_download_gib": round(total_b / (1024**3), 3),
        "pair_count": len(pairs_sel),
        "unique_scene_count": len(uniq),
        "warnings": warnings,
        "yearly_summary": yearly_summary,
        "pairs": pairs_sel,
        "scenes": [s.__dict__ for s in uniq],
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Scenes indexed (IW, dedup): {len(scenes)}")
    print(f"Pairs selected: {len(pairs_sel)}  ·  unique SLC: {len(uniq)}")
    if yearly_summary:
        print("Yearly selection:")
        for row in yearly_summary:
            print(
                f"  {row['year']}: scenes={row['selected_scene_count']}/{args.scenes_per_year}, "
                f"pairs={row['selected_pair_count']}, candidates={row['candidate_pair_count']}"
            )
    print(f"Pairs with perpendicular baseline: {known_pair_baselines}/{len(pairs_sel)}")
    if pairs_sel and known_pair_baselines == 0:
        print(
            "Warning: ASF response did not include perpendicular baseline values; "
            "validate Bperp in SNAP before bulk downloading to SSD."
        )
    budget_note = "enforced" if args.enforce_budget else "not enforced"
    print(f"Estimated size: {manifest['estimated_download_gib']} GiB  (budget {args.budget_gb} GiB, {budget_note})")
    print(f"Wrote {out_path}")
    for w in warnings:
        print(f"Note: {w}")


if __name__ == "__main__":
    main()
