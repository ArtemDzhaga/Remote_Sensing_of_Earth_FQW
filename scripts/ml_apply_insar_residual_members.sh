#!/usr/bin/env bash
set -euo pipefail

# Apply a trained residual model to each filtered InSAR DEM member, then stack
# the corrected DEMs on the COP30 grid.

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
RUN_NAME="${RUN_NAME:-$(basename "$(dirname "$CHECKPOINT")")}"

STACK_METRICS="${STACK_METRICS:-${VKR_RUN_ROOT}/insar/stack_roi_filtered/insar_stack_metrics.json}"
OUT_ROOT="${OUT_ROOT:-${VKR_RUN_ROOT}/ml_corrected_pairs/${RUN_NAME}}"
STACK_OUT_DIR="${STACK_OUT_DIR:-${VKR_RUN_ROOT}/ml_corrected_stack/${RUN_NAME}}"
MAX_RMSE="${MAX_RMSE:-500}"
MIN_PIXELS="${MIN_PIXELS:-50000}"
INFER_MODE="${INFER_MODE:-full}"

echo "checkpoint:    ${CHECKPOINT}"
echo "stack_metrics: ${STACK_METRICS}"
echo "out_root:      ${OUT_ROOT}"
echo "stack_out_dir: ${STACK_OUT_DIR}"
echo "infer_mode:    ${INFER_MODE}"

MEMBER_DEMS="$("$PYTHON" - "$STACK_METRICS" <<'PY'
import json
import sys
from pathlib import Path

metrics = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for row in metrics.get("members", []):
    path = row.get("path")
    if path:
        print(path)
PY
)"

while IFS= read -r dem_tif; do
  [[ -n "$dem_tif" ]] || continue
  pair_name="$(basename "$(dirname "$dem_tif")")"
  echo
  echo "===================================================================================================="
  echo "correcting: ${pair_name}"
  CHECKPOINT="$CHECKPOINT" \
  DEM_TIF="$dem_tif" \
  OUT_DIR="${OUT_ROOT}/${pair_name}" \
  OUT_TIF="${OUT_ROOT}/${pair_name}/dem_ml_corrected.tif" \
  MASK_TIF="${OUT_ROOT}/${pair_name}/dem_ml_valid_mask.tif" \
  FILLED_OUT_TIF="${OUT_ROOT}/${pair_name}/dem_ml_corrected_filled.tif" \
  FILL_TIF="" \
  STACK_METRICS="$STACK_METRICS" \
  INFER_MODE="$INFER_MODE" \
  "${SCRIPT_DIR}/ml_apply_insar_residual.sh"
done <<< "$MEMBER_DEMS"

PAIR_ROOT="$OUT_ROOT" \
OUT_DIR="$STACK_OUT_DIR" \
DEM_GLOB="*/dem_ml_corrected.tif" \
PRODUCT_PREFIX="ml_corrected_stack" \
MAX_RMSE="$MAX_RMSE" \
MIN_PIXELS="$MIN_PIXELS" \
"${SCRIPT_DIR}/insar_stack_roi_dems.sh"

echo
echo "corrected_stack: ${STACK_OUT_DIR}"
