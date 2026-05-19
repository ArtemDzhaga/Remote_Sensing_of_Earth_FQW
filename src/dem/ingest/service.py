# -*- coding: utf-8 -*-
"""
Единая точка входа для загрузки SAR:
- stac — Sentinel-1 RTC через Planetary Computer (основной путь для sochi_khosta_mzymta_small);
- external — образцы Indigo / Capella с AWS Open Data (см. sar_external_samples).
"""
from __future__ import annotations

import argparse
import sys

def _run_stac(argv: list[str]) -> None:
    from dem.ingest import sar_rtc_stac as sra

    sra.main_argv(argv)


def _run_external(argv: list[str]) -> None:
    from dem.ingest import samples as ext

    p = ext.build_parser()
    args = p.parse_args(argv)
    args.func(args)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Сервис загрузки SAR: stac (PC) | external (образцы AWS/DagsHub-связанные датасеты)."
    )
    sub = parser.add_subparsers(dest="domain", required=True)

    st = sub.add_parser("stac", help="Проброс в dem.ingest.sar_rtc_stac (list | download).")
    st.add_argument(
        "stac_argv",
        nargs=argparse.REMAINDER,
        help="Аргументы после `stac`, например: download --region sochi_khosta_mzymta_small --month 2024-06 --limit 1",
    )

    ex = sub.add_parser("external", help="Образцы Indigo/Capella (см. dem.ingest.samples --help).")
    ex.add_argument(
        "external_argv",
        nargs=argparse.REMAINDER,
        help="Например: indigo-sample  или  capella-sample --scan-max-keys 2000",
    )

    args = parser.parse_args()
    if args.domain == "stac":
        child = list(args.stac_argv)
        if child and child[0] == "--":
            child = child[1:]
        if not child:
            child = ["--help"]
        _run_stac(child)
    else:
        child = list(args.external_argv)
        if child and child[0] == "--":
            child = child[1:]
        if not child:
            child = ["--help"]
        _run_external(child)


if __name__ == "__main__":
    main()
