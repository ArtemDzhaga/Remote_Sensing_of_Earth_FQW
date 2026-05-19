#!/usr/bin/env bash
set -euo pipefail

# Единые пути для InSAR-цепочки 2014-2026.
# Скрипты можно переопределять через env-переменные, но по умолчанию весь
# пайплайн работает с одной общей папкой на SSD.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

export VKR_DATA_ROOT="${VKR_DATA_ROOT:-${ROOT_DIR}/.local_data}"
# InSAR-цепочку держим в одной исторической папке, где уже лежат SLC и расчёты.
# Если нужно сознательно сменить дату папки, задайте VKR_INSAR_RUN_DATE.
export VKR_RUN_DATE="${VKR_INSAR_RUN_DATE:-2026-05-08}"
export PYTHONPATH="${PYTHONPATH:-${ROOT_DIR}/src}"
export COPYFILE_DISABLE=1

export VKR_OUTPUTS_ROOT="${VKR_OUTPUTS_ROOT:-${VKR_DATA_ROOT}/outputs}"
export VKR_RUN_ROOT="${VKR_RUN_ROOT:-${VKR_OUTPUTS_ROOT}/${VKR_RUN_DATE}}"

export VKR_REGION="${VKR_REGION:-sochi_khosta_mzymta_small}"
export VKR_SLC_RUN_NAME="${VKR_SLC_RUN_NAME:-slc_sochi_khosta_mzymta_small_2014-04-01_2026-05-01_20260508_023404}"
export VKR_SLC_DIR="${VKR_SLC_DIR:-${VKR_RUN_ROOT}/data/raw/slc_runs/${VKR_SLC_RUN_NAME}}"

export VKR_MANIFEST_UNIFIED="${VKR_MANIFEST_UNIFIED:-${VKR_OUTPUTS_ROOT}/slc_yearly_2014_2026_unified_manifest.json}"
export VKR_MANIFEST_BASE="${VKR_MANIFEST_BASE:-${VKR_OUTPUTS_ROOT}/slc_yearly_2014_2026_10_per_year_manifest.json}"
export VKR_MANIFEST_EXTRA="${VKR_MANIFEST_EXTRA:-${VKR_OUTPUTS_ROOT}/slc_yearly_2019_2026_10_per_year_manifest.json}"

if [[ -f "$VKR_MANIFEST_UNIFIED" ]]; then
  export VKR_MANIFEST_DEFAULT="$VKR_MANIFEST_UNIFIED"
else
  export VKR_MANIFEST_DEFAULT="$VKR_MANIFEST_BASE"
fi

export VKR_BASELINE_PREFLIGHT_DIR="${VKR_BASELINE_PREFLIGHT_DIR:-${VKR_RUN_ROOT}/insar/baseline_preflight}"
export VKR_FULL_PAIRS_DIR="${VKR_FULL_PAIRS_DIR:-${VKR_RUN_ROOT}/insar/full_pairs_roi}"
export VKR_STACK_DIR="${VKR_STACK_DIR:-${VKR_RUN_ROOT}/insar/stack_roi_filtered}"
