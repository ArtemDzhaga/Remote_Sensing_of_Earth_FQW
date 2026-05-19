# -*- coding: utf-8 -*-
"""Функции потерь для обучения DEM-коррекции."""

from __future__ import annotations


def slope_aware_mae(pred, target, slope, *, alpha: float = 1.0, valid_mask=None):
    """MAE с повышенным весом на крутых склонах.

    Формула: ``mean(abs(pred-target) * (1 + alpha * abs(slope)))``.
    `slope` ожидается нормированным или в радианах/относительных единицах.
    """

    import torch

    err = torch.abs(pred - target)
    weight = 1.0 + alpha * torch.abs(slope)
    loss = err * weight
    if valid_mask is not None:
        loss = loss[valid_mask]
    return loss.mean()


def masked_mae(pred, target, valid_mask=None):
    """Обычная MAE с опциональной маской."""

    import torch

    loss = torch.abs(pred - target)
    if valid_mask is not None:
        loss = loss[valid_mask]
    return torch.mean(loss)


# Backward-compatible alias для ранних набросков.
slope_aware_loss = slope_aware_mae
