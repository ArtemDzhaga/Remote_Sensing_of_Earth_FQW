#!/usr/bin/env bash
set -euo pipefail

# Build a calibrated weighted stack from all ML-corrected InSAR DEMs.
# The weights are estimated against the reference DEM, so this product is a
# calibrated/reporting stack, not an independent validation split.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT_DIR"

source "${SCRIPT_DIR}/insar_env.sh"

PYTHON="${PYTHON:-python}"
PAIR_ROOT="${PAIR_ROOT:-${VKR_RUN_ROOT}/ml_corrected_pairs/resnet18_unet_bs8_ep120_seed42_20260511}"
OUT_DIR="${OUT_DIR:-${VKR_RUN_ROOT}/ml_corrected_stack/resnet18_unet_bs8_ep120_seed42_20260511_robust15}"
DEM_GLOB="${DEM_GLOB:-*/dem_ml_corrected.tif}"
POWER="${POWER:-4}"
DYNAMIC_MIN_MAX="${DYNAMIC_MIN_MAX:-150}"
DYNAMIC_SCALE="${DYNAMIC_SCALE:-700}"
DYNAMIC_FLOOR="${DYNAMIC_FLOOR:-0.05}"

REF_TIF="${REF_TIF:-}"
if [[ -z "$REF_TIF" ]]; then
  REF_TIF="$("$PYTHON" - <<'PY'
from dem.io.layout import iter_reference_dem_processed_bases_newest_first
from dem.config import DEFAULT_REGION

for base in iter_reference_dem_processed_bases_newest_first():
    root = base / DEFAULT_REGION
    if root.is_dir():
        refs = sorted(root.rglob("*cop30*.tif"), key=lambda p: p.stat().st_mtime, reverse=True)
        if refs:
            print(refs[0])
            raise SystemExit(0)
raise SystemExit("No COP30 reference DEM found")
PY
)"
fi

echo "pair_root:       ${PAIR_ROOT}"
echo "dem_glob:        ${DEM_GLOB}"
echo "reference:       ${REF_TIF}"
echo "out_dir:         ${OUT_DIR}"
echo "weight_power:    ${POWER}"
echo "dynamic_min_max: ${DYNAMIC_MIN_MAX}"

"$PYTHON" - "$PAIR_ROOT" "$DEM_GLOB" "$REF_TIF" "$OUT_DIR" "$POWER" "$DYNAMIC_MIN_MAX" "$DYNAMIC_SCALE" "$DYNAMIC_FLOOR" <<'PY'
import json
import sys
from pathlib import Path

import numpy as np
import rasterio

pair_root = Path(sys.argv[1])
dem_glob = sys.argv[2]
reference = Path(sys.argv[3])
out_dir = Path(sys.argv[4])
power = float(sys.argv[5])
dynamic_min_max = float(sys.argv[6])
dynamic_scale = float(sys.argv[7])
dynamic_floor = float(sys.argv[8])
out_dir.mkdir(parents=True, exist_ok=True)

paths = sorted(pair_root.glob(dem_glob))
if not paths:
    raise SystemExit(f"No corrected DEM found in {pair_root} by glob={dem_glob!r}")

with rasterio.open(reference) as ref_src:
    ref = ref_src.read(1, masked=True).filled(np.nan).astype("float32")
    profile = ref_src.profile.copy()

arrays = []
members = []
for path in paths:
    with rasterio.open(path) as src:
        arr = src.read(1, masked=True).filled(np.nan).astype("float32")
    if arr.shape != ref.shape:
        raise SystemExit(f"Shape mismatch for {path}: {arr.shape} != {ref.shape}")
    valid = np.isfinite(arr) & np.isfinite(ref)
    if not valid.any():
        continue
    err = arr[valid] - ref[valid]
    rmse = float(np.sqrt(np.mean(err**2)))
    bias = float(np.mean(err))
    max_height = float(np.nanmax(arr))
    dynamic_score = float(np.clip((max_height - dynamic_min_max) / dynamic_scale, dynamic_floor, 1.0))
    weight = dynamic_score / max(rmse, 1e-6) ** power
    arrays.append(arr)
    members.append(
        {
            "pair": path.parent.name,
            "path": str(path),
            "pixels": int(valid.sum()),
            "min": float(np.nanmin(arr)),
            "max": max_height,
            "mean": float(np.nanmean(arr)),
            "std": float(np.nanstd(arr)),
            "mae": float(np.mean(np.abs(err))),
            "rmse": rmse,
            "bias": bias,
            "dynamic_score": dynamic_score,
            "raw_weight": float(weight),
        }
    )

if not arrays:
    raise SystemExit("No finite corrected DEMs to stack")

weights = np.array([m["raw_weight"] for m in members], dtype="float64")
weights = weights / np.sum(weights)
stack_arr = np.stack(arrays).astype("float32")
biases = np.array([m["bias"] for m in members], dtype="float32")[:, None, None]
calibrated = stack_arr - biases
finite = np.isfinite(calibrated)
weighted_sum = np.nansum(np.where(finite, calibrated, 0.0) * weights[:, None, None], axis=0)
weight_sum = np.sum(finite * weights[:, None, None], axis=0)
stack = np.where(weight_sum > 0, weighted_sum / weight_sum, np.nan).astype("float32")

for m, w in zip(members, weights):
    m["weight"] = float(w)

valid = np.isfinite(stack) & np.isfinite(ref)
err = stack[valid] - ref[valid]
summary = {
    "name": "robust15_dynamic_weighted_bias_corrected_mean",
    "pixels": int(valid.sum()),
    "mae": float(np.mean(np.abs(err))),
    "rmse": float(np.sqrt(np.mean(err**2))),
    "bias": float(np.mean(err)),
    "min": float(np.nanmin(stack)),
    "max": float(np.nanmax(stack)),
    "mean": float(np.nanmean(stack)),
    "std": float(np.nanstd(stack)),
}

profile.update(dtype="float32", count=1, nodata=np.nan, compress="lzw")
out_tif = out_dir / "ml_corrected_stack_robust15.tif"
with rasterio.open(out_tif, "w", **profile) as dst:
    dst.write(stack, 1)

report = {
    "reference": str(reference),
    "pair_root": str(pair_root),
    "dem_glob": dem_glob,
    "selection_note": "All listed DEMs are used. Weights and bias calibration are estimated against reference DEM; use this as calibrated product, not independent validation.",
    "weighting": {
        "formula": "dynamic_score / rmse**power, then normalized; stack uses candidate - global_bias",
        "power": power,
        "dynamic_min_max": dynamic_min_max,
        "dynamic_scale": dynamic_scale,
        "dynamic_floor": dynamic_floor,
    },
    "output": str(out_tif),
    "summary": summary,
    "members": members,
}
(out_dir / "robust_stack_metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

lines = [
    "# Robust15 ML-Corrected DEM Stack",
    "",
    "> Использованы все исправленные DEM из списка ниже. Веса и bias-калибровка рассчитаны по COP30 reference DEM, поэтому это калиброванный продукт, а не независимая оценка обобщения.",
    "",
    f"- reference: `{reference}`",
    f"- output: `{out_tif}`",
    f"- members: `{len(members)}`",
    f"- formula: `dynamic_score / rmse**{power:g}`, затем `candidate - bias`",
    f"- pixels: `{summary['pixels']}`",
    f"- MAE: `{summary['mae']:.3f}`",
    f"- RMSE: `{summary['rmse']:.3f}`",
    f"- bias: `{summary['bias']:.3f}`",
    f"- min/max/mean/std: `{summary['min']:.3f}` / `{summary['max']:.3f}` / `{summary['mean']:.3f}` / `{summary['std']:.3f}`",
    "",
    "| pair | weight | pixels | min | max | MAE | RMSE | bias | dynamic_score |",
    "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
]
for row in sorted(members, key=lambda x: x["weight"], reverse=True):
    lines.append(
        f"| {row['pair']} | {row['weight']:.6f} | {row['pixels']} | {row['min']:.1f} | {row['max']:.1f} | "
        f"{row['mae']:.3f} | {row['rmse']:.3f} | {row['bias']:.3f} | {row['dynamic_score']:.3f} |"
    )
(out_dir / "robust_stack_metrics.md").write_text("\n".join(lines), encoding="utf-8")

print(f"output: {out_tif}")
print(f"report: {out_dir / 'robust_stack_metrics.md'}")
print(f"members: {len(members)}")
print(f"MAE={summary['mae']:.3f} RMSE={summary['rmse']:.3f} bias={summary['bias']:.3f}")
print(f"min={summary['min']:.3f} max={summary['max']:.3f} mean={summary['mean']:.3f} std={summary['std']:.3f}")
PY
