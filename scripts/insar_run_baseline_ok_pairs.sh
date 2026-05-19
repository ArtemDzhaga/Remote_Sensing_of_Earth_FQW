#!/usr/bin/env bash
set -euo pipefail

# Последовательный полный прогон всех SLC-пар, которые прошли baseline_preflight
# и имеют baseline_status=ok.
#
# Управление:
#   LIMIT=2   scripts/insar_run_baseline_ok_pairs.sh   # прогнать первые 2 пары
#   START=4   scripts/insar_run_baseline_ok_pairs.sh   # начать с 4-й строки ok-списка
#   DRY_RUN=1 scripts/insar_run_baseline_ok_pairs.sh   # только показать команды

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT_DIR"

source "${SCRIPT_DIR}/insar_env.sh"
export SNAPHU_EXEC="${SNAPHU_EXEC:-snaphu}"

PYTHON="${PYTHON:-python}"
if [[ -z "${REGION:-}" ]]; then
  REGION="$("$PYTHON" - <<'PY'
from dem.config import DEFAULT_REGION
print(DEFAULT_REGION)
PY
)"
fi

OK_PAIRS_JSON="${OK_PAIRS_JSON:-${VKR_BASELINE_PREFLIGHT_DIR}/baseline_ok_pairs.json}"
SLC_DIR="${SLC_DIR:-$VKR_SLC_DIR}"
OUT_DIR="${OUT_DIR:-$VKR_FULL_PAIRS_DIR}"

SUBSWATH="${SUBSWATH:-auto}"
POLARIZATION="${POLARIZATION:-VV}"
FIRST_BURST="${FIRST_BURST:-0}"
LAST_BURST="${LAST_BURST:-0}"
GPT_CACHE="${GPT_CACHE:-12G}"
GPT_THREADS="${GPT_THREADS:-4}"

START="${START:-1}"
LIMIT="${LIMIT:-0}"
DRY_RUN="${DRY_RUN:-0}"
PAIR_ORDER="${PAIR_ORDER:-quality}"

if [[ ! -f "$OK_PAIRS_JSON" ]]; then
  echo "Не найден OK_PAIRS_JSON: $OK_PAIRS_JSON" >&2
  exit 1
fi

if [[ ! -d "$SLC_DIR" ]]; then
  echo "Не найден SLC_DIR: $SLC_DIR" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"

"$PYTHON" - "$OK_PAIRS_JSON" "$SLC_DIR" "$OUT_DIR" "$REGION" "$SUBSWATH" "$POLARIZATION" "$FIRST_BURST" "$LAST_BURST" "$GPT_CACHE" "$GPT_THREADS" "$START" "$LIMIT" "$DRY_RUN" <<'PY'
import json
import os
import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

from dem.config import REGIONS
from dem.geo.utils import region_bbox

(
    ok_pairs_json,
    slc_dir,
    out_dir,
    region_default,
    subswath,
    polarization,
    first_burst,
    last_burst,
    gpt_cache,
    gpt_threads,
    start,
    limit,
    dry_run,
) = sys.argv[1:]

ok_pairs_json = Path(ok_pairs_json)
slc_dir = Path(slc_dir)
out_dir = Path(out_dir)
start_i = int(start)
limit_i = int(limit)
dry = dry_run == "1"

rows = json.loads(ok_pairs_json.read_text(encoding="utf-8"))
rows = [r for r in rows if r.get("status") == "ok" and r.get("baseline_status") == "ok"]
if os.environ.get("PAIR_ORDER", "quality") == "quality":
    def score(row: dict) -> tuple[float, float, float]:
        dt = abs(float(row.get("dt_days") or 999.0) - 12.0)
        baseline = abs(abs(float(row.get("baseline_m") or 0.0)) - 200.0)
        eap_penalty = 20.0 if (row.get("eap_correction") or "none") != "none" else 0.0
        return (dt, baseline + eap_penalty, float(row.get("index") or 999999))

    rows = sorted(rows, key=score)
rows = rows[start_i - 1 :]
if limit_i > 0:
    rows = rows[:limit_i]

zips = [p for p in slc_dir.rglob("*.zip") if not p.name.startswith("._")]

def resolve_slc(scene_id: str) -> Path:
    exact = slc_dir / f"{scene_id}.zip"
    if exact.is_file():
        return exact
    matches = [p for p in zips if p.name.startswith(scene_id)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise SystemExit(f"SLC ZIP не найден для {scene_id}")
    raise SystemExit(f"Найдено несколько SLC ZIP для {scene_id}: {matches}")


def intersects(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return a[0] <= b[2] and a[2] >= b[0] and a[1] <= b[3] and a[3] >= b[1]


def burst_windows(zip_path: Path, *, region: str, polarization: str) -> dict[str, list[int]]:
    reg = region_bbox(REGIONS[region])
    region_bounds = (float(reg["west"]), float(reg["south"]), float(reg["east"]), float(reg["north"]))
    out: dict[str, list[int]] = {}
    with ZipFile(zip_path) as z:
        for subswath in ("IW1", "IW2", "IW3"):
            anns = [
                n
                for n in z.namelist()
                if "/annotation/s1" in n
                and f"-{subswath.lower()}-" in n.lower()
                and f"-{polarization.lower()}-" in n.lower()
                and n.endswith(".xml")
            ]
            if not anns:
                continue
            root = ET.fromstring(z.read(anns[0]))
            lines_per_burst = int(root.findtext(".//swathTiming/linesPerBurst"))
            burst_count = int(root.find(".//swathTiming/burstList").attrib["count"])
            points: list[tuple[int, float, float]] = []
            for gp in root.findall(".//geolocationGridPoint"):
                points.append(
                    (
                        int(gp.findtext("line")),
                        float(gp.findtext("longitude")),
                        float(gp.findtext("latitude")),
                    )
                )
            hits: list[int] = []
            for burst in range(1, burst_count + 1):
                lo = (burst - 1) * lines_per_burst
                hi = burst * lines_per_burst - 1
                vals = [(lon, lat) for line, lon, lat in points if lo <= line <= hi]
                if not vals:
                    continue
                lons = [v[0] for v in vals]
                lats = [v[1] for v in vals]
                burst_bounds = (min(lons), min(lats), max(lons), max(lats))
                if intersects(burst_bounds, region_bounds):
                    hits.append(burst)
            if hits:
                out[subswath] = hits
    return out


def choose_region_bursts(master: Path, slave: Path, *, region: str, polarization: str) -> tuple[str, int, int]:
    master_hits = burst_windows(master, region=region, polarization=polarization)
    slave_hits = burst_windows(slave, region=region, polarization=polarization)
    candidates: list[tuple[int, str, int, int]] = []
    for subswath in ("IW1", "IW2", "IW3"):
        common = sorted(set(master_hits.get(subswath, [])) & set(slave_hits.get(subswath, [])))
        if not common:
            continue
        candidates.append((len(common), subswath, min(common), max(common)))
    if not candidates:
        raise SystemExit(f"Не удалось подобрать burst-окно для region={region}")
    _, subswath, first_burst, last_burst = min(candidates, key=lambda x: (x[0], x[1]))
    return subswath, first_burst, last_burst

print(f"OK pairs to run: {len(rows)}")
print(f"SLC dir: {slc_dir}")
print(f"Out dir: {out_dir}")
print(f"Region: {region_default}")
print(f"Pair order: {os.environ.get('PAIR_ORDER', 'quality')}")
print()

for pos, row in enumerate(rows, start=start_i):
    master = resolve_slc(row["master_id"])
    slave = resolve_slc(row["slave_id"])
    eap = (row.get("eap_correction") or "none").strip() or "none"
    region = (row.get("region") or region_default).strip() or region_default
    row_subswath = (row.get("subswath") or subswath).strip() or subswath
    row_first_burst = str(row.get("first_burst") or first_burst)
    row_last_burst = str(row.get("last_burst") or last_burst)
    if row_first_burst == "0" and row_last_burst == "0":
        picked_subswath, picked_first, picked_last = choose_region_bursts(
            master,
            slave,
            region=region,
            polarization=polarization,
        )
        row_subswath = picked_subswath
        row_first_burst = str(picked_first)
        row_last_burst = str(picked_last)
    cmd = [
        sys.executable,
        "-m",
        "dem.insar.pipeline",
        "run-pair",
        "--master",
        str(master),
        "--slave",
        str(slave),
        "--region",
        region,
        "--subswath",
        row_subswath,
        "--polarization",
        polarization,
        "--first-burst",
        row_first_burst,
        "--last-burst",
        row_last_burst,
        "--eap-correction",
        eap,
        "--gpt-cache",
        gpt_cache,
        "--gpt-threads",
        gpt_threads,
        "--out-dir",
        str(out_dir),
    ]
    print("=" * 100)
    print(
        f"[{pos}] baseline={row.get('baseline_m')} m, dt={row.get('dt_days')} days, "
        f"region={region}, subswath={row_subswath}, bursts={row_first_burst}..{row_last_burst}, eap={eap}"
    )
    print(" ".join(shlex.quote(x) for x in cmd))
    if dry:
        continue
    rc = subprocess.call(cmd, env={**os.environ, "COPYFILE_DISABLE": "1"})
    if rc != 0:
        raise SystemExit(rc)

print()
print("Пакетный прогон завершён.")
PY
