#!/usr/bin/env bash
set -euo pipefail

# Проверка одного InSAR DEM:
# 1) базовая статистика GeoTIFF через gdalinfo;
# 2) карта/гистограмма через dem.viz.validate_dem;
# 3) MAE/RMSE/bias/PSNR относительно COP30 через dem.viz.compare_dems.
#
# По умолчанию берётся уже полученный DEM первой полной пары на SSD.
# При необходимости можно переопределить DEM_TIF, REF_TIF, REPORT_DIR, REGION.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT_DIR"

export VKR_DATA_ROOT="${VKR_DATA_ROOT:-${ROOT_DIR}/.local_data}"
export PYTHONPATH="${PYTHONPATH:-${ROOT_DIR}/src}"
export MPLCONFIGDIR="${MPLCONFIGDIR:-/private/tmp/vkr_matplotlib_cache}"

PYTHON="${PYTHON:-python}"
if [[ -z "${REGION:-}" ]]; then
  REGION="$("$PYTHON" - <<'PY'
from dem.config import DEFAULT_REGION
print(DEFAULT_REGION)
PY
)"
fi
export REGION

if [[ -z "${DEM_TIF:-}" ]]; then
  DEM_TIF="$("$PYTHON" - <<'PY'
from pathlib import Path
from dem.io.layout import data_root

roots = [
    data_root() / "outputs",
    Path.cwd() / "outputs",
]
candidates = []
for root in roots:
    if root.is_dir():
        candidates.extend(p for p in root.glob("*/insar/full_pairs/**/dem_insar.tif") if p.is_file())
        candidates.extend(p for p in root.glob("*/insar/pairs/**/dem_insar.tif") if p.is_file())
if not candidates:
    raise SystemExit("dem_insar.tif was not found. Set DEM_TIF=/path/to/dem_insar.tif.")
print(sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0])
PY
)"
fi

if [[ -z "${REF_TIF:-}" ]]; then
  REF_TIF="$("$PYTHON" - <<'PY'
from pathlib import Path
import os

from dem.io.layout import iter_reference_dem_processed_bases_newest_first

region = os.environ["REGION"]
candidates = []
for base in iter_reference_dem_processed_bases_newest_first():
    root = base / region
    if root.is_dir():
        candidates.extend(p for p in root.rglob("*cop30*.tif") if p.is_file())
if not candidates:
    raise SystemExit(f"COP30 reference DEM was not found for region={region}.")
print(sorted(candidates, key=lambda p: (p.suffix, p.stat().st_mtime), reverse=True)[0])
PY
)"
fi

PAIR_DIR="$(dirname "$DEM_TIF")"
REPORT_DIR="${REPORT_DIR:-${PAIR_DIR}/quality_check}"

if [[ ! -f "$DEM_TIF" ]]; then
  echo "DEM_TIF не найден: $DEM_TIF" >&2
  exit 1
fi

if [[ ! -f "$REF_TIF" ]]; then
  echo "REF_TIF не найден: $REF_TIF" >&2
  exit 1
fi

mkdir -p "$REPORT_DIR"

echo "DEM_TIF:    $DEM_TIF"
echo "REF_TIF:    $REF_TIF"
echo "REPORT_DIR: $REPORT_DIR"
echo

if command -v gdalinfo >/dev/null 2>&1; then
  gdalinfo -stats "$DEM_TIF" > "${REPORT_DIR}/gdalinfo_dem_insar.txt"
  echo "GDAL info: ${REPORT_DIR}/gdalinfo_dem_insar.txt"
else
  echo "gdalinfo не найден, пропускаю GDAL-статистику."
fi

"$PYTHON" -m dem.viz.validate_dem "$DEM_TIF" \
  --region "$REGION" \
  --out-dir "${REPORT_DIR}/dem_visual_quality" \
  --flat \
  --no-3d \
  --no-html

"$PYTHON" -m dem.viz.compare_dems \
  --reference "$REF_TIF" \
  --candidate "insar=${DEM_TIF}" \
  --out-dir "${REPORT_DIR}/dem_vs_cop30_metrics"

"$PYTHON" - "${REPORT_DIR}/dem_vs_cop30_metrics/dem_comparison_metrics.json" <<'PY'
import json
import os
import sys
from pathlib import Path

metrics_path = Path(sys.argv[1])
data = json.loads(metrics_path.read_text(encoding="utf-8"))
row = data["rows"][0]
all_metrics = row["all"]
print()
print("Краткая метрика insar vs COP30:")
print(f"- pixels: {all_metrics['pixels']}")
print(f"- MAE:    {all_metrics['mae']}")
print(f"- RMSE:   {all_metrics['rmse']}")
print(f"- bias:   {all_metrics['bias']}")
if all_metrics["pixels"] == 0:
    print("- WARNING: пересечения с reference DEM нет; проверь burst/subswath/географию пары.")
    if os.environ.get("STRICT_VALIDATION", "0") == "1":
        raise SystemExit(2)
if all_metrics["rmse"] != all_metrics["rmse"] or all_metrics["rmse"] > 500:
    print("- ERROR: RMSE слишком большой для контрольного прогона; полный пакет запускать нельзя.")
    if os.environ.get("STRICT_VALIDATION", "0") == "1":
        raise SystemExit(3)
PY

echo
echo "Готово. Основные отчёты:"
echo "- ${REPORT_DIR}/dem_visual_quality/$(basename "$DEM_TIF" .tif)_report.md"
echo "- ${REPORT_DIR}/dem_vs_cop30_metrics/dem_comparison_metrics.md"
