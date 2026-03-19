# -*- coding: utf-8 -*-
"""
Скачивание всепогодных SAR-снимков (Sentinel-1 RTC) из Planetary Computer STAC.

По структуре и CLI аналогично RGB/NIR скрипту:
- download/list subcommands
- run-папка на итерацию
- отдельная папка на сцену
- image.tif + image.md + image.stac.json + quicklook_vv.png
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from config import DEFAULT_REGION, DEFAULT_SAR_SATELLITE, REGIONS, SAR_SATELLITES  # noqa: E402


@dataclass
class SceneMeta:
    item_id: str
    datetime_utc: str
    platform: str
    epsg: int | None
    orbit: str | None
    stac_url: str


def _require_deps() -> None:
    try:
        from pystac_client import Client  # noqa: F401
        import planetary_computer  # noqa: F401
        from odc.stac import load  # noqa: F401
        import rioxarray  # noqa: F401
        import rasterio  # noqa: F401
    except Exception as e:  # pragma: no cover
        raise RuntimeError("Не хватает зависимостей. Установи: pip install -r requirements.txt") from e


def _slug(s: str) -> str:
    return s.replace(":", "-").replace("/", "-").replace("\\", "-").replace(" ", "_")


def _region_bbox(region: dict) -> dict:
    if all(k in region for k in ("south", "north", "west", "east")):
        return {
            "south": float(region["south"]),
            "north": float(region["north"]),
            "west": float(region["west"]),
            "east": float(region["east"]),
        }
    polygon = region.get("polygon")
    if polygon and polygon.get("coordinates"):
        ring = polygon["coordinates"][0]
        lons = [pt[0] for pt in ring]
        lats = [pt[1] for pt in ring]
        return {
            "south": float(min(lats)),
            "north": float(max(lats)),
            "west": float(min(lons)),
            "east": float(max(lons)),
        }
    raise ValueError("Регион должен содержать bbox (south/north/west/east) или polygon.")


def _region_polygon(region: dict) -> dict | None:
    polygon = region.get("polygon")
    if isinstance(polygon, dict) and polygon.get("type") == "Polygon":
        return polygon
    return None


def _parse_date_for_search(s: str, *, is_end: bool) -> str:
    s = s.strip()
    if len(s) == 4 and s.isdigit():
        y = int(s)
        return date(y, 12, 31).isoformat() if is_end else date(y, 1, 1).isoformat()
    if len(s) == 7 and s[4] == "-" and s[:4].isdigit() and s[5:7].isdigit():
        y = int(s[:4])
        m = int(s[5:7])
        if is_end:
            if m == 12:
                return date(y, 12, 31).isoformat()
            first_next = date(y, m + 1, 1)
            return (first_next - timedelta(days=1)).isoformat()
        return date(y, m, 1).isoformat()
    return datetime.fromisoformat(s).date().isoformat()


def _parse_month_to_range(month: str) -> tuple[str, str]:
    y, m = month.strip().split("-")
    y_i = int(y)
    m_i = int(m)
    start = date(y_i, m_i, 1)
    end_excl = date(y_i + 1, 1, 1) if m_i == 12 else date(y_i, m_i + 1, 1)
    end = date.fromordinal(end_excl.toordinal() - 1)
    return start.isoformat(), end.isoformat()


def _stac_items(
    *,
    collection: str,
    region_wgs84: dict,
    date_from: str,
    date_to: str,
    max_items: int,
    retries: int,
    retry_delay_sec: float,
) -> list[object]:
    _require_deps()
    from pystac_client import Client
    import planetary_computer

    catalog_url = "https://planetarycomputer.microsoft.com/api/stac/v1"
    bbox_wgs84 = _region_bbox(region_wgs84)
    bbox = [
        float(bbox_wgs84["west"]),
        float(bbox_wgs84["south"]),
        float(bbox_wgs84["east"]),
        float(bbox_wgs84["north"]),
    ]
    polygon = _region_polygon(region_wgs84)
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            client = Client.open(catalog_url)
            search = client.search(
                collections=[collection],
                bbox=None if polygon else bbox,
                intersects=polygon,
                datetime=f"{date_from}/{date_to}",
                max_items=max_items,
            )
            items = list(search.items())
            items.sort(key=lambda it: it.properties.get("datetime", ""))
            return [planetary_computer.sign(it) for it in items]
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(retry_delay_sec)
            else:
                raise last_err
    return []


def _save_sar_geotiff(
    *,
    item: object,
    bbox_wgs84: dict,
    out_tif: Path,
    bands: list[str],
    dst_epsg: int,
    resolution: float,
) -> tuple[int, int]:
    _require_deps()
    from odc.stac import load
    import rioxarray  # noqa: F401

    bbox = (
        float(bbox_wgs84["west"]),
        float(bbox_wgs84["south"]),
        float(bbox_wgs84["east"]),
        float(bbox_wgs84["north"]),
    )
    ds = load([item], bands=bands, bbox=bbox, crs=f"EPSG:{dst_epsg}", resolution=resolution, fail_on_error=True)
    if "time" in ds.dims and ds.sizes.get("time", 0) == 1:
        ds = ds.isel(time=0, drop=True)
    da = ds.to_array(dim="band")
    if "time" in da.dims and da.sizes.get("time", 0) == 1:
        da = da.isel(time=0, drop=True)

    out_tif.parent.mkdir(parents=True, exist_ok=True)
    da_f32 = da.astype("float32")
    da_f32.rio.write_nodata(np.nan, inplace=True)
    da_f32.rio.to_raster(out_tif, compress="deflate")
    return int(da_f32.sizes["y"]), int(da_f32.sizes["x"])


def _save_quicklook_vv(tif_path: Path, out_png: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import rasterio

    with rasterio.open(tif_path) as src:
        arr = src.read(1).astype(np.float32)
        mask = np.isfinite(arr)
        if not np.any(mask):
            return
        lo, hi = np.percentile(arr[mask], [2, 98])
        img = np.clip((arr - lo) / (hi - lo + 1e-9), 0, 1)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    plt.imsave(out_png, img, cmap="gray")


def _make_run_dir(out_dir: Path, tag: str) -> Path:
    stamp = _slug(datetime.now().isoformat(timespec="seconds"))
    run_dir = out_dir / "runs" / f"{_slug(tag)}_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _write_md(md_path: Path, scene: SceneMeta, region: str, bbox: dict, bands: list[str], out_tif: Path, res: float, epsg: int) -> None:
    lines = [
        f"# SAR снимок: {scene.platform}",
        "",
        f"- item_id: `{scene.item_id}`",
        f"- datetime (UTC): {scene.datetime_utc}",
        f"- orbit: {scene.orbit if scene.orbit else 'unknown'}",
        f"- region: `{region}`",
        f"- bbox: south={bbox['south']}, north={bbox['north']}, west={bbox['west']}, east={bbox['east']}",
        f"- bands: {', '.join(bands)}",
        f"- tif: `{out_tif.as_posix()}`",
        f"- target CRS: EPSG:{epsg}",
        f"- resolution: {res}",
        f"- stac: {scene.stac_url}",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="download_satellite_sra",
        formatter_class=argparse.RawTextHelpFormatter,
        description="Скачивание всепогодных SAR снимков (Sentinel-1 RTC).\nКоманды: download, list",
        epilog=(
            "Полный help параметров:\n"
            "  python src/download_satellite_sra.py download --help\n"
            "  python src/download_satellite_sra.py list --help"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--region", type=str, default=DEFAULT_REGION, choices=sorted(REGIONS.keys()), help="Ключ bbox.")
    common.add_argument("--satellite", type=str, default=DEFAULT_SAR_SATELLITE, choices=sorted(SAR_SATELLITES.keys()), help="SAR коллекция.")
    common.add_argument("--month", type=str, default="", help="YYYY-MM (перекрывает date-from/date-to).")
    common.add_argument("--date-from", type=str, default="2000-01-01", help="Начало периода: YYYY, YYYY-MM или YYYY-MM-DD.")
    common.add_argument("--date-to", type=str, default="2026-12-31", help="Конец периода: YYYY, YYYY-MM или YYYY-MM-DD.")
    common.add_argument("--dst-epsg", type=int, default=3857, help="Целевая проекция.")
    common.add_argument("--resolution", type=float, default=None, help="Разрешение в единицах CRS.")
    common.add_argument("--out-dir", type=str, default="data/raw", help="Базовая папка.")
    common.add_argument("--search-max-items", type=int, default=10000, help="Лимит найденных сцен STAC.")
    common.add_argument("--retries", type=int, default=3, help="Ретраи на сетевые ошибки.")
    common.add_argument("--retry-delay-sec", type=float, default=3.0, help="Пауза между ретраями.")

    dl = sub.add_parser("download", parents=[common], help="Скачать сцены SAR", formatter_class=argparse.RawTextHelpFormatter)
    dl.add_argument("--max-scenes", "--limit", dest="max_scenes", type=int, default=1, help="Сколько сцен скачивать. 0 = все.")
    dl.set_defaults(func=download_command)

    ls = sub.add_parser("list", parents=[common], help="Показать список SAR сцен", formatter_class=argparse.RawTextHelpFormatter)
    ls.add_argument("--max-scenes", "--limit", dest="max_scenes", type=int, default=10, help="Сколько сцен показать. 0 = все.")
    ls.set_defaults(func=list_command)

    return parser


def download_command(args: argparse.Namespace) -> None:
    sat = SAR_SATELLITES[args.satellite]
    if args.resolution is None:
        args.resolution = float(sat["native_resolution"])
    date_from = _parse_date_for_search(args.date_from, is_end=False)
    date_to = _parse_date_for_search(args.date_to, is_end=True)
    if args.month:
        date_from, date_to = _parse_month_to_range(args.month)
    region = REGIONS[args.region]
    bbox = _region_bbox(region)
    run_tag = f"sar={args.satellite}_region={args.region}_from={date_from}_to={date_to}_res={args.resolution}"
    run_dir = _make_run_dir(Path(args.out_dir), run_tag)

    items = _stac_items(
        collection=sat["collection"],
        region_wgs84=region,
        date_from=date_from,
        date_to=date_to,
        max_items=args.search_max_items,
        retries=args.retries,
        retry_delay_sec=args.retry_delay_sec,
    )
    if args.max_scenes != 0:
        items = items[: args.max_scenes]
    print(f"Найдено SAR сцен: {len(items)}")

    total_start = time.perf_counter()
    for idx, it in enumerate(items, start=1):
        scene_start = time.perf_counter()
        dt = str(it.properties.get("datetime", ""))
        scene_dir = run_dir / f"scene_{_slug(dt[:19].replace('T','_'))}_{it.id}"
        scene_dir.mkdir(parents=True, exist_ok=True)
        out_tif = scene_dir / "image.tif"
        out_md = scene_dir / "image.md"
        out_json = scene_dir / "image.stac.json"
        out_quick = scene_dir / "quicklook_vv.png"

        print(f"[{idx}/{len(items)}] {it.id}")
        y, x = _save_sar_geotiff(
            item=it,
            bbox_wgs84=bbox,
            out_tif=out_tif,
            bands=sat["bands"],
            dst_epsg=args.dst_epsg,
            resolution=args.resolution,
        )
        _save_quicklook_vv(out_tif, out_quick)
        out_json.write_text(json.dumps(it.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

        meta = SceneMeta(
            item_id=it.id,
            datetime_utc=dt,
            platform=str(it.properties.get("platform", args.satellite)),
            epsg=int(it.properties["proj:epsg"]) if it.properties.get("proj:epsg") is not None else None,
            orbit=str(it.properties.get("sat:orbit_state")) if it.properties.get("sat:orbit_state") is not None else None,
            stac_url=f"https://planetarycomputer.microsoft.com/api/stac/v1/collections/{sat['collection']}/items/{it.id}",
        )
        _write_md(out_md, meta, args.region, bbox, sat["bands"], out_tif, args.resolution, args.dst_epsg)
        with out_md.open("a", encoding="utf-8") as f:
            f.write(f"\n\n## Размер\n- {y} x {x}\n")
        scene_elapsed = time.perf_counter() - scene_start
        print(f"  время сцены: {scene_elapsed:.1f} сек")

    total_elapsed = time.perf_counter() - total_start
    print(f"Итого время на сцены: {total_elapsed:.1f} сек")
    print(f"Готово: {run_dir}")


def list_command(args: argparse.Namespace) -> None:
    sat = SAR_SATELLITES[args.satellite]
    date_from = _parse_date_for_search(args.date_from, is_end=False)
    date_to = _parse_date_for_search(args.date_to, is_end=True)
    if args.month:
        date_from, date_to = _parse_month_to_range(args.month)
    items = _stac_items(
        collection=sat["collection"],
        region_wgs84=REGIONS[args.region],
        date_from=date_from,
        date_to=date_to,
        max_items=args.search_max_items,
        retries=args.retries,
        retry_delay_sec=args.retry_delay_sec,
    )
    total_found = len(items)
    if args.max_scenes != 0:
        items = items[: args.max_scenes]
    for it in items:
        print(f"- {it.id} | {it.properties.get('datetime', '')}")
    print(f"Итого SAR сцен: {total_found} (показано {len(items)})")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
