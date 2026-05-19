# -*- coding: utf-8 -*-
"""Расчёт уклона и аспекта из DEM."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import rasterio


def _pixel_size(transform: rasterio.Affine) -> tuple[float, float]:
    dx = abs(float(transform.a))
    dy = abs(float(transform.e))
    if dx == 0 or dy == 0:
        raise ValueError(f"Некорректный transform без размера пикселя: {transform}")
    return dx, dy


def slope_aspect_from_array(elevation: np.ndarray, transform: rasterio.Affine) -> tuple[np.ndarray, np.ndarray]:
    """Вернуть slope/aspect в градусах для 2D DEM-массива.

    Aspect: 0=N, 90=E, 180=S, 270=W.
    """

    arr = elevation.astype("float32", copy=False)
    dx, dy = _pixel_size(transform)
    dz_dy, dz_dx = np.gradient(arr, dy, dx)
    slope = np.degrees(np.arctan(np.hypot(dz_dx, dz_dy))).astype("float32")
    aspect = (np.degrees(np.arctan2(-dz_dx, dz_dy)) + 360.0) % 360.0
    return slope.astype("float32"), aspect.astype("float32")


def slope_from_dem(dem_path: Path | str) -> np.ndarray:
    """Прочитать DEM и вернуть slope в градусах."""

    with rasterio.open(dem_path) as src:
        dem = src.read(1, masked=True).filled(np.nan)
        slope, _ = slope_aspect_from_array(dem, src.transform)
        slope[np.isnan(dem)] = np.nan
        return slope


def write_slope_aspect(
    dem_path: Path | str,
    slope_out: Path | str,
    aspect_out: Path | str | None = None,
) -> tuple[Path, Path | None]:
    """Записать slope/aspect GeoTIFF рядом с геопривязкой исходного DEM."""

    dem_path = Path(dem_path)
    slope_out = Path(slope_out)
    aspect_path = Path(aspect_out) if aspect_out else None

    with rasterio.open(dem_path) as src:
        dem = src.read(1, masked=True).filled(np.nan)
        slope, aspect = slope_aspect_from_array(dem, src.transform)
        invalid = np.isnan(dem)
        slope[invalid] = np.nan
        aspect[invalid] = np.nan
        profile = src.profile.copy()
        profile.update(dtype="float32", count=1, nodata=np.nan, compress="deflate")

    slope_out.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(slope_out, "w", **profile) as dst:
        dst.write(slope, 1)

    if aspect_path:
        aspect_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(aspect_path, "w", **profile) as dst:
            dst.write(aspect, 1)

    return slope_out, aspect_path


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Рассчитать slope/aspect из DEM GeoTIFF.")
    p.add_argument("dem", type=Path)
    p.add_argument("--slope-out", type=Path, default=Path(""))
    p.add_argument("--aspect-out", type=Path, default=Path(""))
    return p


def main() -> None:
    args = build_parser().parse_args()
    slope_out = args.slope_out or args.dem.with_name(args.dem.stem + "_slope_deg.tif")
    aspect_out = args.aspect_out or args.dem.with_name(args.dem.stem + "_aspect_deg.tif")
    out_slope, out_aspect = write_slope_aspect(args.dem, slope_out, aspect_out)
    print(f"slope:  {out_slope}")
    print(f"aspect: {out_aspect}")


if __name__ == "__main__":
    main()
