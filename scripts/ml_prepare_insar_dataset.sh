#!/usr/bin/env bash
set -euo pipefail

# Подготовить train/val/test NPZ-патчи по отобранным InSAR DEM.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT_DIR"

source "${SCRIPT_DIR}/insar_env.sh"

PYTHON="${PYTHON:-python}"
STACK_METRICS="${STACK_METRICS:-${VKR_STACK_DIR}/insar_stack_metrics.json}"
OUT_DIR="${OUT_DIR:-${VKR_RUN_ROOT}/data/processed/ml_insar_residual_dataset}"
MAX_RMSE="${MAX_RMSE:-200}"
MIN_PIXELS="${MIN_PIXELS:-50000}"
MAX_PAIRS="${MAX_PAIRS:-0}"
PATCH_SIZE="${PATCH_SIZE:-128}"
OVERLAP="${OVERLAP:-32}"
MIN_VALID_FRACTION="${MIN_VALID_FRACTION:-0.65}"
MAX_ABS_RESIDUAL="${MAX_ABS_RESIDUAL:-500}"

"$PYTHON" -m dem ml prepare-insar-dataset \
  --stack-metrics "$STACK_METRICS" \
  --out-dir "$OUT_DIR" \
  --max-rmse "$MAX_RMSE" \
  --min-pixels "$MIN_PIXELS" \
  --max-pairs "$MAX_PAIRS" \
  --patch-size "$PATCH_SIZE" \
  --overlap "$OVERLAP" \
  --min-valid-fraction "$MIN_VALID_FRACTION" \
  --max-abs-residual "$MAX_ABS_RESIDUAL" \
  --force
