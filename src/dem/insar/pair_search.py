# -*- coding: utf-8 -*-
"""
Поиск пар Sentinel-1 SLC для InSAR через ASF Search API.

Выход:
- JSON со сценами;
- JSON с кандидатами пар (один path/frame, одна полоса, одна поляризация);
- Markdown-таблица для отчёта.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

SRC_ROOT = Path(__file__).resolve().parents[2]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from dem.ingest.asf_slc import SlcScene, build_slc_pairs, fetch_slc_scenes
from dem.config import DEFAULT_REGION, REGIONS
from dem.io.layout import insar_dir, resolve_out_dir


def _write_md(path: Path, *, region_key: str, date_from: str, date_to: str, scenes: list[SlcScene], pairs: list[dict]) -> None:
    known_baselines = sum(1 for pair in pairs if pair.get("perpendicular_baseline_m") is not None)
    lines = [
        f"# Sentinel-1 SLC pairs: {region_key}",
        "",
        f"- period: `{date_from} .. {date_to}`",
        f"- scenes: `{len(scenes)}`",
        f"- pairs: `{len(pairs)}`",
        f"- pairs_with_perpendicular_baseline: `{known_baselines}`",
        f"- report_time_utc: `{datetime.now(timezone.utc).isoformat()}`",
        "",
        "## Pairs",
        "",
        "| master | slave | dt_days | bperp_m | baseline_status | score | path | frame | orbit | pol |",
        "| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | --- | --- |",
    ]
    for p in pairs[:100]:
        bperp = p.get("perpendicular_baseline_m")
        bperp_s = "" if bperp is None else f"{float(bperp):.1f}"
        score = p.get("pair_score")
        score_s = "" if score is None else f"{float(score):.3f}"
        lines.append(
            f"| `{p['master_time']}` | `{p['slave_time']}` | {p['temporal_baseline_days']} | "
            f"{bperp_s} | {p.get('baseline_status', '')} | {score_s} | "
            f"{p['path_number']} | {p['frame_number']} | {p['flight_direction']} | {p['polarization']} |"
        )
    if len(pairs) > 100:
        lines.append("")
        lines.append(f"_... trimmed, total pairs: {len(pairs)}_")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description="Поиск Sentinel-1 SLC пар для InSAR.")
    p.add_argument("--region", type=str, default=DEFAULT_REGION, choices=sorted(REGIONS.keys()))
    p.add_argument("--date-from", type=str, required=True, help="YYYY-MM-DD")
    p.add_argument("--date-to", type=str, required=True, help="YYYY-MM-DD")
    p.add_argument("--min-days", type=int, default=6, help="Минимальный временной базис пары, дни.")
    p.add_argument("--max-days", type=int, default=24, help="Максимальный временной базис пары, дни.")
    p.add_argument("--target-days", type=float, default=12.0, help="Желаемый временной базис для ранжирования, дни.")
    p.add_argument(
        "--min-perp-baseline",
        type=float,
        default=80.0,
        help="Нижняя граница перпендикулярного baseline для DEM-кандидата, м.",
    )
    p.add_argument(
        "--max-perp-baseline",
        type=float,
        default=450.0,
        help="Верхняя граница перпендикулярного baseline для DEM-кандидата, м.",
    )
    p.add_argument(
        "--require-perp-baseline",
        action="store_true",
        help="Оставлять только пары с известным baseline внутри заданного диапазона.",
    )
    p.add_argument("--max-results", type=int, default=500)
    p.add_argument(
        "--out-dir",
        type=str,
        default="",
        help="База для прогона; пусто = outputs/<дата>/insar/slc_pairs.",
    )
    args = p.parse_args()

    region = REGIONS[args.region]
    out_dir = resolve_out_dir(args.out_dir, lambda: insar_dir() / "slc_pairs")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = out_dir / f"{args.region}_{args.date_from}_{args.date_to}_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    scenes = fetch_slc_scenes(
        region=region,
        date_from=args.date_from,
        date_to=args.date_to,
        max_results=args.max_results,
        beam_mode="IW",
    )
    pairs = build_slc_pairs(
        scenes,
        min_days=args.min_days,
        max_days=args.max_days,
        min_perpendicular_baseline_m=args.min_perp_baseline,
        max_perpendicular_baseline_m=args.max_perp_baseline,
        target_temporal_baseline_days=args.target_days,
        require_perpendicular_baseline=args.require_perp_baseline,
    )

    scenes_json = run_dir / "scenes.json"
    pairs_json = run_dir / "pairs.json"
    pairs_md = run_dir / "pairs.md"
    scenes_json.write_text(json.dumps([s.__dict__ for s in scenes], ensure_ascii=False, indent=2), encoding="utf-8")
    pairs_json.write_text(json.dumps(pairs, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_md(pairs_md, region_key=args.region, date_from=args.date_from, date_to=args.date_to, scenes=scenes, pairs=pairs)

    print(f"SLC scenes: {len(scenes)}")
    print(f"SLC pairs: {len(pairs)}")
    known_baselines = sum(1 for pair in pairs if pair.get("perpendicular_baseline_m") is not None)
    print(f"Pairs with perpendicular baseline: {known_baselines}/{len(pairs)}")
    print(f"Run dir: {run_dir}")
    if pairs and known_baselines == 0:
        print(
            "Warning: ASF response did not include perpendicular baseline values; "
            "treat this list as temporal/same-track preselection and validate Bperp in SNAP before downloading many ZIPs."
        )
    if pairs:
        top = pairs[0]
        if known_baselines == 0:
            print("First candidate (temporal/same-track preselection only):")
        else:
            print("Best pair (DEM ranking):")
        print(f"  master: {top['master_id']}")
        print(f"  slave:  {top['slave_id']}")
        print(f"  dt_days: {top['temporal_baseline_days']}")
        print(f"  bperp_m: {top.get('perpendicular_baseline_m')}")
        print(f"  baseline_status: {top.get('baseline_status')}")
        print(f"  score: {top.get('pair_score')}")
        if known_baselines == 0:
            print("  note: score includes an unknown-baseline penalty and must not be treated as DEM quality.")


if __name__ == "__main__":
    main()
