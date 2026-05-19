# -*- coding: utf-8 -*-
"""
Наглядный прогресс: SAR vs DEM для региона.

Берем:
- SAR GeoTIFF (например Sentinel-1 RTC из download_satellite_sra)
- Эталонный DEM из download_reference_dem (cop30 по умолчанию)

Затем:
- ресемплим DEM на сетку SAR
- строим PNG-репорт: SAR heatmap, DEM heatmap, scatter + корреляция
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject

from dem.config import DEFAULT_REGION, REGIONS  # noqa: E402
from dem.io.layout import (  # noqa: E402
    iter_reference_dem_processed_bases_newest_first,
    iter_sar_run_roots_newest_first,
    progress_report_dir,
    resolve_out_dir,
)


def _latest_sar_image(region: str) -> Path:
    roots = list(iter_sar_run_roots_newest_first())
    if not roots:
        raise SystemExit("Нет SAR runs (outputs/**/data/raw/runs или data/raw/runs).")

    best: tuple[float, Path] | None = None
    for runs_root in roots:
        if not runs_root.is_dir():
            continue
        run_dirs = list(runs_root.glob(f"sar=sentinel1_rtc_region={region}_from=*"))
        for rd in run_dirs:
            for scene_dir in rd.glob("scene_*"):
                tif = scene_dir / "image.tif"
                if tif.is_file():
                    mtime = tif.stat().st_mtime
                    if best is None or mtime > best[0]:
                        best = (mtime, tif)
    if best is None:
        raise SystemExit(f"Не найдено image.tif для региона {region} в {roots}")
    return best[1]


def _pick_default_dem(region: str, epsg: int) -> Path:
    all_cands: list[Path] = []
    for base in iter_reference_dem_processed_bases_newest_first():
        dem_root = base / region
        if not dem_root.is_dir():
            continue
        all_cands.extend([p for p in dem_root.rglob(f"*epsg{epsg}*.tif") if p.is_file()])
    if not all_cands:
        raise SystemExit(
            f"Не найдено DEM epsg{epsg} для {region} (outputs/**/data/processed/reference_dem или legacy data/processed/reference_dem)."
        )

    candidates = sorted(all_cands, key=lambda p: p.stat().st_mtime, reverse=True)
    for p in candidates:
        if "cop30" in p.name.lower():
            return p
    return candidates[0]


def _reproject_to_match(
    src_path: Path,
    *,
    dst_crs,
    dst_transform,
    dst_width: int,
    dst_height: int,
    resampling: Resampling,
    dst_nodata: float = np.nan,
) -> np.ndarray:
    with rasterio.open(src_path) as src:
        src_arr = src.read(1)
        src_nodata = src.nodata

        dst_arr = np.full((dst_height, dst_width), dst_nodata, dtype=np.float32)

        reproject(
            source=src_arr,
            destination=dst_arr,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            resampling=resampling,
            src_nodata=src_nodata,
            dst_nodata=dst_nodata,
        )
    return dst_arr


def _pearson_corr(a: np.ndarray, b: np.ndarray) -> float:
    if a.size < 2:
        return float("nan")
    a0 = a - a.mean()
    b0 = b - b.mean()
    denom = float(np.sqrt((a0 * a0).sum()) * np.sqrt((b0 * b0).sum()))
    if denom == 0:
        return float("nan")
    return float((a0 * b0).sum() / denom)


def main() -> None:
    parser = argparse.ArgumentParser(description="SAR vs DEM визуализация для progress-report.")
    parser.add_argument("--region", type=str, default=DEFAULT_REGION, choices=sorted(REGIONS.keys()))
    parser.add_argument("--sar-tif", type=str, default="", help="Прямой путь к SAR image.tif (если задан).")
    parser.add_argument("--dem-tif", type=str, default="", help="Прямой путь к DEM epsg3857 tif (если задан).")
    parser.add_argument("--epsg", type=int, default=3857, help="Целевой EPSG для DEM (и ожидание для SAR).")
    parser.add_argument("--sar-band", type=int, default=1, help="Номер band в SAR tif (1 = VV по текущему скрипту).")
    parser.add_argument(
        "--out",
        type=str,
        default="",
        help="PNG отчёта; пусто = outputs/<дата>/progress_report/sar_dem_progress.png.",
    )
    parser.add_argument("--max-points", type=int, default=50000, help="Максимум точек для scatter.")
    args = parser.parse_args()

    out_path = resolve_out_dir(args.out, lambda: progress_report_dir() / "sar_dem_progress.png")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    sar_path = Path(args.sar_tif) if args.sar_tif else _latest_sar_image(args.region)
    dem_path = Path(args.dem_tif) if args.dem_tif else _pick_default_dem(args.region, args.epsg)

    if not sar_path.is_file():
        raise SystemExit(f"SAR tif не найден: {sar_path}")
    if not dem_path.is_file():
        raise SystemExit(f"DEM tif не найден: {dem_path}")

    with rasterio.open(sar_path) as sar:
        sar_arr = sar.read(args.sar_band).astype(np.float32)
        sar_crs = sar.crs
        sar_transform = sar.transform
        sar_bounds = sar.bounds
        sar_width = sar.width
        sar_height = sar.height

    # Лог-преобразование чтобы динамика SAR была нагляднее.
    sar_mask = np.isfinite(sar_arr)
    sar_log = np.full_like(sar_arr, np.nan, dtype=np.float32)
    sar_log[sar_mask] = np.log10(np.maximum(sar_arr[sar_mask], 0.0) + 1e-6)

    dem_reproj = _reproject_to_match(
        dem_path,
        dst_crs=sar_crs,
        dst_transform=sar_transform,
        dst_width=sar_width,
        dst_height=sar_height,
        resampling=Resampling.bilinear,
        dst_nodata=np.nan,
    )

    dem_mask = np.isfinite(dem_reproj)
    both = sar_mask & dem_mask

    sar_vals = sar_log[both]
    dem_vals = dem_reproj[both]

    corr = _pearson_corr(sar_vals, dem_vals)

    # Scatter: берем подвыборку, чтобы PNG строился быстро.
    n = sar_vals.size
    if n > args.max_points:
        idx = np.array(random.sample(range(n), args.max_points), dtype=int)
        sar_s = sar_vals[idx]
        dem_s = dem_vals[idx]
    else:
        sar_s = sar_vals
        dem_s = dem_vals

    # Визуализация.
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    extent = (sar_bounds.left, sar_bounds.right, sar_bounds.bottom, sar_bounds.top)
    plt.figure(figsize=(14, 10))

    ax1 = plt.subplot(2, 2, 1)
    im1 = ax1.imshow(sar_log, cmap="gray", vmin=np.nanpercentile(sar_log, 2), vmax=np.nanpercentile(sar_log, 98), extent=extent)
    ax1.set_title(f"SAR log10 band {args.sar_band}\n{sar_path.name}")
    ax1.set_xlabel("X (m)")
    ax1.set_ylabel("Y (m)")
    plt.colorbar(im1, ax=ax1, fraction=0.046, pad=0.04)

    ax2 = plt.subplot(2, 2, 2)
    im2 = ax2.imshow(dem_reproj, cmap="terrain", extent=extent)
    ax2.set_title(f"DEM elevation\n{dem_path.name}")
    ax2.set_xlabel("X (m)")
    ax2.set_ylabel("Y (m)")
    plt.colorbar(im2, ax=ax2, fraction=0.046, pad=0.04)

    ax3 = plt.subplot(2, 1, 2)
    ax3.scatter(dem_s, sar_s, s=2, alpha=0.25)
    ax3.set_title(f"Correlation(Pearson) = {corr:.4f} | points={n}")
    ax3.set_xlabel("DEM height (m)")
    ax3.set_ylabel("SAR log10 amplitude")
    ax3.grid(True, alpha=0.25)

    plt.tight_layout()
    plt.savefig(out_path, dpi=160)

    report = {
        "region": args.region,
        "sar_path": sar_path.as_posix(),
        "dem_path": dem_path.as_posix(),
        "sar_band": args.sar_band,
        "corr_pearson": corr,
        "points_used_in_scatter": int(sar_s.size),
        "points_total": int(n),
        "output_png": out_path.as_posix(),
    }
    (out_path.with_suffix(".json")).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote: {out_path}")
    print(f"Pearson corr: {corr:.6f} (total points={n})")


if __name__ == "__main__":
    main()

