# -*- coding: utf-8 -*-
"""Общие гео-утилиты для регионов из config.REGIONS (bbox / polygon → STAC)."""


def region_bbox(region: dict) -> dict:
    """Возвращает south/north/west/east в WGS84 из явного bbox или ограничивающего прямоугольника полигона."""
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


def region_polygon(region: dict) -> dict | None:
    """GeoJSON Polygon для STAC intersects, если задан в регионе."""
    polygon = region.get("polygon")
    if isinstance(polygon, dict) and polygon.get("type") == "Polygon":
        return polygon
    return None
