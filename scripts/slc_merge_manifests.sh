#!/usr/bin/env bash
set -euo pipefail

# Склеить SLC-манифесты в один рабочий manifest 2014-2026.
# По умолчанию объединяет:
# - slc_yearly_2014_2026_10_per_year_manifest.json
# - slc_yearly_2019_2026_10_per_year_manifest.json
# и пишет slc_yearly_2014_2026_unified_manifest.json.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT_DIR"

source "${SCRIPT_DIR}/insar_env.sh"

PYTHON="${PYTHON:-python}"
INPUTS="${INPUTS:-${VKR_MANIFEST_BASE}:${VKR_MANIFEST_EXTRA}}"
OUT="${OUT:-$VKR_MANIFEST_UNIFIED}"

"$PYTHON" - "$INPUTS" "$OUT" <<'PY'
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

inputs = [Path(p) for p in sys.argv[1].split(":") if p.strip()]
out = Path(sys.argv[2])

docs = []
for path in inputs:
    if not path.is_file():
        raise SystemExit(f"Manifest not found: {path}")
    docs.append(json.loads(path.read_text(encoding="utf-8")))

if not docs:
    raise SystemExit("No manifests to merge.")

region = docs[0].get("region", "sochi_khosta_mzymta_small")
selection = docs[0].get("selection", {})

scenes_by_id = {}
for doc in docs:
    for scene in doc.get("scenes", []):
        sid = scene.get("file_id")
        if not sid:
            continue
        old = scenes_by_id.get(sid)
        if old is None:
            scenes_by_id[sid] = scene
            continue
        old_size = float(old.get("size_mb") or 0.0)
        new_size = float(scene.get("size_mb") or 0.0)
        if new_size > old_size:
            scenes_by_id[sid] = scene

pairs_by_key = {}
for doc in docs:
    for pair in doc.get("pairs", []):
        master = pair.get("master_id")
        slave = pair.get("slave_id")
        if not master or not slave:
            continue
        key = (master, slave)
        old = pairs_by_key.get(key)
        if old is None:
            pairs_by_key[key] = pair
            continue
        old_score = float(old.get("pair_score") or math.inf)
        new_score = float(pair.get("pair_score") or math.inf)
        if new_score < old_score:
            pairs_by_key[key] = pair

scenes = sorted(scenes_by_id.values(), key=lambda x: (x.get("start_time") or "", x.get("file_id") or ""))
pairs = sorted(
    pairs_by_key.values(),
    key=lambda x: (
        x.get("master_time") or "",
        x.get("slave_time") or "",
        x.get("master_id") or "",
        x.get("slave_id") or "",
    ),
)

years = defaultdict(lambda: {"year": 0, "selected_pair_count": 0, "selected_scene_count": 0})
for pair in pairs:
    year = int(str(pair.get("master_time") or "0000")[:4])
    years[year]["year"] = year
    years[year]["selected_pair_count"] += 1
for scene in scenes:
    year = int(str(scene.get("start_time") or "0000")[:4])
    years[year]["year"] = year
    years[year]["selected_scene_count"] += 1

estimated_bytes = 0
for scene in scenes:
    size_mb = scene.get("size_mb")
    if size_mb is not None:
        estimated_bytes += int(float(size_mb) * 1024 * 1024)

merged = {
    "region": region,
    "strategy": "yearly_merged",
    "date_from": "2014-04-01",
    "date_to": "2026-05-01",
    "requested_date_from": "2014-04-01",
    "requested_date_to": "2026-05-01",
    "budget_gb": None,
    "selection": selection,
    "estimated_download_bytes": estimated_bytes,
    "estimated_download_gib": round(estimated_bytes / 1024**3, 3),
    "pair_count": len(pairs),
    "unique_scene_count": len(scenes),
    "warnings": [
        "Merged manifest. Bperp values are still validated by SNAP baseline_preflight, not trusted from ASF."
    ],
    "yearly_summary": [years[y] for y in sorted(years) if y > 0],
    "pairs": pairs,
    "scenes": scenes,
    "merged_from": [str(p) for p in inputs],
}

out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"Wrote: {out}")
print(f"Pairs: {len(pairs)}")
print(f"Unique scenes: {len(scenes)}")
print(f"Estimated unique SLC size: {merged['estimated_download_gib']} GiB")
PY
