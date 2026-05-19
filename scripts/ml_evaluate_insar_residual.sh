#!/usr/bin/env bash
set -euo pipefail

# Оценить best.pt на test/val/train split и собрать отчёт "до/после ML".

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT_DIR"

source "${SCRIPT_DIR}/insar_env.sh"

PYTHON="${PYTHON:-python}"
DATA_DIR="${DATA_DIR:-${VKR_RUN_ROOT}/data/processed/ml_insar_residual_dataset}"
RUN_DIR="${RUN_DIR:-}"
if [[ -n "$RUN_DIR" && -z "${CHECKPOINT:-}" ]]; then
  CHECKPOINT="${RUN_DIR}/best.pt"
fi
CHECKPOINT="${CHECKPOINT:-${VKR_RUN_ROOT}/models/insar_residual_mvp/best.pt}"
RUN_NAME="$(basename "$(dirname "$CHECKPOINT")")"
OUT_DIR="${OUT_DIR:-${VKR_RUN_ROOT}/ml_eval/${RUN_NAME}}"
SPLIT="${SPLIT:-test}"
BATCH_SIZE="${BATCH_SIZE:-16}"
DEVICE="${DEVICE:-auto}"
NUM_WORKERS="${NUM_WORKERS:-0}"
ENCODER_NAME="${ENCODER_NAME:-resnet18}"

echo "checkpoint: ${CHECKPOINT}"
echo "data:       ${DATA_DIR}"
echo "split:      ${SPLIT}"
echo "out:        ${OUT_DIR}"

"$PYTHON" -m dem ml evaluate \
  --checkpoint "$CHECKPOINT" \
  --data-dir "$DATA_DIR" \
  --split "$SPLIT" \
  --out-dir "$OUT_DIR" \
  --batch-size "$BATCH_SIZE" \
  --num-workers "$NUM_WORKERS" \
  --device "$DEVICE" \
  --encoder-name "$ENCODER_NAME" \
  --require-smp
