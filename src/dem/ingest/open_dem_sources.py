# -*- coding: utf-8 -*-
"""
Реестр открытых источников DEM (через OpenTopography Global DEM API).

Все перечисленные типы запрашиваются одним и тем же HTTP API (см. opentopography_client).
Для региона Кавказа/Sochi основные кандидаты: COP30 (Copernicus DSM) и SRTMGL1.
"""
from typing import TypedDict


class DemSourceMeta(TypedDict):
    demtype: str
    label: str
    resolution_m: str
    notes: str


# Ключи — короткие имена для CLI; demtype — параметр OpenTopography API
OPEN_DEM_SOURCES: dict[str, DemSourceMeta] = {
    "cop30": {
        "demtype": "COP30",
        "label": "Copernicus Global DSM 30m",
        "resolution_m": "~30",
        "notes": "Часто предпочтителен в горах; DSM (включая крону леса).",
    },
    "srtm30": {
        "demtype": "SRTMGL1",
        "label": "SRTM GL1 30m",
        "resolution_m": "~30",
        "notes": "Классический DTM/рельеф; хорош как вторая эталонная сетка для сравнения.",
    },
    "nasadem": {
        "demtype": "NASADEM",
        "label": "NASADEM Global DEM",
        "resolution_m": "~30",
        "notes": "Улучшения относительно SRTM в ряде регионов.",
    },
    "aw3d30": {
        "demtype": "AW3D30",
        "label": "ALOS AW3D30",
        "resolution_m": "~30",
        "notes": "Альтернативный глобальный 30m продукт.",
    },
    "srtm90": {
        "demtype": "SRTMGL3",
        "label": "SRTM GL3 90m",
        "resolution_m": "~90",
        "notes": "Грубый ориентир / быстрые прогоны.",
    },
}

# Набор по умолчанию для «эталонного пакета» в горах: DSM + классический рельеф
DEFAULT_REFERENCE_DEM_ALIASES = ("cop30", "srtm30")


def list_sources_table() -> str:
    lines = ["alias | demtype (API) | описание", "--- | --- | ---"]
    for alias, meta in sorted(OPEN_DEM_SOURCES.items()):
        lines.append(f"`{alias}` | `{meta['demtype']}` | {meta['label']}: {meta['notes']}")
    return "\n".join(lines)
