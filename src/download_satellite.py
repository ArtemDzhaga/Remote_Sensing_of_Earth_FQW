# -*- coding: utf-8 -*-
"""
Загрузка оптических спутниковых снимков из Planetary Computer (STAC) и сохранение:
- GeoTIFF (RGB + NIR по желанию)
- quicklook RGB PNG (чтобы быстро проверить, что файл визуально адекватный)
- Markdown с метаданными
- STAC snapshot JSON

Поддерживаемые спутники (конфиг `src/config.py`):
- Sentinel-2 L2A (по умолчанию)
- Landsat 7/8/9 L2
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

from config import DEFAULT_REGION, DEFAULT_SATELLITE, REGIONS, SATELLITES  # noqa: E402


@dataclass
class DownloadScene:
    item_id: str
    datetime_utc: str
    platform: str
    cloud_cover: float | None
    epsg: int | None
    extra_tile: str | None
    stac_url: str


def _require_deps() -> None:
    try:
        from pystac_client import Client  # noqa: F401
        import planetary_computer  # noqa: F401
        from odc.stac import load  # noqa: F401
        import rasterio  # noqa: F401
        import rioxarray  # noqa: F401
    except Exception as e:  # pragma: no cover
        raise RuntimeError("Не хватает зависимостей. Установи: pip install -r requirements.txt") from e


def _slug(s: str) -> str:
    return (
        s.replace(":", "-")
        .replace("/", "-")
        .replace("\\", "-")
        .replace(" ", "_")
        .replace("..", ".")
    )


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
    """
    Разрешаем форматы:
    - YYYY
    - YYYY-MM
    - YYYY-MM-DD
    """
    s = s.strip()
    if len(s) == 4 and s.isdigit():
        y = int(s)
        if is_end:
            return date(y, 12, 31).isoformat()
        return date(y, 1, 1).isoformat()

    if len(s) == 7 and s[4] == "-" and s[:4].isdigit() and s[5:7].isdigit():
        y = int(s[:4])
        m = int(s[5:7])
        if is_end:
            # last day of month = day before first day of next month
            if m == 12:
                return date(y, 12, 31).isoformat()
            first_next = date(y, m + 1, 1)
            return (first_next - timedelta(days=1)).isoformat()
        return date(y, m, 1).isoformat()

    dt = datetime.fromisoformat(s).date()
    if is_end:
        return dt.isoformat()
    return dt.isoformat()


def _parse_date_range(date_from: str, date_to: str) -> tuple[str, str]:
    return (
        _parse_date_for_search(date_from, is_end=False),
        _parse_date_for_search(date_to, is_end=True),
    )


def _parse_month_to_range(month: str) -> tuple[str, str]:
    """YYYY-MM -> (YYYY-MM-01, YYYY-MM-lastday)"""
    month = month.strip()
    y, m = month.split("-")
    y_i = int(y)
    m_i = int(m)
    start = date(y_i, m_i, 1)
    if m_i == 12:
        end_excl = date(y_i + 1, 1, 1)
    else:
        end_excl = date(y_i, m_i + 1, 1)
    last_day = date.fromordinal(end_excl.toordinal() - 1)
    return (start.isoformat(), last_day.isoformat())


def _stac_search_items(
    *,
    collection: str,
    region_wgs84: dict,
    date_from: str,
    date_to: str,
    max_cloud: float,
    cloud_property: str,
    max_items: int,
    retries: int = 3,
    retry_delay_sec: float = 3.0,
) -> list[object]:
    _require_deps()
    from pystac_client import Client
    import planetary_computer
    catalog_url = "https://planetarycomputer.microsoft.com/api/stac/v1"

    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            client = Client.open(catalog_url)

            bbox_wgs84 = _region_bbox(region_wgs84)
            bbox = [
                float(bbox_wgs84["west"]),
                float(bbox_wgs84["south"]),
                float(bbox_wgs84["east"]),
                float(bbox_wgs84["north"]),
            ]
            polygon = _region_polygon(region_wgs84)

            search = client.search(
                collections=[collection],
                bbox=None if polygon else bbox,
                intersects=polygon,
                datetime=f"{date_from}/{date_to}",
                query={cloud_property: {"lt": float(max_cloud)}},
                max_items=max_items,
            )
            raw_items = list(search.items())

            # Fallback: если в коллекции нет cloud_property, то возьмём без фильтра.
            if not raw_items:
                search2 = client.search(
                    collections=[collection],
                    bbox=None if polygon else bbox,
                    intersects=polygon,
                    datetime=f"{date_from}/{date_to}",
                    max_items=max_items,
                )
                raw_items = list(search2.items())

            def key(it):
                cc = it.properties.get(cloud_property, it.properties.get("eo:cloud_cover", 1e9))
                dt = it.properties.get("datetime") or it.properties.get("start_datetime") or ""
                return (cc if cc is not None else 1e9, dt)

            raw_items.sort(key=key)
            return [planetary_computer.sign(it) for it in raw_items]
        except Exception as e:  # pragma: no cover
            last_err = e
            if attempt < retries:
                time.sleep(retry_delay_sec)
            else:
                raise last_err

    raise RuntimeError("STAC search failed unexpectedly")


def _save_geotiff(
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
    import rioxarray  # noqa: F401  # регистрирует .rio accessor

    bbox = (
        float(bbox_wgs84["west"]),
        float(bbox_wgs84["south"]),
        float(bbox_wgs84["east"]),
        float(bbox_wgs84["north"]),
    )

    ds = load(
        [item],
        bands=bands,
        bbox=bbox,
        crs=f"EPSG:{dst_epsg}",
        resolution=resolution,
        fail_on_error=True,
    )

    if "time" in ds.dims and ds.sizes.get("time", 0) == 1:
        ds = ds.isel(time=0, drop=True)
    da = ds.to_array(dim="band")
    if "time" in da.dims and da.sizes.get("time", 0) == 1:
        da = da.isel(time=0, drop=True)

    out_tif.parent.mkdir(parents=True, exist_ok=True)
    da_uint16 = da.astype("uint16")
    da_uint16.rio.write_nodata(0, inplace=True)
    da_uint16.rio.to_raster(out_tif, compress="deflate", nodata=0)
    return int(da_uint16.sizes["y"]), int(da_uint16.sizes["x"])


def _make_quicklook_rgb(tif_path: Path, out_png: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import rasterio

    with rasterio.open(tif_path) as src:
        if src.count < 3:
            return
        arr = src.read([1, 2, 3]).astype(np.float32)  # (3, y, x)
        nodata = src.nodata if src.nodata is not None else 0
        mask = arr[0] != nodata
        if not np.any(mask):
            return

        rgb = []
        for ch in range(3):
            vals = arr[ch][mask]
            if vals.size == 0:
                rgb.append(np.zeros_like(arr[ch], dtype=np.uint8))
                continue
            lo, hi = np.percentile(vals, [2, 98])
            ch_norm = (arr[ch] - lo) / (hi - lo + 1e-9)
            ch_norm = np.clip(ch_norm, 0, 1)
            rgb.append((ch_norm * 255).astype(np.uint8))

        rgb_img = np.stack(rgb, axis=-1)  # (y, x, 3)

    out_png.parent.mkdir(parents=True, exist_ok=True)
    plt.imsave(out_png, rgb_img)


def _write_scene_md(
    *,
    md_path: Path,
    satellite: str,
    scene: DownloadScene,
    region: str,
    bbox_wgs84: dict,
    out_tif: Path,
    bands: list[str],
    dst_epsg: int,
    resolution: float,
) -> None:
    md_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Оптический снимок: {satellite}",
        "",
        f"**item_id:** `{scene.item_id}`",
        f"**datetime (UTC):** {scene.datetime_utc}",
        f"**platform:** {scene.platform}",
        f"**cloud cover:** {scene.cloud_cover if scene.cloud_cover is not None else 'unknown'}",
        "",
        "## Регион",
        f"- region key: `{region}`",
        f"- bbox (WGS84): south={bbox_wgs84['south']}, north={bbox_wgs84['north']}, west={bbox_wgs84['west']}, east={bbox_wgs84['east']}",
        "",
        "## Данные",
        f"- GeoTIFF: `{out_tif.as_posix()}`",
        f"- bands: {', '.join(bands)}",
        f"- target CRS: EPSG:{dst_epsg}",
        f"- resolution: {resolution} (единицы CRS)",
        "",
        "## STAC",
        f"- STAC item: {scene.stac_url}",
    ]
    if scene.extra_tile:
        lines.append(f"- tile/row: {scene.extra_tile}")
    md_path.write_text("\n".join(lines), encoding="utf-8")


def _make_run_dir(out_dir: Path, tag: str) -> Path:
    stamp = datetime.now().isoformat(timespec="seconds")
    stamp = _slug(stamp)
    run_dir = out_dir / "runs" / f"{_slug(tag)}_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _build_scene_meta(
    *,
    it: object,
    satellite_key: str,
    collection: str,
    cloud_property: str,
) -> DownloadScene:
    item_id = it.id
    dt = str(it.properties.get("datetime") or it.properties.get("start_datetime") or "")
    platform = str(it.properties.get("platform") or satellite_key)

    cc = it.properties.get(cloud_property)
    if cc is None:
        cc = it.properties.get("eo:cloud_cover")
    cc_val = float(cc) if cc is not None else None

    epsg = it.properties.get("proj:epsg")
    extra_tile = None
    for k in ("s2:mgrs_tile", "landsat:path", "landsat:row", "sat:orbit_state"):
        if it.properties.get(k) is not None:
            extra_tile = f"{k}={it.properties.get(k)}"
            break

    stac_url = f"https://planetarycomputer.microsoft.com/api/stac/v1/collections/{collection}/items/{item_id}"
    return DownloadScene(
        item_id=item_id,
        datetime_utc=dt,
        platform=platform,
        cloud_cover=cc_val,
        epsg=int(epsg) if epsg is not None else None,
        extra_tile=extra_tile,
        stac_url=stac_url,
    )


def download_command(args: argparse.Namespace) -> None:
    sat_cfg = SATELLITES[args.satellite]
    collection = sat_cfg["collection"]
    region = REGIONS[args.region]
    bbox = _region_bbox(region)

    date_from, date_to = _parse_date_range(args.date_from, args.date_to)
    if args.month:
        date_from, date_to = _parse_month_to_range(args.month)

    # bands
    rgb_bands = (args.rgb_bands.split(",") if args.rgb_bands else sat_cfg["rgb_bands"])
    nir_band = args.nir_band if args.nir_band else sat_cfg["nir_band"]
    bands = list(rgb_bands)
    if args.with_nir:
        bands.append(nir_band)

    if args.resolution is None:
        args.resolution = float(sat_cfg["native_resolution"])

    tag = (
        f"sat={args.satellite}"
        f"_region={args.region}"
        f"_from={date_from}"
        f"_to={date_to}"
        f"_cloud<{args.max_cloud}"
        f"_epsg={args.dst_epsg}"
        f"_res={args.resolution}"
        f"_bands={'+'.join(bands)}"
    )
    run_dir = _make_run_dir(Path(args.out_dir), tag)

    print(f"[1/2] Поиск сцен в {collection} для региона={args.region}...", flush=True)
    max_scenes = args.max_scenes
    search_max_items = args.search_max_items
    items = _stac_search_items(
        collection=collection,
        region_wgs84=region,
        date_from=date_from,
        date_to=date_to,
        max_cloud=args.max_cloud,
        cloud_property=args.cloud_property,
        max_items=search_max_items,
        retries=args.retries,
        retry_delay_sec=args.retry_delay_sec,
    )
    if not items:
        raise RuntimeError("Не найдено сцен по заданным условиям.")

    if max_scenes != 0:
        items = items[:max_scenes]

    print(f"[2/2] Найдено сцен: {len(items)}. Скачивание...", flush=True)
    total_start = time.perf_counter()
    for idx, it in enumerate(items, start=1):
        scene_start = time.perf_counter()
        scene = _build_scene_meta(
            it=it, satellite_key=args.satellite, collection=collection, cloud_property=args.cloud_property
        )
        # Каждая сцена = отдельная папка
        scene_stamp = _slug(scene.datetime_utc[:19].replace("T", "_")) if scene.datetime_utc else f"scene{idx}"
        scene_dir = run_dir / f"scene_{scene_stamp}_{scene.item_id}"
        scene_dir.mkdir(parents=True, exist_ok=True)

        out_tif = scene_dir / "image.tif"
        out_md = scene_dir / "image.md"
        out_json = scene_dir / "image.stac.json"
        out_quick = scene_dir / "quicklook_rgb.png"

        print(f"  [{idx}/{len(items)}] {scene.item_id} -> {scene_dir.name}", flush=True)
        # Скачивание может временно падать на сети/провайдере
        y, x = -1, -1
        last_err: Exception | None = None
        for attempt in range(1, args.retries + 1):
            try:
                y, x = _save_geotiff(
                    item=it,
                    bbox_wgs84=bbox,
                    out_tif=out_tif,
                    bands=bands,
                    dst_epsg=args.dst_epsg,
                    resolution=args.resolution,
                )
                last_err = None
                break
            except Exception as e:  # pragma: no cover
                last_err = e
                if attempt < args.retries:
                    print(f"    retry {attempt}/{args.retries} (ошибка загрузки): {e}", flush=True)
                    time.sleep(args.retry_delay_sec)
                else:
                    print(f"    ошибка загрузки и пропуск сцены: {e}", flush=True)

        if last_err is not None:
            continue
        _make_quicklook_rgb(out_tif, out_quick)
        out_json.write_text(json.dumps(it.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        _write_scene_md(
            md_path=out_md,
            satellite=args.satellite,
            scene=scene,
            region=args.region,
            bbox_wgs84=bbox,
            out_tif=out_tif,
            bands=bands,
            dst_epsg=args.dst_epsg,
            resolution=args.resolution,
        )

        # Мини-лог в конце md
        with out_md.open("a", encoding="utf-8") as f:
            f.write(f"\n\n## Размер\n- {y} x {x}\n")
        scene_elapsed = time.perf_counter() - scene_start
        print(f"    время сцены: {scene_elapsed:.1f} сек", flush=True)

    total_elapsed = time.perf_counter() - total_start
    print(f"Итого время на сцены: {total_elapsed:.1f} сек", flush=True)
    print(f"Готово. Run folder: {run_dir}", flush=True)


def list_command(args: argparse.Namespace) -> None:
    sat_cfg = SATELLITES[args.satellite]
    collection = sat_cfg["collection"]
    region = REGIONS[args.region]
    date_from, date_to = _parse_date_range(args.date_from, args.date_to)
    if args.month:
        date_from, date_to = _parse_month_to_range(args.month)

    items = _stac_search_items(
        collection=collection,
        region_wgs84=region,
        date_from=date_from,
        date_to=date_to,
        max_cloud=args.max_cloud,
        cloud_property=args.cloud_property,
        max_items=args.search_max_items,
    )
    if not items:
        print("Ничего не найдено.")
        return

    total_found = len(items)
    max_scenes = args.max_scenes
    if max_scenes != 0:
        items = items[:max_scenes]

    for it in items:
        dt = str(it.properties.get("datetime") or it.properties.get("start_datetime") or "")
        cc = it.properties.get(args.cloud_property, it.properties.get("eo:cloud_cover"))
        print(f"- {it.id} | {dt} | cloud={cc if cc is not None else 'unknown'}")
    print(f"Итого сцен: {total_found} (collection={collection}, показано {len(items)})")


def build_parser() -> argparse.ArgumentParser:
    prog_name = Path(sys.argv[0]).stem or "download_satellite_rgn"
    parser = argparse.ArgumentParser(
        prog=prog_name,
        formatter_class=argparse.RawTextHelpFormatter,
        description="Скачивание спутниковых снимков (Sentinel-2 / Landsat) из Planetary Computer STAC.\n\n"
        "Команды как у git:\n"
        "  download  — скачать GeoTIFF + md + json + quicklook\n"
        "  list       — просто показать найденные сцены",
        epilog=(
            "Важно: полный список параметров показывается у подкоманд:\n"
            "  python src/download_satellite_rgb.py download --help\n"
            "  python src/download_satellite_rgb.py list --help\n\n"
            "Быстрый пример:\n"
            "  python src/download_satellite_rgb.py download --region sochi_khosta_mzymta_wide "
            "--satellite sentinel2 --date-from 2021-07-01 --date-to 2021-07-07 "
            "--resolution 10 --limit 3 --with-nir"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--region",
        type=str,
        default=DEFAULT_REGION,
        choices=sorted(REGIONS.keys()),
        help="Ключ bbox из config.py (например sochi_khosta_mzymta_wide).",
    )
    common.add_argument(
        "--satellite",
        type=str,
        default=DEFAULT_SATELLITE,
        choices=sorted(SATELLITES.keys()),
        help="Спутник/коллекция из Planetary Computer.\n"
        f"Доступно: {', '.join(sorted(SATELLITES.keys()))}",
    )
    common.add_argument(
        "--month",
        type=str,
        default="",
        help="Быстро: месяц YYYY-MM. Если задан, перезаписывает date-from/date-to.",
    )
    common.add_argument(
        "--date-from",
        type=str,
        default="2000-01-01",
        help="Начало периода: YYYY, YYYY-MM или YYYY-MM-DD (например 2000).",
    )
    common.add_argument(
        "--date-to",
        type=str,
        default="2026-12-31",
        help="Конец периода: YYYY, YYYY-MM или YYYY-MM-DD.",
    )
    common.add_argument(
        "--max-cloud",
        type=float,
        default=20.0,
        help="Макс. облачность для фильтрации (%%).",
    )
    common.add_argument(
        "--cloud-property",
        type=str,
        default="eo:cloud_cover",
        help="Имя поля облачности в STAC (обычно `eo:cloud_cover`).",
    )
    common.add_argument(
        "--dst-epsg",
        type=int,
        default=3857,
        help="Целевая проекция для GeoTIFF (обычно 3857 или другая EPSG).",
    )
    common.add_argument(
        "--resolution",
        type=float,
        default=None,
        help="Разрешение в единицах dst-epsg. Если не задано — берётся нативное для спутника.",
    )
    common.add_argument(
        "--search-max-items",
        type=int,
        default=10000,
        help="Лимит item'ов, которые STAC отдаст для поиска (важно при скачивании «всё начиная с 2000»).",
    )
    common.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Сколько ретраев делать при сетевых сбоях (STAC поиск и чтение band-файлов).",
    )
    common.add_argument(
        "--retry-delay-sec",
        type=float,
        default=3.0,
        help="Пауза между ретраями, секунды.",
    )
    common.add_argument(
        "--out-dir",
        type=str,
        default="data/raw",
        help="Базовая папка, куда будут созданы run/scene папки.",
    )
    common.add_argument(
        "--with-nir",
        action="store_true",
        help="Добавить NIR канал (например B08 для Sentinel-2 или nir08 для Landsat).",
    )
    common.add_argument(
        "--rgb-bands",
        type=str,
        default="",
        help="Переопределить RGB band-ы: формат 'R,G,B' (через запятую).",
    )
    common.add_argument(
        "--nir-band",
        type=str,
        default="",
        help="Переопределить NIR band-имя.",
    )

    dl = sub.add_parser(
        "download",
        parents=[common],
        help="Скачать найденные сцены и сохранить в отдельные папки для каждой сцены.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    dl.add_argument(
        "--max-scenes",
        "--limit",
        dest="max_scenes",
        type=int,
        default=1,
        help="Сколько сцен скачать.\nСиноним: --limit.\n0 = все найденные (может занять очень много времени и диска).",
    )
    dl.set_defaults(func=download_command)

    ls = sub.add_parser(
        "list",
        parents=[common],
        help="Только список найденных сцен (без скачивания GeoTIFF).",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    ls.add_argument("--max-scenes", "--limit", dest="max_scenes", type=int, default=10, help="Сколько сцен вывести. 0 = всё.")
    ls.set_defaults(func=list_command)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
