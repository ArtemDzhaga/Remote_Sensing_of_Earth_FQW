#!/usr/bin/env bash
set -euo pipefail

# Physical / reference-calibrated post-processing for a DEM GeoTIFF.
# Modes:
# - clip_reference_min: clamp only values below the minimum reference DEM elevation.
# - quantile_reference: match candidate hypsometry to the reference DEM distribution.
# - floor0: legacy coastal clamp to 0 m; use only when explicitly justified.
# - quantile_floor0: legacy quantile calibration with a 0 m clamp.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT_DIR"

source "${SCRIPT_DIR}/insar_env.sh"

PYTHON="${PYTHON:-python}"
IN_TIF="${IN_TIF:-${VKR_RUN_ROOT}/ml_corrected_stack/resnet18_unet_bs8_ep120_seed42_20260511_robust15/ml_corrected_stack_robust15.tif}"
MODE="${MODE:-clip_reference_min}"
OUT_DIR="${OUT_DIR:-$(dirname "$IN_TIF")}"
OUT_TIF="${OUT_TIF:-${OUT_DIR}/$(basename "$IN_TIF" .tif)_${MODE}.tif}"
REPORT_MD="${REPORT_MD:-${OUT_DIR}/$(basename "$OUT_TIF" .tif)_postprocess.md}"

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

echo "input:     ${IN_TIF}"
echo "reference: ${REF_TIF}"
echo "mode:      ${MODE}"
echo "output:    ${OUT_TIF}"
echo "report:    ${REPORT_MD}"

"$PYTHON" - "$IN_TIF" "$REF_TIF" "$MODE" "$OUT_TIF" "$REPORT_MD" <<'PY'
import json
import sys
from pathlib import Path

import numpy as np
import rasterio

in_tif = Path(sys.argv[1])
ref_tif = Path(sys.argv[2])
mode = sys.argv[3]
out_tif = Path(sys.argv[4])
report_md = Path(sys.argv[5])

with rasterio.open(in_tif) as src:
    arr = src.read(1, masked=True).filled(np.nan).astype("float32")
    profile = src.profile.copy()
with rasterio.open(ref_tif) as src:
    ref = src.read(1, masked=True).filled(np.nan).astype("float32")

if arr.shape != ref.shape:
    raise SystemExit(f"Shape mismatch: {arr.shape} != {ref.shape}")

valid = np.isfinite(arr) & np.isfinite(ref)
ref_min = float(np.nanmin(ref[valid]))
ref_max = float(np.nanmax(ref[valid]))

if mode == "clip_reference_min":
    out = np.where(np.isfinite(arr), np.maximum(arr, ref_min), np.nan).astype("float32")
    note = (
        "Физическое ограничение нижнего хвоста: значения ниже минимальной высоты reference DEM "
        f"({ref_min:.3f} м) заменены на этот минимум. Жёсткого ограничения в 0 м нет."
    )
elif mode == "quantile_reference":
    qs = np.array([0, 0.1, 0.5, 1, 2, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 98, 99, 99.5, 99.9, 100])
    src_q = np.nanpercentile(arr[valid], qs)
    ref_q = np.nanpercentile(ref[valid], qs)
    out = np.interp(arr, src_q, ref_q, left=ref_q[0], right=ref_q[-1]).astype("float32")
    out = np.where(np.isfinite(out), np.clip(out, ref_min, ref_max), np.nan).astype("float32")
    note = (
        "Гипсометрическая калибровка по COP30: распределение высот DEM приведено к reference DEM. "
        "Это калиброванный продукт, а не независимая оценка обобщения."
    )
elif mode == "floor0":
    out = np.where(np.isfinite(arr), np.maximum(arr, 0.0), np.nan).astype("float32")
    note = "Legacy режим: отрицательные высоты заменены на 0 м. Сейчас не используется как основной продукт."
elif mode == "quantile_floor0":
    qs = np.array([0, 0.1, 0.5, 1, 2, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 98, 99, 99.5, 99.9, 100])
    src_q = np.nanpercentile(arr[valid], qs)
    ref_q = np.nanpercentile(ref[valid], qs)
    out = np.interp(arr, src_q, ref_q, left=ref_q[0], right=ref_q[-1]).astype("float32")
    out = np.where(np.isfinite(out), np.maximum(out, 0.0), np.nan).astype("float32")
    note = "Legacy режим: quantile calibration + 0 м clamp. Сейчас не используется как основной продукт."
else:
    raise SystemExit(f"Unknown mode: {mode}. Expected: clip_reference_min, quantile_reference, floor0, quantile_floor0")

def metrics(x: np.ndarray) -> dict[str, float]:
    m = np.isfinite(x) & np.isfinite(ref)
    d = x[m] - ref[m]
    return {
        "pixels": int(m.sum()),
        "mae": float(np.mean(np.abs(d))),
        "rmse": float(np.sqrt(np.mean(d**2))),
        "bias": float(np.mean(d)),
        "min": float(np.nanmin(x)),
        "max": float(np.nanmax(x)),
        "mean": float(np.nanmean(x)),
        "std": float(np.nanstd(x)),
        "negative_pixels": int(np.sum(x < 0)),
    }

before = metrics(arr)
after = metrics(out)
profile.update(dtype="float32", count=1, nodata=np.nan, compress="lzw")
out_tif.parent.mkdir(parents=True, exist_ok=True)
with rasterio.open(out_tif, "w", **profile) as dst:
    dst.write(out, 1)

json_path = report_md.with_suffix(".json")
json_path.write_text(json.dumps({"input": str(in_tif), "reference": str(ref_tif), "mode": mode, "note": note, "before": before, "after": after}, ensure_ascii=False, indent=2), encoding="utf-8")
lines = [
    f"# DEM Postprocess: {mode}",
    "",
    f"- input: `{in_tif}`",
    f"- output: `{out_tif}`",
    f"- reference: `{ref_tif}`",
    f"- note: {note}",
    "",
    "| state | pixels | MAE | RMSE | bias | min | max | mean | std | negative px |",
    "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
]
for name, row in [("before", before), ("after", after)]:
    lines.append(
        f"| {name} | {row['pixels']} | {row['mae']:.3f} | {row['rmse']:.3f} | {row['bias']:.3f} | "
        f"{row['min']:.3f} | {row['max']:.3f} | {row['mean']:.3f} | {row['std']:.3f} | {row['negative_pixels']} |"
    )
report_md.write_text("\n".join(lines), encoding="utf-8")

print(f"output: {out_tif}")
print(f"report: {report_md}")
print(f"after: MAE={after['mae']:.3f} RMSE={after['rmse']:.3f} bias={after['bias']:.3f} min={after['min']:.3f} max={after['max']:.3f}")
PY
