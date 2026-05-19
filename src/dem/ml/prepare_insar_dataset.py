# -*- coding: utf-8 -*-
"""Подготовка NPZ-патчей для ML-коррекции InSAR DEM."""

from __future__ import annotations

import argparse
import json
import random
import shutil
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject

from dem.features.tiling import iter_windows
from dem.io.layout import data_processed, resolve_out_dir


def _load_stack_metrics(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _split_rows(rows: list[dict], *, val_fraction: float, test_fraction: float, seed: int) -> dict[str, list[dict]]:
    shuffled = list(rows)
    random.Random(seed).shuffle(shuffled)
    n = len(shuffled)
    test_n = max(1, int(round(n * test_fraction))) if n >= 3 and test_fraction > 0 else 0
    val_n = max(1, int(round(n * val_fraction))) if n >= 3 and val_fraction > 0 else 0
    if test_n + val_n >= n:
        test_n = 1 if n >= 3 else 0
        val_n = 1 if n >= 3 else 0
    return {
        "test": shuffled[:test_n],
        "val": shuffled[test_n : test_n + val_n],
        "train": shuffled[test_n + val_n :],
    }


def _read_reference(path: Path) -> tuple[np.ndarray, dict]:
    with rasterio.open(path) as src:
        arr = src.read(1, masked=True).filled(np.nan).astype("float32")
        meta = {
            "crs": src.crs,
            "transform": src.transform,
            "width": src.width,
            "height": src.height,
            "profile": src.profile.copy(),
        }
    return arr, meta


def _reproject_to_reference(dem_path: Path, ref_meta: dict) -> np.ndarray:
    with rasterio.open(dem_path) as src:
        dst = np.full((ref_meta["height"], ref_meta["width"]), np.nan, dtype="float32")
        reproject(
            source=src.read(1, masked=True).filled(np.nan).astype("float32"),
            destination=dst,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=src.nodata,
            dst_transform=ref_meta["transform"],
            dst_crs=ref_meta["crs"],
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )
    return dst


def _channel_stats(rows: list[dict], ref_meta: dict) -> dict[str, float]:
    values: list[np.ndarray] = []
    for row in rows:
        arr = _reproject_to_reference(Path(row["path"]), ref_meta)
        valid = np.isfinite(arr)
        if valid.any():
            values.append(arr[valid])
    if not values:
        return {"mean": 0.0, "std": 1.0}
    merged = np.concatenate(values)
    mean = float(np.mean(merged))
    std = float(np.std(merged))
    if not np.isfinite(std) or std < 1e-6:
        std = 1.0
    return {"mean": mean, "std": std}


def _write_patches_for_row(
    *,
    row: dict,
    split: str,
    ref_arr: np.ndarray,
    ref_meta: dict,
    stats: dict[str, float],
    out_dir: Path,
    patch_size: int,
    overlap: int,
    min_valid_fraction: float,
    max_abs_residual: float,
) -> list[dict]:
    insar = _reproject_to_reference(Path(row["path"]), ref_meta)
    residual = (ref_arr - insar).astype("float32")
    valid = np.isfinite(insar) & np.isfinite(ref_arr) & np.isfinite(residual)
    if max_abs_residual > 0:
        valid &= np.abs(residual) <= max_abs_residual

    x = ((insar - float(stats["mean"])) / float(stats["std"])).astype("float32")
    x[~np.isfinite(x)] = np.nan
    residual[~valid] = np.nan

    split_dir = out_dir / split
    split_dir.mkdir(parents=True, exist_ok=True)

    pair = row["pair"]
    written: list[dict] = []
    for win in iter_windows(ref_meta["height"], ref_meta["width"], patch_size=patch_size, overlap=overlap):
        y_patch = residual[win.row : win.row + win.size, win.col : win.col + win.size]
        x_patch = x[win.row : win.row + win.size, win.col : win.col + win.size]
        ok = valid[win.row : win.row + win.size, win.col : win.col + win.size]
        if float(ok.mean()) < min_valid_fraction:
            continue
        name = f"{pair}__r{win.row:05d}_c{win.col:05d}.npz"
        path = split_dir / name
        np.savez_compressed(
            path,
            x=x_patch[None, ...].astype("float32"),
            y=y_patch.astype("float32"),
            row=win.row,
            col=win.col,
        )
        written.append(
            {
                "file": str(path.relative_to(out_dir)),
                "pair": pair,
                "split": split,
                "row": win.row,
                "col": win.col,
                "valid_fraction": float(ok.mean()),
                "source_rmse": float(row["rmse"]),
                "source_mae": float(row["mae"]),
                "source_bias": float(row["bias"]),
            }
        )
    return written


def prepare(args: argparse.Namespace) -> Path:
    metrics_path = Path(args.stack_metrics)
    data = _load_stack_metrics(metrics_path)
    reference = Path(args.reference or data["reference"])
    ref_arr, ref_meta = _read_reference(reference)

    rows = [
        r
        for r in data.get("members", [])
        if int(r.get("pixels", 0)) >= args.min_pixels and float(r.get("rmse", float("inf"))) <= args.max_rmse
    ]
    if args.max_pairs > 0:
        rows = sorted(rows, key=lambda r: float(r["rmse"]))[: args.max_pairs]
    if not rows:
        raise SystemExit(
            f"Нет DEM для ML после фильтра: pixels>={args.min_pixels}, RMSE<={args.max_rmse}. "
            f"Проверь {metrics_path}"
        )

    out_dir = resolve_out_dir(args.out_dir, lambda: data_processed() / "ml_insar_residual_dataset")
    if out_dir.exists() and args.force:
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    splits = _split_rows(rows, val_fraction=args.val_fraction, test_fraction=args.test_fraction, seed=args.seed)
    stats = _channel_stats(splits["train"] or rows, ref_meta)

    patches: list[dict] = []
    split_summary: dict[str, dict] = {}
    for split, split_rows in splits.items():
        split_summary[split] = {"pairs": [r["pair"] for r in split_rows], "patches": 0}
        for row in split_rows:
            new_patches = _write_patches_for_row(
                row=row,
                split=split,
                ref_arr=ref_arr,
                ref_meta=ref_meta,
                stats=stats,
                out_dir=out_dir,
                patch_size=args.patch_size,
                overlap=args.overlap,
                min_valid_fraction=args.min_valid_fraction,
                max_abs_residual=args.max_abs_residual,
            )
            patches.extend(new_patches)
            split_summary[split]["patches"] += len(new_patches)

    manifest = {
        "task": "insar_residual_correction",
        "description": "Input channel is InSAR DEM normalized by train stats; target is COP30 - InSAR residual in meters.",
        "stack_metrics": str(metrics_path),
        "reference": str(reference),
        "filters": {
            "min_pixels": args.min_pixels,
            "max_rmse": args.max_rmse,
            "max_pairs": args.max_pairs,
            "max_abs_residual": args.max_abs_residual,
        },
        "patch_size": args.patch_size,
        "overlap": args.overlap,
        "min_valid_fraction": args.min_valid_fraction,
        "normalization": {"ch0:insar_dem": stats},
        "splits": split_summary,
        "pairs": rows,
        "patches": patches,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "normalization.json").write_text(
        json.dumps({"ch0:insar_dem": stats}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"dataset: {out_dir}")
    print(f"pairs:   {len(rows)}")
    print(f"stats:   mean={stats['mean']:.3f} std={stats['std']:.3f}")
    for split in ("train", "val", "test"):
        print(
            f"{split}: pairs={len(split_summary[split]['pairs'])} "
            f"patches={split_summary[split]['patches']}"
        )
    print(f"manifest: {out_dir / 'manifest.json'}")
    return out_dir


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Подготовить ML-датасет по отобранным InSAR DEM из stack metrics.")
    p.add_argument("--stack-metrics", required=True, help="Путь к insar_stack_metrics.json.")
    p.add_argument("--reference", default="", help="Переопределить reference DEM; пусто = reference из stack metrics.")
    p.add_argument("--out-dir", default="", help="Папка датасета; пусто = outputs/<date>/data/processed/ml_insar_residual_dataset.")
    p.add_argument("--min-pixels", type=int, default=50000)
    p.add_argument("--max-rmse", type=float, default=200.0)
    p.add_argument("--max-pairs", type=int, default=0, help="0 = все пары после фильтра; иначе top-N по RMSE.")
    p.add_argument("--patch-size", type=int, default=128)
    p.add_argument("--overlap", type=int, default=32)
    p.add_argument("--min-valid-fraction", type=float, default=0.65)
    p.add_argument("--max-abs-residual", type=float, default=500.0)
    p.add_argument("--val-fraction", type=float, default=0.2)
    p.add_argument("--test-fraction", type=float, default=0.15)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--force", action="store_true", help="Удалить out-dir перед сборкой.")
    return p


def main() -> None:
    prepare(build_parser().parse_args())


if __name__ == "__main__":
    main()
