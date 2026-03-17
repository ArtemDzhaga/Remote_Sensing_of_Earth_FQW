# -*- coding: utf-8 -*-
"""
Загрузка DEM с OpenTopography и базовая предобработка.
Поддерживается район рек Хоста и Мзымта (Сочи) — горная местность, реки, застройка.
"""
import argparse
import os
import sys
from pathlib import Path
from typing import Tuple

# Чтобы при запуске из корня проекта (python src/opentopography_client.py) подхватывался config из src/
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject

try:
    import requests
except ImportError:
    requests = None

from config import REGION_SOCHI_KHOSTA_MZYMTA, DEMTYPE_CHOICES

BASE_URL = "https://portal.opentopography.org/API/globaldem"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def download_opentopography(
    output_path: Path,
    *,
    south: float,
    north: float,
    west: float,
    east: float,
    demtype: str = "SRTMGL1",
    api_key: str,
    output_format: str = "GTiff",
) -> None:
    """Скачивает глобальный DEM с OpenTopography по bbox (WGS84)."""
    if not api_key:
        raise ValueError("Требуется API ключ OpenTopography (переменная OPENTOPOGRAPHY_API_KEY или --api-key).")
    if requests is None:
        raise RuntimeError("Установите пакет requests: pip install requests")

    params = {
        "demtype": demtype,
        "south": south,
        "north": north,
        "west": west,
        "east": east,
        "outputFormat": output_format,
        "API_Key": api_key,
    }
    r = requests.get(BASE_URL, params=params, timeout=120)
    r.raise_for_status()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(r.content)


def download_dummy_placeholder(output_path: Path) -> None:
    """Тестовый искусственный DEM для проверки пайплайна без API."""
    width, height = 256, 256
    x = np.linspace(0, 10, width)
    y = np.linspace(0, 10, height)
    xx, yy = np.meshgrid(x, y)
    data = 1000 + 50 * np.sin(xx) * np.cos(yy)

    transform = rasterio.transform.from_origin(0, 10, 0.0001, 0.0001)
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:4326",
        "transform": transform,
        "nodata": None,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(data.astype("float32"), 1)


def reproject_to_epsg(src_path: Path, dst_path: Path, epsg: int = 3857) -> None:
    with rasterio.open(src_path) as src:
        dst_crs = f"EPSG:{epsg}"
        transform, width, height = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds
        )

        profile = src.profile.copy()
        profile.update(
            {
                "crs": dst_crs,
                "transform": transform,
                "width": width,
                "height": height,
            }
        )

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(dst_path, "w", **profile) as dst:
            for i in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, i),
                    destination=rasterio.band(dst, i),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=dst_crs,
                    resampling=Resampling.bilinear,
                )


def basic_stats(path: Path) -> Tuple[float, float, float, float, float]:
    with rasterio.open(path) as src:
        data = src.read(1, masked=True)
        arr = data.compressed()
        if arr.size == 0:
            return (float("nan"),) * 5
        return (
            float(np.nanmin(arr)),
            float(np.nanmax(arr)),
            float(np.nanmean(arr)),
            float(np.nanstd(arr)),
            float(np.mean(np.isnan(data.filled(np.nan)))),
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Загрузка DEM с OpenTopography (район Сочи: Хоста, Мзымта) и базовая предобработка."
    )
    parser.add_argument(
        "--raw-dir",
        type=str,
        default="data/raw",
        help="Каталог для сырых DEM файлов",
    )
    parser.add_argument(
        "--processed-dir",
        type=str,
        default="data/processed",
        help="Каталог для предобработанных DEM файлов",
    )
    parser.add_argument(
        "--epsg",
        type=int,
        default=3857,
        help="Целевая проекция EPSG для репроекции",
    )
    parser.add_argument(
        "--region",
        type=str,
        default="sochi",
        choices=["sochi"],
        help="Регион: sochi — район рек Хоста и Мзымта (Сочи)",
    )
    parser.add_argument(
        "--demtype",
        type=str,
        default="SRTMGL1",
        choices=DEMTYPE_CHOICES,
        help="Тип глобального DEM (игнорируется при --demo)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Использовать тестовый искусственный DEM вместо загрузки с OpenTopography",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=os.environ.get("OPENTOPOGRAPHY_API_KEY", ""),
        help="API ключ OpenTopography (по умолчанию из переменной OPENTOPOGRAPHY_API_KEY)",
    )
    args = parser.parse_args()

    raw_dir = Path(args.raw_dir)
    processed_dir = Path(args.processed_dir)
    ensure_dir(raw_dir)
    ensure_dir(processed_dir)

    if args.region == "sochi":
        bbox = REGION_SOCHI_KHOSTA_MZYMTA
        raw_name = "sochi_khosta_mzymta_dem_raw.tif"
    else:
        bbox = REGION_SOCHI_KHOSTA_MZYMTA
        raw_name = "dem_raw.tif"

    raw_path = raw_dir / raw_name
    processed_path = processed_dir / f"{raw_path.stem.replace('_raw', '')}_epsg{args.epsg}.tif"

    if args.demo:
        print(f"[1/3] Генерация тестового DEM в {raw_path}")
        download_dummy_placeholder(raw_path)
    else:
        print(f"[1/3] Загрузка DEM с OpenTopography (район Сочи: Хоста, Мзымта) в {raw_path}")
        download_opentopography(
            raw_path,
            south=bbox["south"],
            north=bbox["north"],
            west=bbox["west"],
            east=bbox["east"],
            demtype=args.demtype,
            api_key=args.api_key.strip(),
        )

    print(f"[2/3] Репроекция DEM в {processed_path} (EPSG:{args.epsg})")
    reproject_to_epsg(raw_path, processed_path, epsg=args.epsg)

    print("[3/3] Статистика по предобработанному DEM:")
    vmin, vmax, mean, std, nan_frac = basic_stats(processed_path)
    print(f"  min: {vmin:.3f}")
    print(f"  max: {vmax:.3f}")
    print(f"  mean: {mean:.3f}")
    print(f"  std: {std:.3f}")
    print(f"  доля NaN: {nan_frac:.6f}")


if __name__ == "__main__":
    main()
