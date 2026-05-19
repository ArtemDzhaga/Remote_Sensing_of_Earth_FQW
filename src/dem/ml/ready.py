# -*- coding: utf-8 -*-
"""Проверка готовности ML-датасета."""

from __future__ import annotations

import argparse
from pathlib import Path

from dem.ml.dataset import DemPatchDataset


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Проверить, что ML-датасет содержит читаемые NPZ-патчи.")
    p.add_argument("--data-dir", required=True, help="Папка датасета с train/val/test или .npz.")
    return p


def main() -> None:
    args = build_parser().parse_args()
    root = Path(args.data_dir)
    for split in ("train", "val", "test"):
        d = root / split
        if d.is_dir():
            ds = DemPatchDataset(d)
            print(f"{split}: {len(ds)} patches")
    if not any((root / split).is_dir() for split in ("train", "val", "test")):
        ds = DemPatchDataset(root)
        print(f"patches: {len(ds)}")


if __name__ == "__main__":
    main()
