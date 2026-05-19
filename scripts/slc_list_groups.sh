#!/usr/bin/env bash
set -euo pipefail

# List SLC scene counts per subgroup (path/frame/dir/pol/beam)
# Default region and dates can be overridden via env vars.
REGION="${REGION:-sochi_khosta_mzymta_small}"
DATE_FROM="${DATE_FROM:-2010-01-01}"
DATE_TO="${DATE_TO:-2026-03-31}"
MAX_RESULTS="${MAX_RESULTS:-20000}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
export ROOT_DIR

PYTHON="${PYTHON:-python}"

"$PYTHON" - <<'PY'
import os
import sys
from collections import defaultdict

root = os.environ.get("ROOT_DIR", "")
if not root:
    root = os.getcwd()
sys.path.insert(0, os.path.join(root, "src"))

from dem.ingest.asf_slc import fetch_slc_scenes
from dem.config import REGIONS

region = os.environ.get("REGION", "sochi_khosta_mzymta_small")
date_from = os.environ.get("DATE_FROM", "2010-01-01")
date_to = os.environ.get("DATE_TO", "2026-03-31")
max_results = int(os.environ.get("MAX_RESULTS", "20000"))

scenes = fetch_slc_scenes(
    region=REGIONS[region],
    date_from=date_from,
    date_to=date_to,
    max_results=max_results,
)

groups = defaultdict(list)
for s in scenes:
    key = (s.path_number, s.frame_number, s.flight_direction, s.polarization, s.beam_mode)
    groups[key].append(s)

print(f"Region: {region}")
print(f"Period: {date_from} .. {date_to}")
print(f"Total scenes: {len(scenes)}")
print(f"Total groups: {len(groups)}")
print("")
print("Groups (path, frame, direction, pol, beam) -> scenes")
for key in sorted(groups.keys()):
    print(f"- {key} -> {len(groups[key])}")
PY
