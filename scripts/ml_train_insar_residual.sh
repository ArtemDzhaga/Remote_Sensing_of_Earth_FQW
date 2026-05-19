#!/usr/bin/env bash
set -euo pipefail

# Обучить smoke/демо ML-модель residual-коррекции InSAR DEM.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT_DIR"

source "${SCRIPT_DIR}/insar_env.sh"

PYTHON="${PYTHON:-python}"
DATA_DIR="${DATA_DIR:-${VKR_RUN_ROOT}/data/processed/ml_insar_residual_dataset}"
EPOCHS="${EPOCHS:-20}"
BATCH_SIZE="${BATCH_SIZE:-4}"
LR="${LR:-0.001}"
DEVICE="${DEVICE:-auto}"
NUM_WORKERS="${NUM_WORKERS:-0}"
SEED="${SEED:-42}"
WEIGHT_DECAY="${WEIGHT_DECAY:-0.0001}"
ENCODER_NAME="${ENCODER_NAME:-resnet18}"
ENCODER_WEIGHTS="${ENCODER_WEIGHTS:-}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M%S)_insar_residual_${ENCODER_NAME}_unet_bs${BATCH_SIZE}_ep${EPOCHS}_lr${LR}_seed${SEED}}"
OUT_DIR="${OUT_DIR:-${VKR_RUN_ROOT}/models/insar_residual_runs/${RUN_ID}}"

echo "data:       ${DATA_DIR}"
echo "out:        ${OUT_DIR}"
echo "epochs:     ${EPOCHS}"
echo "batch_size: ${BATCH_SIZE}"
echo "lr:         ${LR}"
echo "seed:       ${SEED}"
echo "model:      ${ENCODER_NAME}-unet"

"$PYTHON" -m dem ml train \
  --data-dir "$DATA_DIR" \
  --out-dir "$OUT_DIR" \
  --epochs "$EPOCHS" \
  --batch-size "$BATCH_SIZE" \
  --lr "$LR" \
  --weight-decay "$WEIGHT_DECAY" \
  --num-workers "$NUM_WORKERS" \
  --device "$DEVICE" \
  --seed "$SEED" \
  --encoder-name "$ENCODER_NAME" \
  --encoder-weights "$ENCODER_WEIGHTS" \
  --require-smp

echo "checkpoint: ${OUT_DIR}/best.pt"
echo "metrics:    ${OUT_DIR}/best_metrics.json"
