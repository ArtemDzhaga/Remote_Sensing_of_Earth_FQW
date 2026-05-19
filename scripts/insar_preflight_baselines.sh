#!/usr/bin/env bash
set -euo pipefail

# Пересчитать SNAP preflight для SLC-пар:
# - region берётся из dem.config.DEFAULT_REGION;
# - subswath по умолчанию auto;
# - burst по умолчанию all (0..0);
# - итоговый baseline_ok_pairs.json содержит только пары с пересечением региона.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT_DIR"

source "${SCRIPT_DIR}/insar_env.sh"

PYTHON="${PYTHON:-python}"
if [[ -z "${REGION:-}" ]]; then
  REGION="$("$PYTHON" - <<'PY'
from dem.config import DEFAULT_REGION
print(DEFAULT_REGION)
PY
)"
fi

MANIFEST="${MANIFEST:-$VKR_MANIFEST_DEFAULT}"
SLC_DIR="${SLC_DIR:-$VKR_SLC_DIR}"
OUT_DIR="${OUT_DIR:-$VKR_BASELINE_PREFLIGHT_DIR}"

LIMIT="${LIMIT:-0}"
SUBSWATH="${SUBSWATH:-auto}"
FIRST_BURST="${FIRST_BURST:-0}"
LAST_BURST="${LAST_BURST:-0}"
GPT_CACHE="${GPT_CACHE:-12G}"
GPT_THREADS="${GPT_THREADS:-4}"
CLEANUP_WORKDIRS="${CLEANUP_WORKDIRS:-1}"

CLEANUP_ARGS=()
if [[ "$CLEANUP_WORKDIRS" == "1" ]]; then
  CLEANUP_ARGS+=(--cleanup-workdirs)
fi

"$PYTHON" -m dem.insar.baseline_preflight \
  --manifest "$MANIFEST" \
  --slc-dir "$SLC_DIR" \
  --out-dir "$OUT_DIR" \
  --limit "$LIMIT" \
  --region "$REGION" \
  --subswath "$SUBSWATH" \
  --first-burst "$FIRST_BURST" \
  --last-burst "$LAST_BURST" \
  --gpt-cache "$GPT_CACHE" \
  --gpt-threads "$GPT_THREADS" \
  --eap-mode auto \
  --force \
  "${CLEANUP_ARGS[@]}"

echo
echo "Готово:"
echo "- ${OUT_DIR}/baseline_preflight.md"
echo "- ${OUT_DIR}/baseline_ok_pairs.md"
echo "- ${OUT_DIR}/baseline_ok_pairs.json"
