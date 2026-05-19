# -*- coding: utf-8 -*-
"""
Загрузка «эталонного пакета» DEM: несколько открытых источников для одного региона.

По умолчанию: COP30 + SRTMGL1 (см. open_dem_sources.DEFAULT_REFERENCE_DEM_ALIASES).
Итог: raw GeoTIFF + репроекция + manifest.json для пайплайнов/валидации.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dem.config import DEFAULT_REGION, REGIONS  # noqa: E402
from dem.io.layout import (  # noqa: E402
    reference_dem_processed_base,
    reference_dem_raw_base,
    resolve_out_dir,
)
from dem.ingest.open_dem_sources import DEFAULT_REFERENCE_DEM_ALIASES, OPEN_DEM_SOURCES  # noqa: E402
from dem.ingest.opentopography_client import (  # noqa: E402
    basic_stats,
    download_dummy_placeholder,
    download_opentopography,
    ensure_dir,
    reproject_to_epsg,
)


def _build_manifest(
    *,
    region_key: str,
    bbox: dict,
    epsg: int,
    layers: list[dict],
    demo: bool,
    run_stamp: str,
) -> dict:
    return {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "run_stamp": run_stamp,
        "region": region_key,
        "bbox_wgs84": bbox,
        "target_epsg": epsg,
        "demo_mode": demo,
        "layers": layers,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Скачать несколько эталонных DEM (OpenTopography) для региона и собрать manifest."
    )
    parser.add_argument("--region", type=str, default=DEFAULT_REGION, choices=sorted(REGIONS.keys()))
    parser.add_argument(
        "--sources",
        type=str,
        default=",".join(DEFAULT_REFERENCE_DEM_ALIASES),
        help="Список alias из open_dem_sources через запятую (по умолчанию cop30,srtm30).",
    )
    parser.add_argument(
        "--raw-dir",
        type=str,
        default="",
        help="База raw reference_dem; пусто = outputs/<дата>/data/raw/reference_dem.",
    )
    parser.add_argument(
        "--processed-dir",
        type=str,
        default="",
        help="База processed reference_dem; пусто = outputs/<дата>/data/processed/reference_dem.",
    )
    parser.add_argument("--epsg", type=int, default=3857)
    parser.add_argument(
        "--bbox-source",
        type=str,
        choices=("auto", "polygon"),
        default="auto",
        help=(
            "auto: как в dem.geo.utils.region_bbox (полигонированный регион даёт тот же охват, что south/north/west/east в конфиге). "
            "polygon: только ограничивающий прямоугольник GeoJSON polygon (игнорировать явный bbox в конфиге; нужен polygon)."
        ),
    )
    parser.add_argument("--demo", action="store_true", help="Искусственный DEM вместо API (для теста).")
    parser.add_argument(
        "--api-key",
        type=str,
        default=os.environ.get("OPENTOPOGRAPHY_API_KEY", ""),
        help="Ключ OpenTopography (или OPENTOPOGRAPHY_API_KEY).",
    )
    args = parser.parse_args()
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    region = REGIONS[args.region]
    from dem.geo.utils import region_bbox  # noqa: E402

    if args.bbox_source == "polygon":
        poly = region.get("polygon")
        if not isinstance(poly, dict) or poly.get("type") != "Polygon" or not poly.get("coordinates"):
            raise SystemExit("--bbox-source polygon требует GeoJSON Polygon у региона в конфиге.")
        ring = poly["coordinates"][0]
        lons = [pt[0] for pt in ring]
        lats = [pt[1] for pt in ring]
        bbox = {
            "south": float(min(lats)),
            "north": float(max(lats)),
            "west": float(min(lons)),
            "east": float(max(lons)),
        }
    else:
        bbox = region_bbox(region)

    aliases = [a.strip() for a in args.sources.split(",") if a.strip()]
    for a in aliases:
        if a not in OPEN_DEM_SOURCES:
            raise SystemExit(f"Неизвестный alias источника: {a}. Доступны: {', '.join(sorted(OPEN_DEM_SOURCES))}")

    raw_base = resolve_out_dir(args.raw_dir, reference_dem_raw_base)
    proc_base = resolve_out_dir(args.processed_dir, reference_dem_processed_base)
    raw_root = raw_base / args.region / run_stamp
    proc_root = proc_base / args.region / run_stamp
    ensure_dir(raw_root)
    ensure_dir(proc_root)

    layers: list[dict] = []
    api_key = args.api_key.strip()

    for alias in aliases:
        meta = OPEN_DEM_SOURCES[alias]
        demtype = meta["demtype"]
        raw_name = f"{args.region}_{alias}_{demtype}_opentopo_dl{run_stamp}_raw.tif"
        raw_path = raw_root / raw_name
        proc_path = proc_root / f"{args.region}_{alias}_{demtype}_opentopo_dl{run_stamp}_epsg{args.epsg}.tif"

        print(f"[{alias}] demtype={demtype} → raw {raw_path}")
        if args.demo:
            download_dummy_placeholder(raw_path)
        else:
            download_opentopography(
                raw_path,
                south=bbox["south"],
                north=bbox["north"],
                west=bbox["west"],
                east=bbox["east"],
                demtype=demtype,
                api_key=api_key,
            )

        print(f"  репроекция → {proc_path}")
        reproject_to_epsg(raw_path, proc_path, epsg=args.epsg)
        vmin, vmax, mean, std, nan_frac = basic_stats(proc_path)
        layers.append(
            {
                "alias": alias,
                "demtype": demtype,
                "label": meta["label"],
                "provider": "OpenTopography",
                "downloaded_utc": run_stamp,
                "raw_path": raw_path.as_posix(),
                "processed_path": proc_path.as_posix(),
                "stats": {
                    "min": vmin,
                    "max": vmax,
                    "mean": mean,
                    "std": std,
                    "nan_fraction": nan_frac,
                },
            }
        )

    manifest_path = proc_root / "reference_dem_manifest.json"
    manifest = _build_manifest(
        region_key=args.region,
        bbox=bbox,
        epsg=args.epsg,
        layers=layers,
        demo=args.demo,
        run_stamp=run_stamp,
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
