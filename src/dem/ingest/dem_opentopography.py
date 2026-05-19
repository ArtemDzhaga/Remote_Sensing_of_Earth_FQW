# -*- coding: utf-8 -*-
"""
Фасад «DEM через OpenTopography»: однослойная загрузка и репроекция.

Для пакета нескольких слоёв и manifest см. ``dem.ingest.reference_dem``.
"""

from __future__ import annotations

from dem.ingest import opentopography_client as _client

# Экспорт основных символов для скриптов
from dem.ingest.opentopography_client import (
    basic_stats,
    download_dummy_placeholder,
    download_opentopography,
    ensure_dir,
    reproject_to_epsg,
)

__all__ = [
    "basic_stats",
    "download_dummy_placeholder",
    "download_opentopography",
    "ensure_dir",
    "reproject_to_epsg",
]


def main() -> None:
    _client.main()


if __name__ == "__main__":
    main()
