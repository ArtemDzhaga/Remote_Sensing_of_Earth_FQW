# -*- coding: utf-8 -*-
"""Подготовка признаков: slope, тайлы, стеки."""

from dem.features.slope import slope_from_dem
from dem.features.stack import build_feature_stack
from dem.features.tiling import extract_patches

__all__ = ["build_feature_stack", "extract_patches", "slope_from_dem"]
