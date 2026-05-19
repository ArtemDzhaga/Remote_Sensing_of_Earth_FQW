# -*- coding: utf-8 -*-
"""
Дополнительные открытые SAR-источники (образцы с AWS Open Data), связанные с датасетами на DagsHub.

Важно по географии:
- Sentinel-1 RTC Indigo — покрытие CONUS (США), не пересекает Сочи. Используется как формат RTC/COG
  для обучения и проверки кода; для региона sochi_khosta_mzymta_small основной источник — STAC
  (sentinel-1-rtc на Planetary Computer).
- Capella Open Data — глобальные открытые сцены в s3://capella-open-data (подбор пересечения с bbox
  делается перебором префиксов в пределах лимита; для продакшена лучше STAC-индекс).

Зависимости: boto3 (анонимный доступ к публичным бакетам).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dem.io.layout import data_raw, resolve_out_dir  # noqa: E402

# Документированный пример из официальной документации Indigo (CONUS)
INDIGO_SAMPLE_KEY = (
    "tiles/RTC/1/IW/14/T/PN/2020/S1A_20200801_14TPN_ASC/Gamma0_VV.tif"
)
INDIGO_BUCKET = "sentinel-s1-rtc-indigo"
CAPPELLA_BUCKET = "capella-open-data"
CAPPELLA_PREFIX = "data/"


def _s3_client():
    try:
        import boto3
        from botocore import UNSIGNED
        from botocore.config import Config
    except ImportError as e:
        raise RuntimeError("Установите boto3: pip install boto3") from e

    return boto3.client("s3", config=Config(signature_version=UNSIGNED), region_name="us-west-2")


def download_s3_object(bucket: str, key: str, dest: Path) -> None:
    client = _s3_client()
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"Скачивание s3://{bucket}/{key} → {dest}")
    client.download_file(bucket, key, str(dest))


def cmd_indigo_sample(args: argparse.Namespace) -> None:
    base = resolve_out_dir(args.dest, lambda: data_raw() / "external" / "sar_indigo_sample")
    dest = base / "Gamma0_VV.tif"
    download_s3_object(INDIGO_BUCKET, INDIGO_SAMPLE_KEY, dest)
    print(
        "Готово. Это COG в CONUS (не Сочи). Для Хоста/Мзымты используйте:\n"
        "  python -m dem.ingest.service stac download --region sochi_khosta_mzymta_small ..."
    )


def cmd_capella_sample(args: argparse.Namespace) -> None:
    client = _s3_client()
    dest_dir = resolve_out_dir(args.dest, lambda: data_raw() / "external" / "sar_capella_sample")
    dest_dir.mkdir(parents=True, exist_ok=True)
    resp = client.list_objects_v2(Bucket=CAPPELLA_BUCKET, Prefix=CAPPELLA_PREFIX, MaxKeys=args.scan_max_keys)
    candidates: list[str] = []
    for obj in resp.get("Contents") or []:
        k = obj.get("Key") or ""
        if k.lower().endswith((".tif", ".tiff", ".cog")):
            candidates.append(k)
    if not candidates:
        raise SystemExit(
            "Не найдено .tif в первых ключах листинга. Увеличьте --scan-max-keys или скачайте по STAC:\n"
            "  https://capella-open-data.s3.us-west-2.amazonaws.com/index.html"
        )
    key = candidates[0]
    name = key.rsplit("/", 1)[-1]
    download_s3_object(CAPPELLA_BUCKET, key, dest_dir / name)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Образцы SAR с AWS Open Data (Indigo RTC CONUS, Capella).")
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("indigo-sample", help="Скачать один Gamma0_VV COG из sentinel-s1-rtc-indigo (CONUS).")
    i.add_argument(
        "--dest",
        type=str,
        default="",
        help="Папка; пусто = outputs/<дата>/data/raw/external/sar_indigo_sample.",
    )
    i.set_defaults(func=cmd_indigo_sample)

    c = sub.add_parser("capella-sample", help="Скачать первый найденный GeoTIFF из capella-open-data (листинг).")
    c.add_argument(
        "--dest",
        type=str,
        default="",
        help="Папка; пусто = outputs/<дата>/data/raw/external/sar_capella_sample.",
    )
    c.add_argument("--scan-max-keys", type=int, default=500)
    c.set_defaults(func=cmd_capella_sample)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
