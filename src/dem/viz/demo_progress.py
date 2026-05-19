# -*- coding: utf-8 -*-
"""
Одна команда для демо по региону: эталонный DEM, SAR (RTC), отчёты.

Шаги:
1) опционально — эталонные DEM (OpenTopography);
2) опционально — Sentinel-1 RTC за месяц или за интервал дат;
3) 3D-отчёт по DEM (validate_dem);
4) совмещённый SAR vs DEM (viz_sar_dem_progress);
5) папка с timestamp и summary.md.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dem.config import DEFAULT_REGION, REGIONS  # noqa: E402
from dem.io.layout import (  # noqa: E402
    demo_runs_dir,
    iter_reference_dem_processed_bases_newest_first,
    iter_sar_run_roots_newest_first,
    resolve_out_dir,
)


def _run(cmd: list[str], *, env: dict | None = None) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0:
        raise RuntimeError(f"Command failed ({p.returncode}): {' '.join(cmd)}\n{out}")
    return out


def _extract_by_prefix(text: str, prefix: str) -> str | None:
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return None


def _pick_latest_dem(region: str, epsg: int) -> Path:
    import rasterio
    from rasterio.warp import transform_bounds

    cands_all: list[Path] = []
    for base in iter_reference_dem_processed_bases_newest_first():
        root = base / region
        if not root.is_dir():
            continue
        cands_all.extend([p for p in root.rglob(f"*epsg{epsg}*.tif") if p.is_file()])
    cands_all = sorted(cands_all, key=lambda p: p.stat().st_mtime, reverse=True)
    if not cands_all:
        raise RuntimeError(f"No DEM GeoTIFF for region={region} in reference_dem trees")

    target = REGIONS[region]
    t_w, t_s, t_e, t_n = target["west"], target["south"], target["east"], target["north"]

    def overlaps_region(p: Path) -> bool:
        try:
            with rasterio.open(p) as src:
                b = transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21)
            w, s, e, n = b
            if e <= t_w or w >= t_e or n <= t_s or s >= t_n:
                return False
            return True
        except Exception:
            return False

    cands = [p for p in cands_all if overlaps_region(p)]
    if not cands:
        raise RuntimeError("No DEM GeoTIFF overlapping region bbox in reference_dem trees")
    for p in cands:
        if "cop30" in p.name.lower():
            return p
    return cands[0]


def _pick_latest_sar_tif(region: str, *, month: str, date_from: str, date_to: str) -> Path:
    all_cands: list[Path] = []
    for root in iter_sar_run_roots_newest_first():
        if not root.is_dir():
            continue
        all_cands.extend(
            [p for p in root.rglob("scene_*/image.tif") if f"region={region}_" in p.as_posix()]
        )
    if date_from and date_to:
        tag = f"from={date_from}_to={date_to}"
        cands = [p for p in all_cands if tag in p.as_posix()]
    elif month:
        month_tag = f"from={month}-01_to={month}-"
        cands = [p for p in all_cands if month_tag in p.as_posix()]
    else:
        cands = all_cands
    cands = cands if cands else all_cands
    cands = sorted(cands, key=lambda p: p.stat().st_mtime, reverse=True)
    if not cands:
        raise RuntimeError(f"No SAR image.tif found for region={region}")
    return cands[0]


def _path_or_rel(p: Path, base: Path) -> str:
    try:
        return p.relative_to(base).as_posix()
    except ValueError:
        return p.as_posix()


def _period_label(month: str, date_from: str, date_to: str) -> str:
    if date_from and date_to:
        return f"{date_from}_{date_to}"
    if month:
        return month
    return "period"


def main() -> None:
    parser = argparse.ArgumentParser(description="Демо-ран: DEM + SAR (RTC) + отчёты.")
    parser.add_argument("--region", type=str, default=DEFAULT_REGION, choices=sorted(REGIONS.keys()))
    parser.add_argument("--month", type=str, default="", help="Месяц SAR: YYYY-MM (если не задан интервал дат).")
    parser.add_argument("--date-from", type=str, default="", help="Начало периода SAR: YYYY-MM-DD.")
    parser.add_argument("--date-to", type=str, default="", help="Конец периода SAR: YYYY-MM-DD.")
    parser.add_argument("--epsg", type=int, default=3857)
    parser.add_argument("--max-scenes", type=int, default=1)
    parser.add_argument("--skip-dem-download", action="store_true")
    parser.add_argument("--skip-sar-download", action="store_true")
    parser.add_argument("--sources", type=str, default="cop30,srtm30")
    parser.add_argument(
        "--out-root",
        type=str,
        default="",
        help="Корень демо-ранов; пусто = outputs/<дата>/demo_runs (VKR_RUN_DATE).",
    )
    args = parser.parse_args()

    if bool(args.date_from) ^ bool(args.date_to):
        parser.error("Задайте оба: --date-from и --date-to, либо ни одного.")

    if not args.skip_sar_download:
        if not (args.date_from and args.date_to) and not args.month:
            args.month = "2024-06"

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_base = resolve_out_dir(args.out_root, demo_runs_dir)
    run_dir = out_base / f"{args.region}_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    quality_dir = run_dir / "quality_report"
    progress_dir = run_dir / "progress_report"
    quality_dir.mkdir(parents=True, exist_ok=True)
    progress_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    period_label = _period_label(args.month, args.date_from, args.date_to)

    dem_manifest_path: Path | None = None
    if not args.skip_dem_download:
        out = _run(
            [
                sys.executable,
                "-m",
                "dem.ingest.reference_dem",
                "--region",
                args.region,
                "--sources",
                args.sources,
                "--epsg",
                str(args.epsg),
            ],
            env=env,
        )
        m = _extract_by_prefix(out, "Manifest:")
        if m:
            dem_manifest_path = Path(m)

    sar_run_dir: Path | None = None
    if not args.skip_sar_download:
        sar_cmd = [
            sys.executable,
            "-m",
            "dem.ingest.service",
            "stac",
            "download",
            "--region",
            args.region,
            "--limit",
            str(args.max_scenes),
            "--dst-epsg",
            str(args.epsg),
        ]
        if args.date_from and args.date_to:
            sar_cmd.extend(["--date-from", args.date_from, "--date-to", args.date_to])
        else:
            sar_cmd.extend(["--month", args.month])
        out = _run(sar_cmd, env=env)
        m = _extract_by_prefix(out, "Готово:")
        if m:
            sar_run_dir = Path(m)

    dem_tif: Path | None = None
    if dem_manifest_path and dem_manifest_path.is_file():
        data = json.loads(dem_manifest_path.read_text(encoding="utf-8"))
        layers = data.get("layers") or []
        for layer in layers:
            p = Path(layer.get("processed_path", ""))
            if "cop30" in p.name.lower() and p.is_file():
                dem_tif = p
                break
        if dem_tif is None and layers:
            p0 = Path(layers[0].get("processed_path", ""))
            if p0.is_file():
                dem_tif = p0
    if dem_tif is None:
        dem_tif = _pick_latest_dem(args.region, args.epsg)

    sar_tif: Path | None = None
    if sar_run_dir and sar_run_dir.exists():
        scene_tifs = sorted([p for p in sar_run_dir.rglob("scene_*/image.tif") if p.is_file()])
        if scene_tifs:
            sar_tif = scene_tifs[0]
    if sar_tif is None:
        sar_tif = _pick_latest_sar_tif(
            args.region,
            month=args.month,
            date_from=args.date_from,
            date_to=args.date_to,
        )

    _run(
        [
            sys.executable,
            "-m",
            "dem.viz.validate_dem",
            dem_tif.as_posix(),
            "--out-dir",
            quality_dir.as_posix(),
            "--region",
            args.region,
            "--period-label",
            period_label,
            "--subsample",
            "2",
            "--z-exag",
            "3.0",
        ],
        env=env,
    )

    progress_png = progress_dir / "sar_dem_progress.png"
    _run(
        [
            sys.executable,
            "-m",
            "dem.viz.progress",
            "--region",
            args.region,
            "--sar-tif",
            sar_tif.as_posix(),
            "--dem-tif",
            dem_tif.as_posix(),
            "--epsg",
            str(args.epsg),
            "--out",
            progress_png.as_posix(),
        ],
        env=env,
    )
    progress_json = progress_png.with_suffix(".json")
    corr = None
    if progress_json.is_file():
        data = json.loads(progress_json.read_text(encoding="utf-8"))
        corr = data.get("corr_pearson")

    summary = run_dir / "summary.md"
    sar_period_line = (
        f"`{args.date_from}` .. `{args.date_to}`" if (args.date_from and args.date_to) else f"`{args.month or '—'}` (month)"
    )
    lines = [
        f"# DEMO run: {args.region}",
        "",
        f"- timestamp: `{stamp}`",
        f"- region: `{args.region}`",
        f"- SAR period: {sar_period_line}",
        f"- epsg: `{args.epsg}`",
        "",
        "## Input data",
        f"- DEM: `{_path_or_rel(dem_tif, run_dir)}`",
        f"- SAR (RTC): `{_path_or_rel(sar_tif, run_dir)}`",
    ]
    if dem_manifest_path:
        lines.append(f"- DEM manifest: `{_path_or_rel(dem_manifest_path, run_dir)}`")
    lines.extend(
        [
            "",
            "## Artifacts",
            f"- DEM quality folder: `{_path_or_rel(quality_dir, run_dir)}`",
            f"- SAR vs DEM PNG: `{_path_or_rel(progress_png, run_dir)}`",
            f"- SAR vs DEM JSON: `{_path_or_rel(progress_json, run_dir)}`",
        ]
    )
    if corr is not None:
        lines.append(f"- Pearson corr (SAR log amplitude vs DEM): `{corr:.6f}`")
    lines.extend(
        [
            "",
            "## Quick open",
            f"- Интерактивный 3D HTML: `{_path_or_rel(quality_dir, run_dir)}`",
            f"- Одна картинка прогресса: `{_path_or_rel(progress_png, run_dir)}`",
        ]
    )
    summary.write_text("\n".join(lines), encoding="utf-8")

    print(f"Demo run folder: {run_dir}")
    print(f"Summary: {summary}")


if __name__ == "__main__":
    main()
