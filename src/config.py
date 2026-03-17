# -*- coding: utf-8 -*-
"""Конфигурация регионов и наборов данных."""

# Район рек Хоста и Мзымта (Краснодарский край, окрестности Сочи).
# Горная местность с перепадом высот, реки, жилая застройка вдоль побережья и в долинах.
# WGS84: south, north, west, east.
REGION_SOCHI_KHOSTA_MZYMTA = {
    "south": 43.35,
    "north": 43.75,
    "west": 39.75,
    "east": 40.15,
}

# Доступные глобальные DEM в OpenTopography (30 м лучше подходят для горного рельефа).
DEMTYPE_CHOICES = (
    "SRTMGL1",   # SRTM GL1 30m
    "COP30",     # Copernicus Global DSM 30m
    "NASADEM",   # NASADEM Global DEM
    "AW3D30",    # ALOS World 3D 30m
    "SRTMGL3",   # SRTM GL3 90m
)
