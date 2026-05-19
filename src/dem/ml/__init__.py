# -*- coding: utf-8 -*-
"""ML: подготовка датасета, обучение и инференс DEM-коррекции."""

from dem.ml.dataset import DemPatchDataset
from dem.ml.loss import slope_aware_loss
from dem.ml.model import build_model

__all__ = ["DemPatchDataset", "build_model", "slope_aware_loss"]
