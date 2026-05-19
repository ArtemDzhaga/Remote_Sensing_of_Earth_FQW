# -*- coding: utf-8 -*-
"""
Быстрый preview "когерентности" по амплитудным данным (proxy).

Важно:
- Это НЕ истинная интерферометрическая когерентность из комплексных SLC.
- Используется для быстрой визуальной оценки согласованности двух амплитудных растров.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import rasterio
from rasterio.warp import reproject
from rasterio.enums import Resampling

from dem.io.layout import insar_dir, resolve_out_dir


def _read_band(path: Path, band: int) -> tuple[np.ndarray, dict]:
    with rasterio.open(path) as src:
        arr = src.read(band).astype(np.float32)
        meta = {
            "crs": src.crs,
            "transform": src.transform,
            "width": src.width,
            "height": src.height,
            "nodata": src.nodata,
            "bounds": src.bounds,
        }
    return arr, meta


def _reproject_like(src_arr: np.ndarray, src_meta: dict, dst_meta: dict) -> np.ndarray:
    out = np.full((dst_meta["height"], dst_meta["width"]), np.nan, dtype=np.float32)
    reproject(
        source=src_arr,
        destination=out,
        src_transform=src_meta["transform"],
        src_crs=src_meta["crs"],
        dst_transform=dst_meta["transform"],
        dst_crs=dst_meta["crs"],
        src_nodata=src_meta["nodata"],
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )
    return out


def _local_corr(a: np.ndarray, b: np.ndarray, win: int) -> np.ndarray:
    # Маска валидных значений
    m = np.isfinite(a) & np.isfinite(b)
    a0 = np.where(m, a, 0.0).astype(np.float32)
    b0 = np.where(m, b, 0.0).astype(np.float32)
    w = np.where(m, 1.0, 0.0).astype(np.float32)

    k = (win, win)
    sw = cv2.blur(w, k, borderType=cv2.BORDER_REFLECT)
    ma = cv2.blur(a0, k, borderType=cv2.BORDER_REFLECT) / np.maximum(sw, 1e-6)
    mb = cv2.blur(b0, k, borderType=cv2.BORDER_REFLECT) / np.maximum(sw, 1e-6)

    a2 = cv2.blur(a0 * a0, k, borderType=cv2.BORDER_REFLECT) / np.maximum(sw, 1e-6)
    b2 = cv2.blur(b0 * b0, k, borderType=cv2.BORDER_REFLECT) / np.maximum(sw, 1e-6)
    ab = cv2.blur(a0 * b0, k, borderType=cv2.BORDER_REFLECT) / np.maximum(sw, 1e-6)

    va = np.maximum(a2 - ma * ma, 0.0)
    vb = np.maximum(b2 - mb * mb, 0.0)
    cov = ab - ma * mb
    corr = cov / np.maximum(np.sqrt(va * vb), 1e-6)
    corr = np.clip(corr, -1.0, 1.0)
    corr[sw < 1e-3] = np.nan
    return corr


def main() -> None:
    p = argparse.ArgumentParser(description="Карта амплитудной согласованности (proxy coherence).")
    p.add_argument("--master", type=str, required=True, help="Master amplitude GeoTIFF")
    p.add_argument("--slave", type=str, required=True, help="Slave amplitude GeoTIFF")
    p.add_argument("--band", type=int, default=1, help="Band index (обычно 1=VV)")
    p.add_argument("--window", type=int, default=21, help="Окно локальной корреляции (нечетное число)")
    p.add_argument(
        "--out",
        type=str,
        default="",
        help="PNG; пусто = outputs/<дата>/insar/coherence_preview.png.",
    )
    args = p.parse_args()

    master_path = Path(args.master)
    slave_path = Path(args.slave)
    out_png = resolve_out_dir(args.out, lambda: insar_dir() / "coherence_preview.png")
    out_png.parent.mkdir(parents=True, exist_ok=True)

    a, am = _read_band(master_path, args.band)
    b, bm = _read_band(slave_path, args.band)
    b_r = _reproject_like(b, bm, am)

    # Лог-амплитуда для устойчивости.
    a_log = np.log10(np.maximum(a, 0.0) + 1e-6)
    b_log = np.log10(np.maximum(b_r, 0.0) + 1e-6)
    coh = _local_corr(a_log, b_log, max(3, args.window | 1))

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 1, figsize=(10, 8))
    im = ax.imshow(coh, cmap="viridis", vmin=0, vmax=1)
    ax.set_title("Amplitude consistency (proxy), NOT true InSAR coherence")
    plt.colorbar(im, ax=ax, label="0..1")
    plt.tight_layout()
    plt.savefig(out_png, dpi=160)
    plt.close(fig)

    valid = coh[np.isfinite(coh)]
    stats = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "master": master_path.as_posix(),
        "slave": slave_path.as_posix(),
        "band": args.band,
        "window": int(args.window),
        "mean_proxy_coherence": float(np.nanmean(valid)) if valid.size else float("nan"),
        "p10": float(np.nanpercentile(valid, 10)) if valid.size else float("nan"),
        "p50": float(np.nanpercentile(valid, 50)) if valid.size else float("nan"),
        "p90": float(np.nanpercentile(valid, 90)) if valid.size else float("nan"),
        "output_png": out_png.as_posix(),
    }
    out_json = out_png.with_suffix(".json")
    out_json.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote: {out_png}")
    print(f"Wrote: {out_json}")


if __name__ == "__main__":
    main()

