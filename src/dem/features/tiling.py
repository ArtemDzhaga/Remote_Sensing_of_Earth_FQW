# -*- coding: utf-8 -*-
"""Нарезка массивов на патчи с перекрытием."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PatchWindow:
    row: int
    col: int
    size: int


def iter_windows(height: int, width: int, *, patch_size: int = 256, overlap: int = 32) -> Iterator[PatchWindow]:
    """Окна тайлинга, включая крайние окна у правой/нижней границы."""

    if patch_size <= 0:
        raise ValueError("patch_size должен быть > 0")
    if overlap < 0 or overlap >= patch_size:
        raise ValueError("overlap должен быть в диапазоне [0, patch_size)")
    if height < patch_size or width < patch_size:
        return

    stride = patch_size - overlap
    rows = list(range(0, height - patch_size + 1, stride))
    cols = list(range(0, width - patch_size + 1, stride))
    if rows[-1] != height - patch_size:
        rows.append(height - patch_size)
    if cols[-1] != width - patch_size:
        cols.append(width - patch_size)

    for r in rows:
        for c in cols:
            yield PatchWindow(row=r, col=c, size=patch_size)


def extract_patches(
    array: np.ndarray,
    *,
    patch_size: int = 256,
    overlap: int = 32,
    min_valid_fraction: float = 0.8,
) -> list[tuple[PatchWindow, np.ndarray]]:
    """Вернуть патчи из 2D/3D массива.

    Для 3D ожидается форма ``(channels, height, width)``.
    Валидность считается по конечным значениям во всех каналах.
    """

    if array.ndim == 2:
        height, width = array.shape
        spatial = array
    elif array.ndim == 3:
        _, height, width = array.shape
        spatial = np.all(np.isfinite(array), axis=0)
    else:
        raise ValueError("array должен быть 2D или 3D (channels, height, width)")

    out: list[tuple[PatchWindow, np.ndarray]] = []
    for win in iter_windows(height, width, patch_size=patch_size, overlap=overlap):
        if array.ndim == 2:
            patch = array[win.row : win.row + win.size, win.col : win.col + win.size]
            valid = np.isfinite(patch)
        else:
            patch = array[:, win.row : win.row + win.size, win.col : win.col + win.size]
            valid = spatial[win.row : win.row + win.size, win.col : win.col + win.size]
        if float(valid.mean()) >= min_valid_fraction:
            out.append((win, patch.copy()))
    return out
