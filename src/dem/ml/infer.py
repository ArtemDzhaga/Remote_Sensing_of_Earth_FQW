# -*- coding: utf-8 -*-
"""Тайловый инференс DEM-модели в GeoTIFF."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject

from dem.features.tiling import iter_windows
from dem.ml.model import build_model, default_device


def _read_channel(path: Path, reference_grid: Path | None = None) -> tuple[np.ndarray, dict]:
    with rasterio.open(path) as src:
        if reference_grid is None:
            arr = src.read(1, masked=True).filled(np.nan).astype("float32")
            profile = src.profile.copy()
            return arr, profile
        with rasterio.open(reference_grid) as ref:
            arr = np.full((ref.height, ref.width), np.nan, dtype="float32")
            reproject(
                source=src.read(1, masked=True).filled(np.nan).astype("float32"),
                destination=arr,
                src_transform=src.transform,
                src_crs=src.crs,
                src_nodata=src.nodata,
                dst_transform=ref.transform,
                dst_crs=ref.crs,
                dst_nodata=np.nan,
                resampling=Resampling.bilinear,
            )
            profile = ref.profile.copy()
    return arr, profile


def _load_stats(path: Path | None, channels: list[Path]) -> list[dict[str, float]]:
    if path is None:
        return [{"mean": 0.0, "std": 1.0} for _ in channels]
    raw = json.loads(path.read_text(encoding="utf-8"))
    # dem.features.stack пишет dict с ключами ch0:name, ch1:name ...
    if isinstance(raw, dict) and "stats" in raw:
        raw = raw["stats"]
    if not isinstance(raw, dict):
        raise ValueError(f"Некорректный normalization json: {path}")
    ordered = [raw[k] for k in sorted(raw.keys(), key=lambda s: int(s.split(":", 1)[0].replace("ch", "")))]
    if len(ordered) != len(channels):
        raise ValueError(f"В normalization {len(ordered)} каналов, а передано {len(channels)}")
    return ordered


def _stack_channels(
    channels: list[Path],
    stats: list[dict[str, float]],
    reference_grid: Path | None = None,
) -> tuple[np.ndarray, list[np.ndarray], dict]:
    arrays: list[np.ndarray] = []
    raw_arrays: list[np.ndarray] = []
    profile: dict | None = None
    shape: tuple[int, int] | None = None
    for path, st in zip(channels, stats):
        arr, prof = _read_channel(path, reference_grid)
        if shape is None:
            shape = arr.shape
            profile = prof
        elif arr.shape != shape:
            raise ValueError(f"Размер {path}={arr.shape} не совпадает с первым каналом {shape}")
        std = float(st.get("std", 1.0)) or 1.0
        mean = float(st.get("mean", 0.0))
        raw_arrays.append(arr)
        arrays.append(((arr - mean) / std).astype("float32"))
    return np.stack(arrays, axis=0), raw_arrays, profile or {}


def _blend_weight(size: int) -> np.ndarray:
    """Плавное окно для склейки тайлов без видимой сетки на границах патчей."""

    if size <= 2:
        return np.ones((size, size), dtype="float32")
    one = np.hanning(size).astype("float32")
    # Ненулевые края важны для внешней рамки растра, где нет соседнего тайла.
    one = np.maximum(one, 0.05)
    weight = np.outer(one, one).astype("float32")
    return weight / float(np.max(weight))


def _write_geotiff(path: Path, arr: np.ndarray, profile: dict, *, dtype: str = "float32", nodata=np.nan) -> None:
    out_profile = profile.copy()
    out_profile.update(dtype=dtype, count=1, nodata=nodata, compress="deflate")
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **out_profile) as dst:
        dst.write(arr.astype(dtype), 1)


def _pad_to_multiple(x: np.ndarray, multiple: int = 32) -> tuple[np.ndarray, tuple[int, int]]:
    _, height, width = x.shape
    pad_h = (multiple - height % multiple) % multiple
    pad_w = (multiple - width % multiple) % multiple
    if pad_h == 0 and pad_w == 0:
        return x, (height, width)
    padded = np.pad(x, ((0, 0), (0, pad_h), (0, pad_w)), mode="edge")
    return padded.astype("float32"), (height, width)


def _predict_full(model, x: np.ndarray, device: str, *, multiple: int = 32) -> np.ndarray:
    import torch

    clean = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0).astype("float32")
    padded, (height, width) = _pad_to_multiple(clean, multiple=multiple)
    with torch.no_grad():
        y = model(torch.from_numpy(padded[None]).to(device)).detach().cpu().numpy()[0, 0]
    return y[:height, :width].astype("float32")


def _predict_tiled(model, x: np.ndarray, device: str, *, patch_size: int, overlap: int) -> np.ndarray:
    import torch

    _, height, width = x.shape
    pred_sum = np.zeros((height, width), dtype="float32")
    pred_weight = np.zeros((height, width), dtype="float32")
    blend = _blend_weight(patch_size)

    windows = list(iter_windows(height, width, patch_size=patch_size, overlap=overlap))
    if not windows:
        return _predict_full(model, x, device, multiple=32)

    with torch.no_grad():
        for win in windows:
            patch = np.nan_to_num(x[:, win.row : win.row + win.size, win.col : win.col + win.size], nan=0.0)
            y = model(torch.from_numpy(patch[None]).to(device)).detach().cpu().numpy()[0, 0]
            pred_sum[win.row : win.row + win.size, win.col : win.col + win.size] += y.astype("float32") * blend
            pred_weight[win.row : win.row + win.size, win.col : win.col + win.size] += blend
    return pred_sum / np.maximum(pred_weight, 1e-6)


def infer_geotiff(
    *,
    checkpoint: Path,
    channels: list[Path],
    out_tif: Path,
    normalization: Path | None = None,
    reference_grid: Path | None = None,
    fill_tif: Path | None = None,
    filled_out_tif: Path | None = None,
    mask_out_tif: Path | None = None,
    patch_size: int = 256,
    overlap: int = 32,
    mode: str = "full",
    device: str = "auto",
    residual_base_channel: int = -1,
) -> Path:
    import torch

    stats = _load_stats(normalization, channels)
    x, raw_channels, profile = _stack_channels(channels, stats, reference_grid)
    _, height, width = x.shape
    device = default_device() if device == "auto" else device

    ckpt = torch.load(checkpoint, map_location=device)
    in_channels = int(ckpt.get("in_channels", x.shape[0]))
    model = build_model(
        in_channels=in_channels,
        classes=1,
        encoder_name=str(ckpt.get("encoder_name") or "resnet18"),
        encoder_weights=ckpt.get("encoder_weights"),
        prefer_smp=bool(ckpt.get("prefer_smp", True)),
        require_smp=bool(ckpt.get("prefer_smp", True)),
    ).to(device)
    model.load_state_dict(ckpt["model"])
    model.eval()

    if mode == "full":
        pred = _predict_full(model, x, device, multiple=32)
    elif mode == "tile":
        pred = _predict_tiled(model, x, device, patch_size=patch_size, overlap=overlap)
    else:
        raise ValueError("mode должен быть одним из: full, tile")
    if residual_base_channel >= 0:
        if residual_base_channel >= len(raw_channels):
            raise ValueError(f"residual_base_channel={residual_base_channel} вне диапазона каналов")
        pred = raw_channels[residual_base_channel] + pred
    valid_output = np.isfinite(pred)
    _write_geotiff(out_tif, pred, profile)
    if mask_out_tif is not None:
        _write_geotiff(mask_out_tif, valid_output.astype("uint8"), profile, dtype="uint8", nodata=0)
    if fill_tif is not None and filled_out_tif is not None:
        fill_arr, _ = _read_channel(fill_tif, reference_grid or channels[0])
        filled = np.where(valid_output, pred, fill_arr)
        _write_geotiff(filled_out_tif, filled.astype("float32"), profile)
    return out_tif


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Применить DEM-модель к GeoTIFF-каналам.")
    p.add_argument("--checkpoint", required=True, type=Path)
    p.add_argument("--channel", action="append", required=True, type=Path, help="GeoTIFF канал; повторять в порядке обучения.")
    p.add_argument("--normalization", type=Path, default=None)
    p.add_argument("--reference-grid", type=Path, default=None, help="GeoTIFF, сетку которого надо использовать для выходной DEM.")
    p.add_argument("--fill-tif", type=Path, default=None, help="DEM для заполнения NoData вне InSAR/ML footprint.")
    p.add_argument("--filled-out-tif", type=Path, default=None, help="Куда записать filled DEM: ML где есть прогноз, fill-tif где NoData.")
    p.add_argument("--mask-out-tif", type=Path, default=None, help="Куда записать uint8-маску валидных пикселей ML DEM.")
    p.add_argument("--out-tif", required=True, type=Path)
    p.add_argument("--patch-size", type=int, default=256)
    p.add_argument("--overlap", type=int, default=32)
    p.add_argument("--mode", choices=["full", "tile"], default="full", help="full = один прогон с padding; tile = тайлы.")
    p.add_argument("--device", default="auto", choices=["auto", "cpu", "mps", "cuda"])
    p.add_argument("--residual-base-channel", type=int, default=-1, help="Если модель предсказывает residual, добавить его к этому raw input channel.")
    return p


def main() -> None:
    args = build_parser().parse_args()
    out = infer_geotiff(
        checkpoint=args.checkpoint,
        channels=args.channel,
        out_tif=args.out_tif,
        normalization=args.normalization,
        reference_grid=args.reference_grid,
        fill_tif=args.fill_tif,
        filled_out_tif=args.filled_out_tif,
        mask_out_tif=args.mask_out_tif,
        patch_size=args.patch_size,
        overlap=args.overlap,
        mode=args.mode,
        device=args.device,
        residual_base_channel=args.residual_base_channel,
    )
    print(f"out: {out}")


if __name__ == "__main__":
    main()
