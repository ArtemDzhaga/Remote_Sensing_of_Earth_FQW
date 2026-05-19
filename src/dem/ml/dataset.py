# -*- coding: utf-8 -*-
"""PyTorch Dataset поверх `.npz` патчей."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np


def _is_npz_payload(path: Path) -> bool:
    """Отфильтровать macOS AppleDouble `._*.npz` и битые файлы."""

    if path.name.startswith("._"):
        return False
    try:
        with path.open("rb") as f:
            return f.read(4) == b"PK\x03\x04"
    except OSError:
        return False


class DemPatchDataset:  # pragma: no cover - требует torch runtime
    """Загрузка патчей, созданных `dem.features.stack`.

    `.npz` должен содержать:
    - `x`: `(channels, height, width)`
    - `y`: `(height, width)` или `(1, height, width)`
    """

    def __init__(self, root: str | Path, *, augment: bool = False) -> None:
        self.root = Path(root)
        if self.root.is_file():
            self.files = [self.root] if _is_npz_payload(self.root) else []
        else:
            self.files = sorted(p for p in self.root.glob("*.npz") if _is_npz_payload(p))
        if not self.files:
            raise FileNotFoundError(f"Нет .npz патчей в {self.root}")
        self.augment = augment

    def __len__(self) -> int:
        return len(self.files)

    def _augment(self, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if not self.augment:
            return x, y
        if np.random.rand() < 0.5:
            x = np.flip(x, axis=-1)
            y = np.flip(y, axis=-1)
        if np.random.rand() < 0.5:
            x = np.flip(x, axis=-2)
            y = np.flip(y, axis=-2)
        k = int(np.random.randint(0, 4))
        if k:
            x = np.rot90(x, k=k, axes=(-2, -1))
            y = np.rot90(y, k=k, axes=(-2, -1))
        return np.ascontiguousarray(x), np.ascontiguousarray(y)

    def __getitem__(self, idx: int) -> dict[str, Any]:
        import torch

        with np.load(self.files[idx]) as z:
            x = z["x"].astype("float32")
            y = z["y"].astype("float32")
            row = int(z["row"]) if "row" in z else -1
            col = int(z["col"]) if "col" in z else -1
        if y.ndim == 2:
            y = y[None, ...]
        x, y = self._augment(x, y)
        return {
            "x": torch.from_numpy(x),
            "y": torch.from_numpy(y),
            "path": str(self.files[idx]),
            "row": row,
            "col": col,
        }
