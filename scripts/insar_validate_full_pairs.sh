#!/usr/bin/env bash
set -euo pipefail

# Последовательно проверить все dem_insar.tif из каталога full_pairs.
#
# Управление:
#   LIMIT=3 scripts/insar_validate_full_pairs.sh
#   PAIR_ROOT=/path/to/full_pairs scripts/insar_validate_full_pairs.sh

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
export REGION

PAIR_ROOT="${PAIR_ROOT:-$VKR_FULL_PAIRS_DIR}"
LIMIT="${LIMIT:-0}"

if [[ ! -d "$PAIR_ROOT" ]]; then
  echo "PAIR_ROOT не найден: $PAIR_ROOT" >&2
  exit 1
fi

DEMS=()
while IFS= read -r dem_path; do
  DEMS+=("$dem_path")
done < <(find "$PAIR_ROOT" -mindepth 2 -maxdepth 2 -name dem_insar.tif -type f | sort)

if [[ "${#DEMS[@]}" -eq 0 ]]; then
  echo "В $PAIR_ROOT пока нет dem_insar.tif" >&2
  exit 1
fi

COUNT="${#DEMS[@]}"
if [[ "$LIMIT" -gt 0 && "$LIMIT" -lt "$COUNT" ]]; then
  COUNT="$LIMIT"
fi

echo "DEM files found: ${#DEMS[@]}"
echo "DEM files to validate: $COUNT"
echo

for ((i=0; i<COUNT; i++)); do
  DEM_TIF="${DEMS[$i]}"
  PAIR_DIR="$(dirname "$DEM_TIF")"
  REPORT_DIR="${PAIR_DIR}/quality_check"
  echo "===================================================================================================="
  echo "[$((i + 1))/$COUNT] $DEM_TIF"
  STRICT_VALIDATION="${STRICT_VALIDATION:-0}" DEM_TIF="$DEM_TIF" REPORT_DIR="$REPORT_DIR" REGION="$REGION" "${SCRIPT_DIR}/insar_validate_dem_against_reference.sh"
done

echo
echo "Все проверки завершены."
