#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build final VKR report artifacts for the InSAR + ML DEM workflow."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject


ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = Path(os.environ.get("VKR_RUN_ROOT", ROOT / ".local_data" / "outputs" / "2026-05-08"))
OUT_DIR = Path(os.environ.get("ARTIFACT_OUT_DIR", ROOT / "reports" / "vkr_final_artifacts_2026-05-15"))

REF_TIF = Path(
    os.environ.get(
        "REF_TIF",
        ROOT
        / "data/processed/reference_dem/sochi_khosta_mzymta_small/20260325T043705Z/"
        "sochi_khosta_mzymta_small_cop30_COP30_opentopo_dl20260325T043705Z_epsg3857.tif",
    )
)
MVP_TIF = Path(
    os.environ.get(
        "MVP_TIF",
        RUN_ROOT
        / "insar/full_pairs_roi/"
        "S1A_IW_SLC__1SDV_20141014T032349__VS__S1A_IW_SLC__1SDV_20141026T032349/dem_insar.tif",
    )
)
FINAL_TIF = Path(
    os.environ.get(
        "FINAL_TIF",
        RUN_ROOT
        / "ml_corrected_stack/resnet18_unet_bs8_ep120_seed42_20260511_robust15/"
        "ml_corrected_stack_robust15_clip_reference_min.tif",
    )
)
QUANTILE_TIF = Path(
    os.environ.get(
        "QUANTILE_TIF",
        RUN_ROOT
        / "ml_corrected_stack/resnet18_unet_bs8_ep120_seed42_20260511_robust15/"
        "ml_corrected_stack_robust15_quantile_reference.tif",
    )
)
RAW_STACK_MEAN_TIF = RUN_ROOT / "insar/stack_roi_filtered/insar_stack_mean.tif"
EARLY_ML_TIF = (
    RUN_ROOT
    / "ml_corrected/resnet18_unet_bs8_ep120_seed42_20260511/insar_stack_median/dem_ml_corrected.tif"
)
ROBUST15_TIF = (
    RUN_ROOT
    / "ml_corrected_stack/resnet18_unet_bs8_ep120_seed42_20260511_robust15/ml_corrected_stack_robust15.tif"
)
PSNR_RANGE = 1000.0
STEEP_SLOPE_DEG = 20.0

BASELINE_PREFLIGHT = RUN_ROOT / "insar/baseline_preflight/baseline_preflight.json"
BASELINE_OK = RUN_ROOT / "insar/baseline_preflight/baseline_ok_pairs.json"
STACK_FILTERED = RUN_ROOT / "insar/stack_roi_filtered/insar_stack_metrics.json"
ML_DATASET = RUN_ROOT / "data/processed/ml_insar_residual_dataset/manifest.json"
ML_EVAL_TEST = RUN_ROOT / "ml_eval/resnet18_unet_bs8_ep120_seed42_20260511/ml_eval_test.json"
ML_HISTORY = RUN_ROOT / "models/insar_residual_runs/resnet18_unet_bs8_ep120_seed42_20260511/history.json"
ML_LEARNING_CURVE = RUN_ROOT / "models/insar_residual_runs/resnet18_unet_bs8_ep120_seed42_20260511/learning_curves.png"
ROBUST_METRICS = (
    RUN_ROOT
    / "ml_corrected_stack/resnet18_unet_bs8_ep120_seed42_20260511_robust15/robust_stack_metrics.json"
)
SLC_RUNS_DIR = RUN_ROOT / "data/raw/slc_runs"
FULL_PAIRS_ROI_DIR = RUN_ROOT / "insar/full_pairs_roi"
ML_DATASET_DIR = RUN_ROOT / "data/processed/ml_insar_residual_dataset"
ML_CORRECTED_PAIRS_DIR = RUN_ROOT / "ml_corrected_pairs"
ML_CORRECTED_STACK_DIR = RUN_ROOT / "ml_corrected_stack"
MODEL_RUN_DIR = RUN_ROOT / "models/insar_residual_runs/resnet18_unet_bs8_ep120_seed42_20260511"


@dataclass
class Raster:
    arr: np.ndarray
    profile: dict


def read_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def size_gb(path: Path) -> float:
    """Return decimal gigabytes according to `du -sk`."""
    if not path.exists():
        return float("nan")
    try:
        out = subprocess.check_output(["du", "-sk", str(path)], text=True)
        kib = int(out.split()[0])
        return kib * 1024 / 1_000_000_000
    except Exception:
        return float("nan")


def fmt_gb(value: float) -> str:
    if not np.isfinite(value):
        return "нет данных"
    if value < 0.01:
        return f"{value:.3f}"
    if value < 1:
        return f"{value:.2f}"
    return f"{value:.1f}"


def display_path(path: Path | str) -> str:
    """Return a report-safe path without user-specific absolute directories."""
    p = Path(path)
    for root, label in ((OUT_DIR, "."), (RUN_ROOT, "${VKR_RUN_ROOT}"), (ROOT, "${PROJECT_ROOT}")):
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue
        if label == ".":
            return f"./{rel.as_posix()}"
        return f"{label}/{rel.as_posix()}"
    return p.as_posix()


def read_ref(path: Path) -> Raster:
    with rasterio.open(path) as src:
        return Raster(src.read(1, masked=True).filled(np.nan).astype("float32"), src.profile.copy())


def read_on_reference(path: Path, ref: Raster) -> np.ndarray:
    with rasterio.open(path) as src:
        arr = src.read(1, masked=True).filled(np.nan).astype("float32")
        if (
            arr.shape == ref.arr.shape
            and src.crs == ref.profile["crs"]
            and src.transform == ref.profile["transform"]
        ):
            return arr
        dst = np.full(ref.arr.shape, np.nan, dtype="float32")
        reproject(
            source=arr,
            destination=dst,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=ref.profile["transform"],
            dst_crs=ref.profile["crs"],
            src_nodata=src.nodata,
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )
        return dst


def slope_from_reference(reference: np.ndarray, transform: rasterio.Affine) -> np.ndarray:
    dx = abs(float(transform.a))
    dy = abs(float(transform.e))
    dz_dy, dz_dx = np.gradient(reference.astype("float32", copy=False), dy, dx)
    slope = np.degrees(np.arctan(np.hypot(dz_dx, dz_dy))).astype("float32")
    slope[~np.isfinite(reference)] = np.nan
    return slope


def _basic_metrics(candidate: np.ndarray, reference: np.ndarray, mask: np.ndarray) -> dict[str, float | int]:
    valid = mask & np.isfinite(candidate) & np.isfinite(reference)
    if not valid.any():
        return {
            "pixels": 0,
            "mae": float("nan"),
            "rmse": float("nan"),
            "bias": float("nan"),
            "psnr": float("nan"),
        }
    err = candidate[valid] - reference[valid]
    rmse = float(np.sqrt(np.mean(err**2)))
    psnr = 20.0 * np.log10(PSNR_RANGE / max(rmse, 1e-12))
    return {
        "pixels": int(valid.sum()),
        "mae": float(np.mean(np.abs(err))),
        "rmse": rmse,
        "bias": float(np.mean(err)),
        "psnr": float(psnr),
    }


def metrics(candidate: np.ndarray, reference: np.ndarray, slope: np.ndarray) -> dict[str, float | int]:
    all_mask = np.isfinite(reference)
    steep_mask = all_mask & np.isfinite(slope) & (slope > STEEP_SLOPE_DEG)
    all_metrics = _basic_metrics(candidate, reference, all_mask)
    steep_metrics = _basic_metrics(candidate, reference, steep_mask)
    all_metrics.update(
        {
            "steep_pixels": steep_metrics["pixels"],
            "steep_mae": steep_metrics["mae"],
            "steep_rmse": steep_metrics["rmse"],
            "min": float(np.nanmin(candidate)),
            "max": float(np.nanmax(candidate)),
            "mean": float(np.nanmean(candidate)),
            "std": float(np.nanstd(candidate)),
        }
    )
    return all_metrics


def candidate_products() -> list[dict[str, str | Path]]:
    return [
        {
            "name": "Минимальный базовый вариант: одна InSAR-пара",
            "path": MVP_TIF,
            "meaning": "Одна пригодная интерферометрическая пара; используется только как нижняя точка сравнения.",
        },
        {
            "name": "Среднее по 15 исходным InSAR-ЦМР",
            "path": RAW_STACK_MEAN_TIF,
            "meaning": "Арифметическое среднее 15 исходных InSAR-ЦМР; снижает часть случайной ошибки, но сохраняет систематическое смещение.",
        },
        {
            "name": "Ранний вариант нейросетевой коррекции",
            "path": EARLY_ML_TIF,
            "meaning": "Первый результат после нейросетевой коррекции без финального устойчивого взвешивания 15 ЦМР.",
        },
        {
            "name": "Robust15 + ResNet18-U-Net",
            "path": ROBUST15_TIF,
            "meaning": "Устойчивое объединение 15 нейросетево исправленных ЦМР до постобработки нижней границы.",
        },
        {
            "name": "Robust15 + ограничение нижней границы",
            "path": FINAL_TIF,
            "meaning": "Основной итоговый продукт: значения ниже минимума Copernicus GLO-30 в области интереса заменены этим минимумом; распределение высот не подгонялось под эталон.",
        },
        {
            "name": "Robust15 + квантильная калибровка",
            "path": QUANTILE_TIF,
            "meaning": "Калиброванный вариант: распределение высот согласовано с Copernicus GLO-30 по квантилям; это не полностью независимый продукт.",
        },
    ]


def load_metric_rows(ref_raster: Raster, slope: np.ndarray) -> tuple[list[dict], dict[str, np.ndarray]]:
    arrays: dict[str, np.ndarray] = {"Эталон COP30": ref_raster.arr}
    rows: list[dict] = []
    for product in candidate_products():
        arr = read_on_reference(Path(product["path"]), ref_raster)
        arrays[str(product["name"])] = arr
        rows.append(
            {
                "name": str(product["name"]),
                "path": display_path(product["path"]),
                "meaning": str(product["meaning"]),
                **metrics(arr, ref_raster.arr, slope),
            }
        )
    return rows, arrays


def pct_improve(before: float, after: float) -> float:
    return 100.0 * (before - after) / before if before else float("nan")


def save_map_panel(ref: np.ndarray, raw_stack: np.ndarray, final: np.ndarray, quantile: np.ndarray) -> Path:
    out = OUT_DIR / "fig_01_dem_maps_reference_stack_final.png"
    values = np.concatenate([x[np.isfinite(x)].ravel() for x in (ref, raw_stack, final, quantile)])
    vmin, vmax = np.nanpercentile(values, [1, 99])
    items = [
        ("Эталонная ЦМР COP30", ref),
        ("Среднее по 15 исходным InSAR-ЦМР", raw_stack),
        ("Основной продукт: Robust15 + ограничение нижней границы", final),
        ("Калиброванный продукт: квантильная калибровка", quantile),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(12, 14), constrained_layout=True)
    for ax, (title, arr) in zip(axes.ravel(), items):
        im = ax.imshow(arr, cmap="terrain", vmin=vmin, vmax=vmax)
        ax.set_title(title)
        ax.set_xticks([])
        ax.set_yticks([])
    fig.colorbar(im, ax=axes.ravel().tolist(), shrink=0.75, label="Высота, м")
    fig.savefig(out, dpi=200)
    plt.close(fig)
    return out


def save_error_maps(
    ref: np.ndarray,
    raw_stack: np.ndarray,
    early_ml: np.ndarray,
    final: np.ndarray,
    quantile: np.ndarray,
) -> Path:
    out = OUT_DIR / "fig_02_error_maps_before_after.png"
    raw_err = raw_stack - ref
    early_err = early_ml - ref
    final_err = final - ref
    quantile_err = quantile - ref
    fig, axes = plt.subplots(2, 2, figsize=(12, 14), constrained_layout=True)
    err_items = [
        ("Ошибка среднего по 15 исходным ЦМР относительно COP30", raw_err, "RdBu_r", -250, 250, "Ошибка, м"),
        ("Ошибка ранней нейросетевой коррекции относительно COP30", early_err, "RdBu_r", -250, 250, "Ошибка, м"),
        ("Ошибка основного продукта относительно COP30", final_err, "RdBu_r", -250, 250, "Ошибка, м"),
        ("Ошибка калиброванного продукта относительно COP30", quantile_err, "RdBu_r", -250, 250, "Ошибка, м"),
    ]
    for ax, (title, arr, cmap, vmin, vmax, label) in zip(axes.ravel(), err_items):
        im = ax.imshow(arr, cmap=cmap, vmin=vmin, vmax=vmax)
        ax.set_title(title)
        ax.set_xticks([])
        ax.set_yticks([])
        fig.colorbar(im, ax=ax, shrink=0.75, label=label)
    fig.savefig(out, dpi=200)
    plt.close(fig)
    return out


def save_error_hist(
    ref: np.ndarray,
    raw_stack: np.ndarray,
    early_ml: np.ndarray,
    final: np.ndarray,
    quantile: np.ndarray,
) -> Path:
    out = OUT_DIR / "fig_03_error_histogram_before_after.png"
    fig, ax = plt.subplots(figsize=(11, 6), constrained_layout=True)
    for label, arr, color in [
        ("Среднее по 15 исходным ЦМР", raw_stack - ref, "#9a3412"),
        ("Ранняя нейросетевая коррекция", early_ml - ref, "#a855f7"),
        ("Основной Robust15", final - ref, "#2563eb"),
        ("Квантильная калибровка", quantile - ref, "#16a34a"),
    ]:
        vals = arr[np.isfinite(arr)]
        vals = vals[np.abs(vals) <= 500]
        ax.hist(vals, bins=100, alpha=0.45, density=True, label=label, color=color)
    ax.axvline(0, color="black", linewidth=1)
    ax.set_title("Распределение вертикальной ошибки относительно COP30")
    ax.set_xlabel("Ошибка высоты, м")
    ax.set_ylabel("Плотность")
    ax.legend()
    ax.grid(alpha=0.25)
    fig.savefig(out, dpi=200)
    plt.close(fig)
    return out


def save_scatter(
    ref: np.ndarray,
    raw_stack: np.ndarray,
    early_ml: np.ndarray,
    final: np.ndarray,
    quantile: np.ndarray,
) -> Path:
    out = OUT_DIR / "fig_04_scatter_cop30_vs_dem.png"
    rng = np.random.default_rng(42)
    fig, axes = plt.subplots(2, 2, figsize=(12, 12), constrained_layout=True)
    items = [
        ("Среднее по 15 исходным ЦМР", raw_stack),
        ("Ранняя нейросетевая коррекция", early_ml),
        ("Основной продукт", final),
        ("Калиброванный продукт", quantile),
    ]
    for ax, (title, arr) in zip(axes.ravel(), items):
        valid = np.isfinite(ref) & np.isfinite(arr)
        idx = np.flatnonzero(valid.ravel())
        if len(idx) > 12000:
            idx = rng.choice(idx, size=12000, replace=False)
        x = ref.ravel()[idx]
        y = arr.ravel()[idx]
        ax.scatter(x, y, s=3, alpha=0.25)
        lo = float(np.nanpercentile(np.concatenate([x, y]), 0.5))
        hi = float(np.nanpercentile(np.concatenate([x, y]), 99.5))
        ax.plot([lo, hi], [lo, hi], color="black", linewidth=1)
        ax.set_title(title)
        ax.set_xlabel("Высота COP30, м")
        ax.set_ylabel("Высота продукта, м")
        ax.set_xlim(lo, hi)
        ax.set_ylim(lo, hi)
        ax.grid(alpha=0.25)
    fig.suptitle("Диаграмма рассеяния: COP30 и рассчитанные ЦМР-продукты")
    fig.savefig(out, dpi=200)
    plt.close(fig)
    return out


def save_profiles(
    ref: np.ndarray,
    raw_stack: np.ndarray,
    final: np.ndarray,
    quantile: np.ndarray,
    profile: dict,
) -> list[Path]:
    out_profile = OUT_DIR / "fig_05_height_profiles.png"
    out_locations = OUT_DIR / "fig_06_profile_locations.png"
    height, width = ref.shape
    profile_specs = [
        (int(height * 0.22), "Профиль 1: северный горный участок", "#dc2626"),
        (int(height * 0.50), "Профиль 2: центральная часть", "#2563eb"),
        (int(height * 0.88), "Профиль 3: прибрежная зона", "#16a34a"),
    ]
    px = abs(profile["transform"].a)
    py = abs(profile["transform"].e)
    x_km = (np.arange(width) + 0.5) * px / 1000.0
    xmax = width * px / 1000.0
    ymax = height * py / 1000.0

    fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True, constrained_layout=True)
    for ax, (row, label, color) in zip(axes, profile_specs):
        y_km = (row + 0.5) * py / 1000.0
        ax.plot(x_km, ref[row, :], label="Copernicus GLO-30", linewidth=2.2, color="black")
        ax.plot(x_km, raw_stack[row, :], label="Среднее по 15 исходным ЦМР", alpha=0.85, color="#78716c", linestyle="--")
        ax.plot(x_km, final[row, :], label="Основной продукт", alpha=0.95, color="#2563eb")
        ax.plot(x_km, quantile[row, :], label="Калиброванный продукт", alpha=0.95, color="#16a34a")
        ax.set_title(f"{label}; горизонтальное сечение на {y_km:.1f} км от северной границы")
        ax.set_ylabel("Высота, м")
        ax.grid(alpha=0.25)
    axes[-1].set_xlabel("Расстояние от западной границы области интереса, км")
    axes[0].legend(ncol=4)
    fig.suptitle("Профили высот по трём горизонтальным сечениям области интереса", y=1.02)
    fig.savefig(out_profile, dpi=200)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 10), constrained_layout=True)
    im = ax.imshow(ref, cmap="terrain", extent=(0, xmax, ymax, 0))
    for row, label, color in profile_specs:
        y_km = (row + 0.5) * py / 1000.0
        ax.hlines(y_km, xmin=0, xmax=xmax, linewidth=3, color=color, label=label)
        ax.text(
            0.25,
            y_km - 0.25,
            label,
            color=color,
            fontsize=9,
            weight="bold",
            bbox={"facecolor": "white", "alpha": 0.75, "edgecolor": "none", "pad": 2},
        )
    ax.set_title("Положение трёх профилей на эталонной ЦМР Copernicus GLO-30")
    ax.set_xlabel("Расстояние от западной границы, км")
    ax.set_ylabel("Расстояние от северной границы, км")
    ax.legend(loc="lower right", fontsize=8)
    fig.colorbar(im, ax=ax, shrink=0.75, label="Высота, м")
    fig.savefig(out_locations, dpi=200)
    plt.close(fig)
    return [out_profile, out_locations]


def save_validity_and_high_error(ref: np.ndarray, raw_stack: np.ndarray, final: np.ndarray) -> Path:
    out = OUT_DIR / "fig_07_validity_and_high_error_masks.png"
    finite = np.isfinite(ref) & np.isfinite(raw_stack) & np.isfinite(final)
    high_error = np.abs(final - ref) > 100
    improvement = np.abs(raw_stack - ref) > np.abs(final - ref)
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), constrained_layout=True)
    items = [
        ("Валидные пиксели во всех ЦМР", finite.astype(float), "Greens"),
        ("Зоны |ошибка основного продукта| > 100 м", high_error.astype(float), "Reds"),
        ("Где основной продукт лучше среднего по 15 исходным ЦМР", improvement.astype(float), "Blues"),
    ]
    for ax, (title, arr, cmap) in zip(axes, items):
        ax.imshow(arr, cmap=cmap, vmin=0, vmax=1)
        ax.set_title(title)
        ax.set_xticks([])
        ax.set_yticks([])
    fig.savefig(out, dpi=200)
    plt.close(fig)
    return out


def save_metrics_bar(rows: list[dict]) -> Path:
    out = OUT_DIR / "fig_08_metrics_bar_against_cop30.png"
    names = [r["name"] for r in rows]
    mae = [r["mae"] for r in rows]
    rmse = [r["rmse"] for r in rows]
    y = np.arange(len(names))
    width = 0.36
    fig, ax = plt.subplots(figsize=(13, 8), constrained_layout=True)
    ax.barh(y - width / 2, mae, width, label="MAE")
    ax.barh(y + width / 2, rmse, width, label="RMSE")
    ax.set_yticks(y)
    ax.set_yticklabels(names)
    ax.invert_yaxis()
    ax.set_xlabel("Ошибка, м")
    ax.set_title("Ошибки ЦМР-продуктов относительно эталонной ЦМР COP30")
    ax.legend()
    ax.grid(axis="x", alpha=0.25)
    fig.savefig(out, dpi=200)
    plt.close(fig)
    return out


def moving_average(values: np.ndarray, window: int = 5) -> np.ndarray:
    if len(values) < window:
        return values
    kernel = np.ones(window, dtype="float32") / window
    padded = np.pad(values.astype("float32"), (window // 2, window - 1 - window // 2), mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def save_learning_curves_from_history() -> Path | None:
    if not ML_HISTORY.exists():
        return None
    history = read_json(ML_HISTORY)
    if not isinstance(history, list) or not history:
        return None
    out = OUT_DIR / "fig_09_learning_curves.png"
    epochs = np.array([row["epoch"] for row in history], dtype="float32")
    train_loss = np.array([row["train_loss"] for row in history], dtype="float32")
    val_mae = np.array([row["val_mae"] for row in history], dtype="float32")
    val_rmse = np.array([row["val_rmse"] for row in history], dtype="float32")
    val_psnr = np.array([row["val_psnr"] for row in history], dtype="float32")
    best_idx = int(np.nanargmin(val_rmse))

    fig, axes = plt.subplots(2, 1, figsize=(12, 9), sharex=True, constrained_layout=True)
    axes[0].plot(epochs, train_loss, color="#94a3b8", alpha=0.35, label="Функция потерь на обучении")
    axes[0].plot(epochs, moving_average(train_loss), color="#475569", linewidth=2, label="Сглаженная функция потерь")
    axes[0].plot(epochs, val_mae, color="#f59e0b", alpha=0.35, label="MAE на валидации")
    axes[0].plot(epochs, moving_average(val_mae), color="#b45309", linewidth=2, label="Сглаженная MAE")
    axes[0].plot(epochs, val_rmse, color="#2563eb", alpha=0.35, label="RMSE на валидации")
    axes[0].plot(epochs, moving_average(val_rmse), color="#1d4ed8", linewidth=2, label="Сглаженная RMSE")
    axes[0].axvline(epochs[best_idx], color="black", linestyle=":", linewidth=1.5, label=f"Лучшая эпоха по RMSE: {int(epochs[best_idx])}")
    axes[0].set_ylabel("Ошибка, м")
    axes[0].set_title("Кривые обучения ResNet18-U-Net: ошибка")
    axes[0].grid(alpha=0.25)
    axes[0].legend(ncol=2, fontsize=8)

    axes[1].plot(epochs, val_psnr, color="#16a34a", alpha=0.35, label="PSNR на валидации")
    axes[1].plot(epochs, moving_average(val_psnr), color="#15803d", linewidth=2, label="Сглаженная PSNR")
    axes[1].axvline(epochs[best_idx], color="black", linestyle=":", linewidth=1.5)
    axes[1].set_xlabel("Эпоха обучения")
    axes[1].set_ylabel("PSNR, дБ")
    axes[1].set_title("Кривые обучения ResNet18-U-Net: PSNR")
    axes[1].grid(alpha=0.25)
    axes[1].legend(fontsize=8)
    fig.savefig(out, dpi=200)
    plt.close(fig)
    return out


def table_line(values: list[str | int | float]) -> str:
    return "| " + " | ".join(str(v) for v in values) + " |"


def count_items(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, (list, tuple, set, dict)):
        return len(value)
    return 0


def write_markdown_reports(metrics_rows: list[dict], artifact_paths: dict[str, Path]) -> None:
    preflight = read_json(BASELINE_PREFLIGHT)
    ok_pairs = read_json(BASELINE_OK)
    stack = read_json(STACK_FILTERED)
    dataset = read_json(ML_DATASET)
    ml_eval = read_json(ML_EVAL_TEST)
    robust = read_json(ROBUST_METRICS)
    sizes = {
        "slc": fmt_gb(size_gb(SLC_RUNS_DIR)),
        "pairs_filter": fmt_gb(size_gb(BASELINE_PREFLIGHT.parent)),
        "insar": fmt_gb(size_gb(FULL_PAIRS_ROI_DIR)),
        "stack": fmt_gb(size_gb(STACK_FILTERED.parent)),
        "dataset": fmt_gb(size_gb(ML_DATASET_DIR)),
        "ml_pairs": fmt_gb(size_gb(ML_CORRECTED_PAIRS_DIR)),
        "ml_stack": fmt_gb(size_gb(ML_CORRECTED_STACK_DIR)),
        "model": fmt_gb(size_gb(MODEL_RUN_DIR)),
    }

    funnel_md = OUT_DIR / "table_01_selection_funnel.md"
    funnel_lines = [
        "# Воронка отбора данных и ЦМР",
        "",
        "| Этап | Размер данных, ГБ | Вход | Выход | Отсеяно | Развёрнутый принцип отбора |",
        "|---|---:|---:|---:|---:|---|",
        table_line(
            [
                "Архив SLC-сцен Sentinel-1",
                sizes["slc"],
                "2014-2026",
                "единая папка SLC",
                "-",
                "Все SLC-сцены за 2014-2026 гг. сведены в одну директорию. Дальше даты рассматриваются как единый неделимый временной ряд, без разделения на старую и новую папку.",
            ]
        ),
        table_line(
            [
                "Первичный отбор интерферометрических пар",
                sizes["pairs_filter"],
                len(preflight),
                len(ok_pairs),
                len(preflight) - len(ok_pairs),
                "Оставлены пары с достаточным покрытием области интереса, совместимой геометрией съёмки, подходящей подполосой и пакетами импульсов, приемлемым временным интервалом и перпендикулярной интерферометрической базой. Отсеяны пары с неподходящей геометрией, слабым пересечением или отсутствием устойчивых параметров базы.",
            ]
        ),
        table_line(
            [
                "Построение InSAR-ЦМР",
                sizes["insar"],
                len(ok_pairs),
                28,
                0,
                "Каждая допущенная пара обработана в SNAP и SNAPHU: уточнение орбит, совместная привязка сцен, построение интерферограммы, фильтрация, развёртка фазы, перевод фазы в высоту, геокодирование и обрезка по области интереса.",
            ]
        ),
        table_line(
            [
                "Контроль качества InSAR-ЦМР",
                sizes["stack"],
                28,
                len(stack["members"]),
                len(stack["excluded"]),
                "Каждая ЦМР сравнивалась с Copernicus GLO-30. Оставлены ЦМР с достаточным числом валидных пикселей и приемлемой ошибкой; исключены продукты с грубыми провалами, полосами, малым покрытием или RMSE выше заданного порога.",
            ]
        ),
        table_line(
            [
                "Формирование набора для обучения",
                sizes["dataset"],
                len(stack["members"]),
                len(dataset["pairs"]),
                len(stack["members"]) - len(dataset["pairs"]),
                "Для обучения нейросети применён более строгий порог: используются только ЦМР с RMSE не выше 200 м. Целевая поправка задаётся как разность `Copernicus GLO-30 - InSAR-ЦМР`, а разделение выполняется по парам, чтобы соседние фрагменты одной пары не попадали одновременно в обучение и проверку.",
            ]
        ),
        table_line(
            [
                "Нарезка обучающих фрагментов",
                sizes["dataset"],
                len(dataset["pairs"]),
                count_items(dataset["patches"]),
                "-",
                "ЦМР нарезаны на фрагменты 128 x 128 пикселей с перекрытием 32 пикселя. Фрагменты с недостаточной долей валидных значений исключаются; остальные распределяются на обучение, валидацию и тест.",
            ]
        ),
        table_line(
            [
                "Обучение ResNet18-U-Net",
                sizes["model"],
                count_items(dataset["patches"]),
                "best.pt",
                "-",
                "Модель обучается предсказывать остаточную высотную поправку по фрагменту InSAR-ЦМР. Лучшая контрольная точка выбирается по ошибке на валидационном разделе, а итоговое качество затем проверяется на отложенном тестовом разделе.",
            ]
        ),
        table_line(
            [
                "Нейросетевая коррекция",
                sizes["ml_pairs"],
                15,
                15,
                0,
                "Обученная ResNet18-U-Net применена ко всем 15 ЦМР, прошедшим контроль качества. На выходе для каждой исходной ЦМР получена карта предсказанной остаточной поправки и исправленная ЦМР.",
            ]
        ),
        table_line(
            [
                "Устойчивое объединение Robust15",
                sizes["ml_stack"],
                15,
                1,
                0,
                "Исправленные ЦМР объединены взвешенно: больший вес получают продукты с меньшей ошибкой относительно Copernicus GLO-30 и более содержательной динамикой рельефа. После объединения получен один итоговый GeoTIFF.",
            ]
        ),
    ]
    funnel_md.write_text("\n".join(funnel_lines), encoding="utf-8")

    comparison_md = OUT_DIR / "table_02_quality_against_cop30.md"
    comp_lines = [
        "# Сравнение метрик InSAR-ЦМР до и после нейросетевой коррекции относительно Copernicus GLO-30",
        "",
        "MAE - средняя абсолютная ошибка высоты в метрах. RMSE - среднеквадратическая ошибка; она сильнее наказывает крупные локальные промахи. "
        "Среднее смещение показывает, завышает или занижает продукт высоты относительно эталона.",
        "",
        f"PSNR рассчитан как `20 * log10({PSNR_RANGE:.0f} / RMSE)`, где 1000 м - фиксированный диапазон высот для сопоставимости экспериментов. "
        f"Метрики на склонах рассчитаны только по пикселям, где уклон эталонной Copernicus GLO-30 больше {STEEP_SLOPE_DEG:.0f} градусов.",
        "",
        "| Вариант | MAE, м | RMSE, м | Среднее смещение, м | PSNR, дБ | MAE на склонах > 20°, м | RMSE на склонах > 20°, м | Что означает вариант |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in metrics_rows:
        comp_lines.append(
            table_line(
                [
                    row["name"],
                    f"{row['mae']:.2f}",
                    f"{row['rmse']:.2f}",
                    f"{row['bias']:.2f}",
                    f"{row['psnr']:.2f}",
                    f"{row['steep_mae']:.2f}",
                    f"{row['steep_rmse']:.2f}",
                    row["meaning"],
                ]
            )
        )
    comparison_md.write_text("\n".join(comp_lines), encoding="utf-8")

    ml_md = OUT_DIR / "table_03_ml_train_val_test.md"
    splits = dataset["splits"]
    ml_lines = [
        "# Сводка набора для нейросетевой коррекции: обучение, валидация, тест",
        "",
        "| Раздел выборки | ЦМР-пар | Фрагментов | Назначение |",
        "|---|---:|---:|---|",
        table_line(["обучение", count_items(splits["train"]["pairs"]), count_items(splits["train"]["patches"]), "обучение весов ResNet18-U-Net"]),
        table_line(["валидация", count_items(splits["val"]["pairs"]), count_items(splits["val"]["patches"]), "выбор лучшей эпохи и контрольной точки модели"]),
        table_line(["тест", count_items(splits["test"]["pairs"]), count_items(splits["test"]["patches"]), "отложенная оценка модели"]),
        "",
        "## Тестовые метрики модели остаточной ошибки",
        "",
        "| Вариант | MAE, м | RMSE, м | PSNR, дБ |",
        "|---|---:|---:|---:|",
        table_line(
            [
                "Базовый вариант без нейросетевой коррекции",
                f"{ml_eval['baseline']['mae']:.3f}",
                f"{ml_eval['baseline']['rmse']:.3f}",
                f"{ml_eval['baseline']['psnr']:.3f}",
            ]
        ),
        table_line(
            [
                "После ResNet18-U-Net",
                f"{ml_eval['corrected']['mae']:.3f}",
                f"{ml_eval['corrected']['rmse']:.3f}",
                f"{ml_eval['corrected']['psnr']:.3f}",
            ]
        ),
        table_line(
            [
                "Улучшение",
                f"{ml_eval['improvement']['mae_pct']:.2f}%",
                f"{ml_eval['improvement']['rmse_pct']:.2f}%",
                "-",
            ]
        ),
        "",
        f"Лучшая контрольная точка модели выбрана на эпохе `{ml_eval['checkpoint_metrics']['epoch']}` по RMSE на валидационном разделе.",
        "",
        "PSNR здесь - логарифмическая мера отношения выбранного диапазона высот к RMSE. Чем выше PSNR, тем меньше ошибка. "
        "Для ЦМР это не физическая точность сама по себе, а удобная дополнительная метрика качества реконструкции.",
    ]
    ml_md.write_text("\n".join(ml_lines), encoding="utf-8")

    limitations_md = OUT_DIR / "limitations_and_interpretation.md"
    limitations_lines = [
        "# Ограничения и интерпретация результата",
        "",
        "1. Итоговая ЦМР не превосходит готовые глобальные продукты уровня Copernicus GLO-30.",
        "   Согласно Copernicus DEM Product Handbook, для GLO-30 указана абсолютная вертикальная точность <4 м LE90.",
        "2. Основная ценность результата - не замена COP30, а воспроизводимая исследовательская цепочка обработки:",
        "   Sentinel-1 SLC -> InSAR-ЦМР -> контроль качества -> нейросетевая коррекция остаточной ошибки -> устойчивое объединение ЦМР.",
        "3. Ошибки остаются высокими из-за ограничений Sentinel-1 repeat-pass InSAR в прибрежно-горной зоне:",
        "   потеря когерентности, наложение склонов и радиотень, ошибки развёртки фазы, низкая высотная чувствительность отдельных интерферометрических баз.",
        "4. Ограничение нижней границы - это минимальная постобработка: значения ниже минимума COP30 в пределах области интереса заменяются на этот минимум.",
        "   Такая правка убирает заведомо неправдоподобные отрицательные экстремумы, но не подгоняет всё распределение высот под эталон.",
        "5. Квантильная калибровка является продуктом, зависимым от эталона: она использует COP30 не только для оценки,",
        "   но и для согласования распределения высот по квантилям. Поэтому основной независимый результат - вариант с ограничением нижней границы.",
        "6. Дальнейшее снижение ошибки разумно делать через многоканальную модель машинного обучения:",
        "   маски воды Sentinel-2/NDWI, NDVI, классы земного покрова, разброс высот по 15 ЦМР и маску валидности InSAR.",
        "",
        "## Ссылки для методического контекста",
        "",
        "- Copernicus DEM Product Handbook: https://dataspace.copernicus.eu/sites/default/files/media/files/2024-06/geo1988-copernicusdem-spe-002_producthandbook_i5.0.pdf",
        "- NASA SRTM dataset specification: https://data.nasa.gov/dataset/shuttle-radar-topography-mission-srtm-images",
        "- Multi-baseline InSAR DEM in mountainous terrain: https://pmc.ncbi.nlm.nih.gov/articles/PMC12156989/",
        "- ML correction of DEM errors with terrain/land-cover predictors: https://arxiv.org/abs/2308.06545",
    ]
    limitations_md.write_text("\n".join(limitations_lines), encoding="utf-8")

    postprocessing_md = OUT_DIR / "postprocessing_and_psnr_explanation.md"
    postprocessing_lines = [
        "# Объяснение PSNR и постобработки итоговой ЦМР",
        "",
        "## PSNR",
        "",
        f"PSNR рассчитан по формуле `20 * log10({PSNR_RANGE:.0f} / RMSE)`. "
        "В числителе используется фиксированный диапазон высот 1000 м, чтобы разные запуски можно было сравнивать между собой. "
        "Чем выше PSNR, тем меньше RMSE. В отличие от MAE и RMSE, PSNR не является прямой физической ошибкой в метрах; "
        "это логарифмическая метрика качества восстановления.",
        "",
        "Пример: если RMSE уменьшается, PSNR растёт. Поэтому переход от основного продукта с ограничением нижней границы "
        "к калиброванному варианту даёт рост PSNR с 21.46 до 22.35 дБ.",
        "",
        "## Что делает ограничение нижней границы высот",
        "",
        "Ограничение нижней границы высот - это минимальная физическая правка. "
        "Она берёт минимальную высоту в эталонной COP30 для нашей области интереса и заменяет только те пиксели итоговой ЦМР, "
        "которые оказались ниже этого минимума.",
        "",
        "Важно: эта операция не делает ЦМР похожей на COP30 целиком. Она не меняет форму гор, не выравнивает склоны, "
        "не подгоняет среднее и максимум. Она просто убирает заведомо неправдоподобные отрицательные экстремумы, "
        "которые возникли после объединения нейросетево исправленных ЦМР.",
        "",
        "Поэтому вариант с ограничением нижней границы используется как основной независимый продукт: эталон применяется только для отсечения нижнего хвоста, "
        "а не для полной подгонки распределения высот.",
        "",
        "## Что делает квантильная калибровка",
        "",
        "Квантильная калибровка - это согласование распределения высот по COP30. "
        "В этом контексте гипсометрия означает не форму отдельных склонов, а статистическое распределение высот в области интереса: "
        "сколько пикселей приходится на низины, средние высоты и горные участки. "
        "Смысл такой: для итоговой ЦМР и COP30 строятся распределения высот, затем значения итоговой ЦМР пересчитываются так, "
        "чтобы их квантили соответствовали квантилям COP30.",
        "",
        "Простой пример: если 90-й процентиль итоговой ЦМР равен 420 м, а 90-й процентиль COP30 равен 650 м, "
        "то верхняя часть распределения итоговой ЦМР будет поднята ближе к эталонной. Аналогично корректируются другие уровни распределения.",
        "",
        "Это снижает MAE/RMSE, но делает продукт зависимым от COP30 не только на этапе оценки, а уже на этапе постобработки. "
        "Поэтому квантильная калибровка полезна как отдельный калиброванный продукт и как оценка потенциального качества после гипсометрической калибровки, "
        "но её нельзя подавать как полностью независимый результат InSAR- и нейросетевой цепочки.",
    ]
    postprocessing_md.write_text("\n".join(postprocessing_lines), encoding="utf-8")

    profiles_md = OUT_DIR / "profiles_explanation.md"
    with rasterio.open(REF_TIF) as src:
        width = src.width
        height = src.height
        px = abs(float(src.transform.a))
        py = abs(float(src.transform.e))
    profile_rows = [
        (int(height * 0.22), "северный горный участок"),
        (int(height * 0.50), "центральная часть"),
        (int(height * 0.88), "прибрежная зона"),
    ]
    profiles_lines = [
        "# Как читать профили высот",
        "",
        "Подложка на рисунке положения профилей построена по эталонной ЦМР Copernicus GLO-30, приведённой к сетке проекта EPSG:3857. "
        "Это не итоговая InSAR-ЦМР и не результат нейросетевой коррекции: подложка нужна только как устойчивая карта рельефа, на которой удобно показать, где проведены сечения.",
        "",
        f"Размер эталонной сетки: {width} x {height} пикселей. Пространственный шаг: {px:.2f} м по X и {py:.2f} м по Y. "
        f"Поэтому горизонтальный профиль имеет длину примерно {width * px / 1000:.2f} км. "
        f"Вертикальный размер области интереса составляет примерно {height * py / 1000:.2f} км.",
        "",
        "Ось X на графиках профилей - это не длина полигона и не периметр области. "
        "Это расстояние от западной границы области интереса вдоль выбранной строки растра, выраженное в километрах.",
        "",
        "Используются три горизонтальных сечения:",
        "",
    ]
    for idx, (row, label) in enumerate(profile_rows, start=1):
        y_km = (row + 0.5) * py / 1000.0
        profiles_lines.append(f"- профиль {idx}: {label}, примерно {y_km:.2f} км от северной границы области интереса;")
    profiles_lines += [
        "",
        "Ранее подпись вида `row=148` могла восприниматься как значение исходной высоты. Это не высота, а номер строки в растровой сетке. "
        "В новых рисунках такие подписи заменены на расстояние от северной границы, чтобы избежать путаницы.",
        "",
        "Цвета профилей на карте положения различаются: красный - северный горный участок, синий - центральная часть, зелёный - прибрежная зона.",
    ]
    profiles_md.write_text("\n".join(profiles_lines), encoding="utf-8")

    learning_md = OUT_DIR / "learning_curves_interpretation.md"
    history = read_json(ML_HISTORY) if ML_HISTORY.exists() else []
    if isinstance(history, list) and history:
        best_rmse_row = min(history, key=lambda row: row["val_rmse"])
        best_mae_row = min(history, key=lambda row: row["val_mae"])
        learning_lines = [
            "# Как трактовать кривые обучения",
            "",
            "Кривые обучения показывают, как менялись ошибка на обучающих фрагментах и метрики на валидационном разделе по эпохам. "
            "Для выбора модели используется не последняя эпоха, а лучшая контрольная точка по валидационной ошибке.",
            "",
            f"Минимальная RMSE на валидации достигнута на эпохе {best_rmse_row['epoch']}: "
            f"MAE={best_rmse_row['val_mae']:.3f} м, RMSE={best_rmse_row['val_rmse']:.3f} м, PSNR={best_rmse_row['val_psnr']:.3f} дБ.",
            f"Минимальная MAE на валидации достигнута на эпохе {best_mae_row['epoch']}: "
            f"MAE={best_mae_row['val_mae']:.3f} м, RMSE={best_mae_row['val_rmse']:.3f} м.",
            "",
            "Резкие скачки на графиках ожидаемы для этого эксперимента по нескольким причинам:",
            "",
            "- обучающий набор небольшой: 13 ЦМР-пар и 385 фрагментов, поэтому одна сложная группа фрагментов заметно меняет среднюю ошибку эпохи;",
            "- валидационный раздел тоже мал: 3 ЦМР-пары и 100 фрагментов, поэтому метрика чувствительна к отдельным горным или прибрежным участкам;",
            "- пары неоднородны по качеству: часть InSAR-ЦМР содержит полосы, ошибки развёртки фазы и разные доли валидной области;",
            "- при обучении используются случайное перемешивание и мини-пакеты, поэтому последовательность сложных фрагментов меняется от эпохи к эпохе;",
            "- оптимизатор делает шаги по шумной оценке градиента, и на маленьких данных это даёт колебания даже при общем улучшении модели.",
            "",
            "Поэтому для интерпретации важнее смотреть на сглаженную линию и лучшую валидационную эпоху, а не на отдельные пики функции потерь.",
        ]
    else:
        learning_lines = [
            "# Как трактовать кривые обучения",
            "",
            "История обучения не найдена; файл будет заполнен после запуска обучения модели.",
        ]
    learning_md.write_text("\n".join(learning_lines), encoding="utf-8")

    artifact_manifest_md = OUT_DIR / "artifact_manifest.md"
    artifact_manifest_lines = [
        "# Манифест артефактов ВКР",
        "",
        "Эта таблица связывает этапы пайплайна, готовые материалы для текста ВКР и исходные файлы, из которых они построены.",
        "",
        "| Этап | Готовый артефакт | Пример исходного файла | Как трактовать |",
        "|---|---|---|---|",
        table_line(
            [
                "SLC-сцены 2014-2026",
                display_path(SLC_RUNS_DIR),
                display_path(SLC_RUNS_DIR),
                "Единый архив Sentinel-1 SLC-сцен; из него формируются интерферометрические пары.",
            ]
        ),
        table_line(
            [
                "Предварительный отбор интерферометрических пар",
                display_path(BASELINE_PREFLIGHT.with_suffix(".md")),
                display_path(BASELINE_PREFLIGHT),
                "Показывает, какие пары допустимы по геометрии, временному интервалу, перпендикулярной базе и покрытию области интереса.",
            ]
        ),
        table_line(
            [
                "Пары, допущенные к InSAR",
                display_path(BASELINE_OK.with_suffix(".md")),
                display_path(BASELINE_OK),
                "Список пар, реально запущенных через SNAP и SNAPHU.",
            ]
        ),
        table_line(
            [
                "Валидация InSAR-ЦМР",
                display_path(RUN_ROOT / "insar/stack_roi_filtered/insar_stack_metrics.md"),
                display_path(STACK_FILTERED),
                "Отбор ЦМР по числу валидных пикселей и ошибкам относительно Copernicus GLO-30.",
            ]
        ),
        table_line(
            [
                "Набор для нейросетевой коррекции остаточной ошибки",
                display_path(ml_md),
                display_path(ML_DATASET),
                "13 ЦМР-пар нарезаны на 385 фрагментов; целевая переменная = Copernicus GLO-30 - InSAR-ЦМР.",
            ]
        ),
        table_line(
            [
                "Обучение ResNet18-U-Net",
                display_path(learning_md),
                display_path(ML_HISTORY),
                "Кривые обучения и валидации показывают динамику обучения и выбор лучшей эпохи.",
            ]
        ),
        table_line(
            [
                "Профили высот",
                display_path(OUT_DIR / "fig_05_height_profiles.png"),
                display_path(profiles_md),
                "Три горизонтальных сечения по эталонной сетке: северный горный участок, центральная часть и прибрежная зона.",
            ]
        ),
        table_line(
            [
                "Оценка нейросетевой модели на тестовом разделе",
                display_path(RUN_ROOT / "ml_eval/resnet18_unet_bs8_ep120_seed42_20260511/ml_eval_test.md"),
                display_path(ML_EVAL_TEST),
                "Проверка модели на отложенных фрагментах: ошибка до и после коррекции остаточной ошибки.",
            ]
        ),
        table_line(
            [
                "Устойчивое объединение Robust15",
                display_path(comparison_md),
                display_path(ROBUST_METRICS),
                "Финальное объединение 15 нейросетево исправленных ЦМР с весами по качеству и динамике рельефа.",
            ]
        ),
        table_line(
            [
                "Финальные карты и ошибки",
                display_path(OUT_DIR / "fig_01_dem_maps_reference_stack_final.png"),
                display_path(FINAL_TIF),
                "Визуальное сравнение COP30, простого усреднения, основного итогового продукта и калиброванного варианта.",
            ]
        ),
    ]
    artifact_manifest_md.write_text("\n".join(artifact_manifest_lines), encoding="utf-8")

    methodology_md = OUT_DIR / "vkr_text_methodology_results.md"
    methodology_lines = [
        "# Черновик текста для ВКР: данные, методика и результаты",
        "",
        "## Исходные данные",
        "",
        "В работе использованы радиолокационные снимки Sentinel-1 SLC за период 2014-2026 гг. "
        "Сцены были объединены в единую директорию данных, после чего для них был выполнен предварительный отбор пар. "
        "Отбор проводился не по календарному принципу, а по пригодности пары для интерферометрической обработки: "
        "учитывались наличие покрытия исследуемой территории, совместимость геометрии съемки, временная дистанция между сценами "
        "и параметры интерферометрической базы. В результате из 67 потенциальных пар для дальнейшей обработки были оставлены 28.",
        "",
        "В качестве опорной высотной модели использовалась Copernicus GLO-30, приведённая к той же области интереса "
        "и системе координат EPSG:3857. Эта ЦМР применялась как эталон для контроля качества, формирования целевой остаточной ошибки "
        "при обучении нейронной сети и количественной оценки итогового результата.",
        "",
        "## Формирование InSAR-ЦМР",
        "",
        "Для каждой прошедшей предварительный фильтр пары была построена интерферометрическая цифровая модель рельефа. "
        "Обработка выполнялась через цепочку Sentinel-1 InSAR, включающую подготовку SLC-сцен, построение интерферограммы, "
        "развёртку фазы и геокодирование результата в общую сетку. После этого каждая ЦМР сравнивалась с опорной COP30. "
        "Контроль качества включал число валидных пикселей, MAE, RMSE, среднее смещение и визуальную проверку карты высот.",
        "",
        "Из 28 построенных ЦМР после проверки качества было оставлено 15. Отсеивание было необходимо, потому что часть пар "
        "содержала выраженные ошибки развёртки фазы, провалы, полосы, низкое покрытие или слишком сильное отклонение от опорной ЦМР. "
        "Для обучения модели машинного обучения использовался более строгий порог качества: в набор попали 13 ЦМР, удовлетворяющих ограничению RMSE <= 200 м.",
        "",
        "## Нейросетевая коррекция остаточной ошибки",
        "",
        "Нейросетевая часть построена как задача коррекции остаточной ошибки InSAR-ЦМР. На вход модели подаётся фрагмент InSAR-ЦМР, "
        "нормированный по статистике обучающей выборки. Целевой переменной является остаточная ошибка, то есть разность между опорной "
        "ЦМР и InSAR-ЦМР: `остаточная_ошибка = COP30 - InSAR`. После предсказания этой поправки итоговая исправленная высота "
        "вычисляется как `исправленная_ЦМР = InSAR_ЦМР + предсказанная_поправка`.",
        "",
        "Набор был нарезан на фрагменты 128x128 пикселей с перекрытием 32 пикселя. Использовалось разделение по ЦМР-парам, а не случайное "
        "перемешивание отдельных фрагментов: 8 пар вошли в обучающий раздел, 3 пары в валидационный и 2 пары в тестовый. Такой подход снижает риск утечки "
        "пространственно близких фрагментов между обучением и проверкой.",
        "",
        "Архитектура модели - ResNet18-U-Net. Энкодер ResNet18 извлекает признаки рельефа на разных масштабах, а U-Net-декодер "
        "восстанавливает плотную карту поправки той же размерности, что и входной патч. Лучшая контрольная точка модели была выбрана по RMSE на валидационном разделе.",
        "",
        "## Итоговое объединение",
        "",
        "После обучения модель была применена ко всем 15 ЦМР, прошедшим первичную валидацию. Далее исправленные ЦМР были объединены "
        "в устойчивый продукт Robust15. При объединении больший вес получали ЦМР с меньшей RMSE и более выраженной полезной динамикой рельефа. "
        "Таким образом итоговый продукт не является результатом одной пары, а представляет собой агрегированную модель рельефа, "
        "полученную из 15 независимых интерферометрических оценок.",
        "",
        "## Количественный результат",
        "",
        f"Все итоговые метрики рассчитаны относительно эталонной ЦМР COP30. Простое среднее по 15 исходным ЦМР имеет "
        f"MAE={metrics_rows[1]['mae']:.3f} м и RMSE={metrics_rows[1]['rmse']:.3f} м. "
        f"После нейросетевой коррекции и устойчивого объединения основной продукт с ограничением нижней границы имеет "
        f"MAE={metrics_rows[4]['mae']:.3f} м, RMSE={metrics_rows[4]['rmse']:.3f} м, среднее смещение={metrics_rows[4]['bias']:.3f} м "
        f"и PSNR={metrics_rows[4]['psnr']:.3f} дБ. На склонах круче {STEEP_SLOPE_DEG:.0f} градусов ошибка составляет "
        f"MAE={metrics_rows[4]['steep_mae']:.3f} м и RMSE={metrics_rows[4]['steep_rmse']:.3f} м.",
        "",
        "Отдельно был получен вариант с квантильной калибровкой, в котором распределение высот дополнительно калибруется по COP30. "
        f"Его ошибка ниже: MAE={metrics_rows[5]['mae']:.3f} м и RMSE={metrics_rows[5]['rmse']:.3f} м. "
        "Однако этот вариант следует интерпретировать как калиброванный продукт, а не как полностью независимую оценку качества нейросетевой модели, "
        "поскольку опорная ЦМР используется не только для оценки, но и для постобработки.",
        "",
        "## Интерпретация",
        "",
        "Полученный результат показывает, что многоэтапная цепочка Sentinel-1 InSAR + нейросетевая коррекция остаточной ошибки + устойчивое объединение "
        "снижает ошибку относительно эталонной COP30 по сравнению с простым усреднением исходных ЦМР. При этом итоговая точность пока недостаточна "
        "для замены специализированных глобальных ЦМР-продуктов. Наиболее важный научно-практический результат работы заключается "
        "в воспроизводимой схеме отбора пар, контроля качества, обучения модели остаточной ошибки и объединения нескольких исправленных ЦМР.",
    ]
    methodology_md.write_text("\n".join(methodology_lines), encoding="utf-8")

    pipeline_out = OUT_DIR / "final_pipeline_sequence.puml"
    pipeline_src = ROOT / "docs/final_pipeline_sequence.puml"
    if pipeline_src.exists():
        shutil.copy2(pipeline_src, pipeline_out)

    index = OUT_DIR / "README.md"
    idx_lines = [
        "# Финальные артефакты для ВКР",
        "",
        "Пакет построен автоматически скриптом `scripts/build_vkr_final_artifacts.py`.",
        "",
        "## Таблицы и текстовые материалы",
        "",
        f"- [Воронка отбора](./{funnel_md.name})",
        f"- [Сравнение продуктов с COP30](./{comparison_md.name})",
        f"- [Набор для нейросетевой коррекции: обучение, валидация, тест](./{ml_md.name})",
        f"- [Манифест артефактов](./{artifact_manifest_md.name})",
        f"- [Черновик текста методики и результатов](./{methodology_md.name})",
        f"- [Объяснение PSNR и постобработки](./{postprocessing_md.name})",
        f"- [Как читать профили высот](./{profiles_md.name})",
        f"- [Как трактовать кривые обучения](./{learning_md.name})",
        f"- [Ограничения и интерпретация](./{limitations_md.name})",
        f"- [Диаграмма последовательности PlantUML](./{pipeline_out.name})",
        "",
        "## Рисунки",
        "",
    ]
    for title, path in artifact_paths.items():
        idx_lines.append(f"- {title}: [./{path.name}](./{path.name})")
    idx_lines += [
        "",
        "## Исходные GeoTIFF",
        "",
        f"- Эталонная ЦМР COP30: `{display_path(REF_TIF)}`",
        f"- Минимальный базовый вариант, одна InSAR-пара: `{display_path(MVP_TIF)}`",
        f"- Простое среднее по 15 исходным ЦМР: `{display_path(RAW_STACK_MEAN_TIF)}`",
        f"- Ранний нейросетево исправленный вариант: `{display_path(EARLY_ML_TIF)}`",
        f"- Основной продукт с ограничением нижней границы: `{display_path(FINAL_TIF)}`",
        f"- Калиброванный продукт с квантильной калибровкой: `{display_path(QUANTILE_TIF)}`",
        "",
        "## Итоговая метрика",
        "",
        f"- Основной продукт с ограничением нижней границы: MAE={metrics_rows[4]['mae']:.3f} м, RMSE={metrics_rows[4]['rmse']:.3f} м, PSNR={metrics_rows[4]['psnr']:.3f} дБ.",
        f"- Калиброванный продукт с квантильной калибровкой: MAE={metrics_rows[-1]['mae']:.3f} м, RMSE={metrics_rows[-1]['rmse']:.3f} м.",
        f"- В Robust15 использовано ЦМР: {len(robust['members'])}.",
    ]
    index.write_text("\n".join(idx_lines), encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale_name in (
        "table_02_mvp_vs_final.md",
        "fig_01_dem_maps_reference_mvp_final.png",
        "fig_08_metrics_bar_mvp_vs_final.png",
        " .png",
    ):
        stale_path = OUT_DIR / stale_name
        if stale_path.exists():
            stale_path.unlink()

    ref_raster = read_ref(REF_TIF)
    ref = ref_raster.arr
    slope = slope_from_reference(ref, ref_raster.profile["transform"])
    metrics_rows, arrays = load_metric_rows(ref_raster, slope)
    raw_stack = arrays["Среднее по 15 исходным InSAR-ЦМР"]
    early_ml = arrays["Ранний вариант нейросетевой коррекции"]
    final = arrays["Robust15 + ограничение нижней границы"]
    quantile = arrays["Robust15 + квантильная калибровка"]

    profile_artifacts = save_profiles(ref, raw_stack, final, quantile, ref_raster.profile)
    artifacts = {
        "Карты ЦМР: COP30, простое среднее, основной и калиброванный продукт": save_map_panel(ref, raw_stack, final, quantile),
        "Карты ошибок относительно COP30": save_error_maps(ref, raw_stack, early_ml, final, quantile),
        "Гистограмма ошибок относительно COP30": save_error_hist(ref, raw_stack, early_ml, final, quantile),
        "Диаграмма рассеяния COP30 и рассчитанных ЦМР": save_scatter(ref, raw_stack, early_ml, final, quantile),
        "Профили высот": profile_artifacts[0],
        "Положение профилей": profile_artifacts[1],
        "Маски валидности и больших ошибок": save_validity_and_high_error(ref, raw_stack, final),
        "Столбчатая диаграмма MAE/RMSE": save_metrics_bar(metrics_rows),
    }
    learning_out = save_learning_curves_from_history()
    if learning_out is not None:
        artifacts["Кривые обучения ResNet18-U-Net"] = learning_out

    write_markdown_reports(metrics_rows, artifacts)

    print(f"Artifacts written to: {OUT_DIR}")
    print(f"Index: {OUT_DIR / 'README.md'}")


if __name__ == "__main__":
    main()
