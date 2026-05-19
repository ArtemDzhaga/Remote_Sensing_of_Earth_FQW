# -*- coding: utf-8 -*-
"""Сравнение нескольких DEM с эталоном: таблица метрик для MVP."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject

from dem.features.slope import slope_aspect_from_array
from dem.io.layout import progress_report_dir, resolve_out_dir


def _read_reference(path: Path) -> tuple[np.ndarray, dict]:
    with rasterio.open(path) as src:
        arr = src.read(1, masked=True).filled(np.nan).astype("float32")
        meta = {
            "crs": src.crs,
            "transform": src.transform,
            "width": src.width,
            "height": src.height,
            "nodata": src.nodata,
        }
    return arr, meta


def _read_match(path: Path, ref_meta: dict) -> np.ndarray:
    with rasterio.open(path) as src:
        src_arr = src.read(1, masked=True).filled(np.nan).astype("float32")
        dst = np.full((ref_meta["height"], ref_meta["width"]), np.nan, dtype="float32")
        reproject(
            source=src_arr,
            destination=dst,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=src.nodata,
            dst_transform=ref_meta["transform"],
            dst_crs=ref_meta["crs"],
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )
    return dst


def _metrics(candidate: np.ndarray, reference: np.ndarray, *, mask: np.ndarray, psnr_range: float) -> dict[str, float]:
    valid = mask & np.isfinite(candidate) & np.isfinite(reference)
    if not valid.any():
        return {
            "pixels": 0,
            "mae": float("nan"),
            "rmse": float("nan"),
            "bias": float("nan"),
            "psnr": float("nan"),
            "candidate_min": float("nan"),
            "candidate_max": float("nan"),
            "candidate_mean": float("nan"),
            "reference_min": float("nan"),
            "reference_max": float("nan"),
            "reference_mean": float("nan"),
        }
    err = candidate[valid] - reference[valid]
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err**2)))
    bias = float(np.mean(err))
    psnr = 20.0 * math.log10(psnr_range / max(rmse, 1e-12)) if psnr_range > 0 else float("nan")
    return {
        "pixels": int(valid.sum()),
        "mae": mae,
        "rmse": rmse,
        "bias": bias,
        "psnr": psnr,
        "candidate_min": float(np.nanmin(candidate[valid])),
        "candidate_max": float(np.nanmax(candidate[valid])),
        "candidate_mean": float(np.nanmean(candidate[valid])),
        "reference_min": float(np.nanmin(reference[valid])),
        "reference_max": float(np.nanmax(reference[valid])),
        "reference_mean": float(np.nanmean(reference[valid])),
    }


def compare_dems(
    *,
    reference: Path,
    candidates: list[tuple[str, Path]],
    out_dir: Path,
    psnr_range: float = 1000.0,
    steep_slope_deg: float = 20.0,
) -> Path:
    ref, meta = _read_reference(reference)
    slope, _ = slope_aspect_from_array(ref, meta["transform"])
    base_mask = np.isfinite(ref)
    steep_mask = base_mask & np.isfinite(slope) & (slope > steep_slope_deg)

    rows = []
    for name, path in candidates:
        arr = _read_match(path, meta)
        row = {
            "name": name,
            "path": str(path),
            "all": _metrics(arr, ref, mask=base_mask, psnr_range=psnr_range),
            f"slope_gt_{steep_slope_deg:g}deg": _metrics(arr, ref, mask=steep_mask, psnr_range=psnr_range),
        }
        rows.append(row)

    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "dem_comparison_metrics.json"
    md_path = out_dir / "dem_comparison_metrics.md"
    json_path.write_text(
        json.dumps(
            {
                "reference": str(reference),
                "psnr_range": psnr_range,
                "steep_slope_deg": steep_slope_deg,
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    lines = [
        "# DEM Comparison Metrics",
        "",
        f"- reference: `{reference}`",
        f"- psnr_range: `{psnr_range}`",
        f"- steep_slope_deg: `{steep_slope_deg}`",
        "",
        "| name | pixels | MAE | RMSE | bias | PSNR | cand min | cand max | ref min | ref max | steep MAE | steep RMSE |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        all_m = row["all"]
        steep_m = row[f"slope_gt_{steep_slope_deg:g}deg"]
        lines.append(
            f"| {row['name']} | {all_m['pixels']} | {all_m['mae']:.3f} | {all_m['rmse']:.3f} | "
            f"{all_m['bias']:.3f} | {all_m['psnr']:.3f} | {all_m['candidate_min']:.3f} | "
            f"{all_m['candidate_max']:.3f} | {all_m['reference_min']:.3f} | {all_m['reference_max']:.3f} | "
            f"{steep_m['mae']:.3f} | {steep_m['rmse']:.3f} |"
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


def _parse_candidate(values: list[str]) -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    for raw in values:
        if "=" in raw:
            name, path = raw.split("=", 1)
            out.append((name.strip(), Path(path.strip())))
        else:
            p = Path(raw)
            out.append((p.stem, p))
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Сравнить DEM-кандидаты с reference DEM.")
    p.add_argument("--reference", required=True, type=Path, help="Эталонный DEM GeoTIFF.")
    p.add_argument(
        "--candidate",
        action="append",
        required=True,
        help="Кандидат GeoTIFF. Формат: name=path.tif или просто path.tif. Можно повторять.",
    )
    p.add_argument("--out-dir", default="", help="Пусто = outputs/<дата>/progress_report/dem_comparison")
    p.add_argument("--psnr-range", type=float, default=1000.0)
    p.add_argument("--steep-slope-deg", type=float, default=20.0)
    return p


def main() -> None:
    args = build_parser().parse_args()
    out_dir = resolve_out_dir(args.out_dir, lambda: progress_report_dir() / "dem_comparison")
    report = compare_dems(
        reference=args.reference,
        candidates=_parse_candidate(args.candidate),
        out_dir=out_dir,
        psnr_range=args.psnr_range,
        steep_slope_deg=args.steep_slope_deg,
    )
    print(f"report: {report}")


if __name__ == "__main__":
    main()
