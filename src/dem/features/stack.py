# -*- coding: utf-8 -*-
"""Сборка стека каналов для PyTorch Dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import rasterio

from dem.features.tiling import extract_patches
from dem.io.layout import data_processed, resolve_out_dir


def _read_band(path: Path | str) -> tuple[np.ndarray, dict]:
    with rasterio.open(path) as src:
        arr = src.read(1, masked=True).filled(np.nan).astype("float32")
        profile = src.profile.copy()
    return arr, profile


def normalize_channel(arr: np.ndarray, *, eps: float = 1e-6) -> tuple[np.ndarray, dict[str, float]]:
    valid = np.isfinite(arr)
    if not valid.any():
        return arr.astype("float32"), {"mean": 0.0, "std": 1.0}
    mean = float(np.nanmean(arr))
    std = float(np.nanstd(arr))
    if std < eps:
        std = 1.0
    return ((arr - mean) / std).astype("float32"), {"mean": mean, "std": std}


def build_feature_stack(
    channels: list[Path | str],
    *,
    normalize: bool = True,
) -> tuple[np.ndarray, dict]:
    """Собрать ``(C, H, W)`` из одно-канальных GeoTIFF с одинаковой сеткой."""

    arrays: list[np.ndarray] = []
    stats: dict[str, dict[str, float]] = {}
    base_profile: dict | None = None

    for i, path in enumerate(channels):
        arr, profile = _read_band(path)
        if base_profile is None:
            base_profile = profile
        elif arr.shape != arrays[0].shape:
            raise ValueError(f"Размер {path}={arr.shape} не совпадает с первым каналом {arrays[0].shape}")
        if normalize:
            arr, st = normalize_channel(arr)
        else:
            st = {"mean": 0.0, "std": 1.0}
        arrays.append(arr)
        stats[f"ch{i}:{Path(path).name}"] = st

    return np.stack(arrays, axis=0).astype("float32"), {"channels": [str(p) for p in channels], "stats": stats}


def write_npz_patches(
    *,
    channels: list[Path | str],
    target: Path | str,
    out_dir: Path | str,
    patch_size: int = 256,
    overlap: int = 32,
    min_valid_fraction: float = 0.8,
    target_mode: str = "dem",
    base_channel_index: int = 0,
    target_invalid_values: list[float] | None = None,
) -> Path:
    """Собрать feature stack + target и сохранить патчи `.npz`."""

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    x, meta = build_feature_stack(channels)
    y, _ = _read_band(target)
    if y.shape != x.shape[1:]:
        raise ValueError(f"target shape {y.shape} != stack shape {x.shape[1:]}")
    if target_mode == "residual":
        if base_channel_index < 0 or base_channel_index >= len(channels):
            raise ValueError(f"base_channel_index={base_channel_index} вне диапазона каналов")
        base_raw, _ = _read_band(channels[base_channel_index])
        if base_raw.shape != y.shape:
            raise ValueError(f"base channel shape {base_raw.shape} != target shape {y.shape}")
        y = (y - base_raw).astype("float32")
    elif target_mode != "dem":
        raise ValueError("target_mode должен быть 'dem' или 'residual'")

    inv = target_invalid_values or []
    target_ok = np.isfinite(y)
    for v in inv:
        target_ok &= y != float(v)

    samples = 0
    manifest = {
        "channels": meta["channels"],
        "target": str(target),
        "patch_size": patch_size,
        "overlap": overlap,
        "min_valid_fraction": min_valid_fraction,
        "target_mode": target_mode,
        "base_channel_index": base_channel_index,
        "target_invalid_values": inv,
        "normalization": meta["stats"],
        "patches": [],
    }

    for win, x_patch in extract_patches(
        x,
        patch_size=patch_size,
        overlap=overlap,
        min_valid_fraction=min_valid_fraction,
    ):
        y_patch = y[win.row : win.row + win.size, win.col : win.col + win.size]
        ok_patch = target_ok[win.row : win.row + win.size, win.col : win.col + win.size]
        if float(ok_patch.mean()) < min_valid_fraction:
            continue
        name = f"patch_r{win.row:05d}_c{win.col:05d}.npz"
        path = out_dir / name
        np.savez_compressed(path, x=x_patch.astype("float32"), y=y_patch.astype("float32"), row=win.row, col=win.col)
        manifest["patches"].append({"file": name, "row": win.row, "col": win.col})
        samples += 1

    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "normalization.json").write_text(json.dumps(meta["stats"], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"patches: {samples}")
    return out_dir


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Собрать NPZ-патчи из растровых каналов и target DEM.")
    p.add_argument("--channel", action="append", required=True, help="GeoTIFF канал; можно повторять.")
    p.add_argument("--target", required=True, help="GeoTIFF target DEM.")
    p.add_argument("--out-dir", default="", help="Пусто = outputs/<дата>/data/processed/dataset_v1")
    p.add_argument("--patch-size", type=int, default=256)
    p.add_argument("--overlap", type=int, default=32)
    p.add_argument("--min-valid-fraction", type=float, default=0.8)
    p.add_argument("--target-mode", choices=["dem", "residual"], default="dem")
    p.add_argument("--base-channel-index", type=int, default=0, help="Канал baseline DEM для residual target.")
    p.add_argument(
        "--target-invalid-value",
        action="append",
        type=float,
        default=None,
        help=(
            "Значение таргета, считающееся дырой/нет данных (повторять). "
            "Например после warp без nodata часто везде 0 — тогда: --target-invalid-value 0"
        ),
    )
    return p


def main() -> None:
    args = build_parser().parse_args()
    out_dir = resolve_out_dir(args.out_dir, lambda: data_processed() / "dataset_v1")
    result = write_npz_patches(
        channels=[Path(p) for p in args.channel],
        target=Path(args.target),
        out_dir=out_dir,
        patch_size=args.patch_size,
        overlap=args.overlap,
        min_valid_fraction=args.min_valid_fraction,
        target_mode=args.target_mode,
        base_channel_index=args.base_channel_index,
        target_invalid_values=list(args.target_invalid_value or []),
    )
    print(f"done: {result}")


if __name__ == "__main__":
    main()
