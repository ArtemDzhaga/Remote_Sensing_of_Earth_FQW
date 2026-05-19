#!/usr/bin/env bash
set -euo pipefail

# Применить обученную residual-модель к InSAR DEM и записать corrected GeoTIFF.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT_DIR"

source "${SCRIPT_DIR}/insar_env.sh"

PYTHON="${PYTHON:-python}"
RUN_DIR="${RUN_DIR:-}"
if [[ -n "$RUN_DIR" && -z "${CHECKPOINT:-}" ]]; then
  CHECKPOINT="${RUN_DIR}/best.pt"
fi
CHECKPOINT="${CHECKPOINT:-${VKR_RUN_ROOT}/models/insar_residual_mvp/best.pt}"
RUN_NAME="$(basename "$(dirname "$CHECKPOINT")")"

STACK_METRICS="${STACK_METRICS:-${VKR_RUN_ROOT}/insar/stack_roi_filtered/insar_stack_metrics.json}"
NORMALIZATION="${NORMALIZATION:-${VKR_RUN_ROOT}/data/processed/ml_insar_residual_dataset/normalization.json}"
PATCH_SIZE="${PATCH_SIZE:-128}"
OVERLAP="${OVERLAP:-32}"
INFER_MODE="${INFER_MODE:-full}"
DEVICE="${DEVICE:-auto}"

REF_TIF="${REF_TIF:-}"
if [[ -z "$REF_TIF" ]]; then
  REF_TIF="$("$PYTHON" - "$STACK_METRICS" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
ref = Path(data["reference"])
if not ref.is_absolute():
    ref = Path.cwd() / ref
print(ref)
PY
)"
fi

DEM_TIF="${DEM_TIF:-}"
if [[ -z "$DEM_TIF" ]]; then
  STACK_MEDIAN="${VKR_RUN_ROOT}/insar/stack_roi_filtered/insar_stack_median.tif"
  if [[ -f "$STACK_MEDIAN" ]]; then
    DEM_TIF="$STACK_MEDIAN"
  else
    DEM_TIF="$("$PYTHON" - "$STACK_METRICS" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
members = data.get("members", [])
if not members:
    raise SystemExit(f"Нет members в {sys.argv[1]}")
best = min(members, key=lambda r: float(r.get("rmse", float("inf"))))
print(best["path"])
PY
)"
  fi
fi

if [[ "$(basename "$DEM_TIF")" == "insar_stack_median.tif" ]]; then
  PAIR_NAME="insar_stack_median"
else
  PAIR_NAME="$(basename "$(dirname "$DEM_TIF")")"
fi
OUT_DIR="${OUT_DIR:-${VKR_RUN_ROOT}/ml_corrected/${RUN_NAME}/${PAIR_NAME}}"
OUT_TIF="${OUT_TIF:-${OUT_DIR}/dem_ml_corrected.tif}"
MASK_TIF="${MASK_TIF:-${OUT_DIR}/dem_ml_valid_mask.tif}"
FILL_TIF="${FILL_TIF:-${VKR_RUN_ROOT}/insar/stack_roi_filtered/insar_stack_median.tif}"
FILLED_OUT_TIF="${FILLED_OUT_TIF:-${OUT_DIR}/dem_ml_corrected_filled.tif}"

echo "checkpoint:     ${CHECKPOINT}"
echo "input_dem:      ${DEM_TIF}"
echo "reference_grid: ${REF_TIF}"
echo "normalization:  ${NORMALIZATION}"
echo "infer_mode:     ${INFER_MODE}"
echo "out_tif:        ${OUT_TIF}"
echo "mask_tif:       ${MASK_TIF}"
if [[ -f "$FILL_TIF" ]]; then
  echo "fill_tif:       ${FILL_TIF}"
  echo "filled_out_tif: ${FILLED_OUT_TIF}"
fi

CMD=(
  "$PYTHON" -m dem ml infer
  --checkpoint "$CHECKPOINT" \
  --channel "$DEM_TIF" \
  --normalization "$NORMALIZATION" \
  --reference-grid "$REF_TIF" \
  --residual-base-channel 0 \
  --patch-size "$PATCH_SIZE" \
  --overlap "$OVERLAP" \
  --mode "$INFER_MODE" \
  --device "$DEVICE" \
  --mask-out-tif "$MASK_TIF" \
  --out-tif "$OUT_TIF"
)
if [[ -f "$FILL_TIF" ]]; then
  CMD+=(--fill-tif "$FILL_TIF" --filled-out-tif "$FILLED_OUT_TIF")
fi

"${CMD[@]}"

echo "corrected_dem: ${OUT_TIF}"
if [[ -f "$FILLED_OUT_TIF" ]]; then
  echo "filled_dem:    ${FILLED_OUT_TIF}"
fi
