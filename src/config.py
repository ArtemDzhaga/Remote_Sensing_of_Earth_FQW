# -*- coding: utf-8 -*-
"""Конфигурация регионов и наборов данных."""

"""
Регионы под DEM/спутниковые снимки.

Формат bbox: WGS84 (EPSG:4326): south, north, west, east
"""

# Кандидаты вокруг Сочи с выраженным горным рельефом + реки + застройка.
# Важно: для ML/валидации удобнее держать bbox умеренным (не слишком огромным),
# чтобы 10м Sentinel-2/DEM нормально обрабатывались на ноутбуке.
REGIONS = {
    # 1) Широкий охват: побережье + долины Хосты и Мзымты + предгорья
    "sochi_khosta_mzymta_wide": {"south": 43.35, "north": 43.75, "west": 39.75, "east": 40.15},
    # 2) Долина Мзымты до Красной Поляны (более «горный» рельеф, река, застройка)
    "sochi_mzymta_krasnaya_polyana": {"south": 43.50, "north": 43.74, "west": 39.90, "east": 40.35},
    # 3) Район Хосты и Агурских ущелий (горный рельеф ближе к побережью)
    "sochi_khosta_agura": {"south": 43.48, "north": 43.62, "west": 39.78, "east": 39.95},
    # 4) Небольшой полигон у Хосты и Мзымты (точный контур)
    "sochi_khosta_mzymta_small": {
        "south": 43.378606,
        "north": 43.545557,
        "west": 39.914017,
        "east": 40.060959,
        "polygon": {
            "type": "Polygon",
            "coordinates": [
                [
                    [39.914017, 43.411902],
                    [39.987488, 43.378606],
                    [40.022507, 43.445443],
                    [40.046539, 43.497758],
                    [40.060959, 43.531123],
                    [39.973755, 43.545557],
                    [39.914017, 43.411902],
                ]
            ],
        },
    },
}

# Регион по умолчанию на первом этапе
# По твоему требованию держимся исходного района между Хостой и Мзымтой
DEFAULT_REGION = "sochi_khosta_mzymta_wide"

# Доступные глобальные DEM в OpenTopography (30 м лучше подходят для горного рельефа).
DEMTYPE_CHOICES = (
    "SRTMGL1",   # SRTM GL1 30m
    "COP30",     # Copernicus Global DSM 30m
    "NASADEM",   # NASADEM Global DEM
    "AW3D30",    # ALOS World 3D 30m
    "SRTMGL3",   # SRTM GL3 90m
)

# --- Спутники для скачивания оптических снимков (из Planetary Computer STAC) ---
#
# Примечание: имена band-ов для odc-stac могут отличаться.
# Поэтому скрипт позволяет переопределить band-ы CLI-параметрами.
SATELLITES = {
    # Sentinel-2 MSI L2A: RGB обычно B04/B03/B02, NIR — B08
    "sentinel2": {
        "collection": "sentinel-2-l2a",
        "rgb_bands": ["B04", "B03", "B02"],
        "nir_band": "B08",
        "native_resolution": 10.0,
    },
    # Landsat Collection 2 Level 2: band-алиасы у одних и тех же коллекций в STAC обычно red/green/blue и nir08
    # Это чаще всего работает для odc-stac. Если нет — переопределите через CLI.
    "landsat8": {
        "collection": "landsat-8-c2-l2",
        "rgb_bands": ["red", "green", "blue"],
        "nir_band": "nir08",
        "native_resolution": 30.0,
    },
    "landsat9": {
        "collection": "landsat-9-c2-l2",
        "rgb_bands": ["red", "green", "blue"],
        "nir_band": "nir08",
        "native_resolution": 30.0,
    },
    "landsat7": {
        "collection": "landsat-7-c2-l2",
        "rgb_bands": ["red", "green", "blue"],
        "nir_band": "nir08",
        "native_resolution": 30.0,
    },
}

DEFAULT_SATELLITE = "sentinel2"

# --- Всепогодные SAR-спутники ---
SAR_SATELLITES = {
    # Radiometrically Terrain Corrected Sentinel-1 (VV/VH), C-band SAR
    "sentinel1_rtc": {
        "collection": "sentinel-1-rtc",
        "bands": ["vv", "vh"],
        "native_resolution": 10.0,
    }
}

DEFAULT_SAR_SATELLITE = "sentinel1_rtc"
