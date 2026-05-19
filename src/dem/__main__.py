# -*- coding: utf-8 -*-
"""Точка входа ``python -m dem``: без аргументов — справка; с аргументами — ``dem.cli``."""
from __future__ import annotations

import sys


def _print_short_help() -> None:
    print(
        """dem — пакет построения и улучшения ЦМР.

Справка по единому CLI:
  python -m dem --help

Примеры модулей:
  python -m dem.ingest.service stac download --region sochi_khosta_mzymta_small --month 2024-06 --limit 1
  python -m dem.viz.validate_dem <path/to/dem.tif>
  python -m dem.insar.pipeline doctor

Полный список: docs/handbook.md · дерево каталогов: README.md
"""
    )


def main() -> None:
    extra = sys.argv[1:]
    if extra:
        from dem.cli import dispatch

        raise SystemExit(dispatch(extra))
    _print_short_help()


if __name__ == "__main__":
    main()
