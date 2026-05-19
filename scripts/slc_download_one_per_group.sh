#!/usr/bin/env bash
set -euo pipefail

# Download one SLC scene per subgroup (path/frame/dir/pol/beam)
# Defaults can be overridden via env vars.
REGION="${REGION:-sochi_khosta_mzymta_small}"
DATE_FROM="${DATE_FROM:-2010-01-01}"
DATE_TO="${DATE_TO:-2026-03-31}"
MAX_RESULTS="${MAX_RESULTS:-20000}"
AUTH_MODE="${AUTH_MODE:-auto}"  # auto|environment|netrc|interactive|basic

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
export ROOT_DIR

PYTHON="${PYTHON:-python}"

"$PYTHON" - <<'PY'
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

root = os.environ.get("ROOT_DIR", "")
if not root:
    root = os.getcwd()
sys.path.insert(0, os.path.join(root, "src"))

from dem.ingest.asf_slc import fetch_slc_scenes
from dem.config import REGIONS
from dem.ingest.sar_slc_download import (
    _download_file,
    _download_via_earthaccess,
    _earthaccess_strategy,
    _make_session,
    _slug,
)
from dem.io.layout import resolve_out_dir, slc_runs_dir

region = os.environ.get("REGION", "sochi_khosta_mzymta_small")
date_from = os.environ.get("DATE_FROM", "2010-01-01")
date_to = os.environ.get("DATE_TO", "2026-03-31")
max_results = int(os.environ.get("MAX_RESULTS", "20000"))
auth_mode = os.environ.get("AUTH_MODE", "auto")

scenes = fetch_slc_scenes(
    region=REGIONS[region],
    date_from=date_from,
    date_to=date_to,
    max_results=max_results,
)
if not scenes:
    print("No SLC scenes found.")
    sys.exit(0)

groups = defaultdict(list)
for s in scenes:
    key = (s.path_number, s.frame_number, s.flight_direction, s.polarization, s.beam_mode)
    groups[key].append(s)

# pick earliest scene per group
sample = []
for key, arr in groups.items():
    arr.sort(key=lambda x: x.start_time)
    sample.append(arr[0])

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
out_base = resolve_out_dir("", slc_runs_dir)
run_dir = out_base / f"slc_sample_{region}_{date_from}_{date_to}_{stamp}"
run_dir.mkdir(parents=True, exist_ok=True)

manifest = {
    "region": region,
    "date_from": date_from,
    "date_to": date_to,
    "max_results": max_results,
    "auth_mode": auth_mode,
    "run_dir": run_dir.as_posix(),
    "groups": len(groups),
    "sample_scenes": [s.__dict__ for s in sample],
}
(run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

if auth_mode != "basic" and auth_mode == "environment" and not os.environ.get("EARTHDATA_TOKEN", "").strip():
    print("AUTH_MODE=environment requires EARTHDATA_TOKEN or Earthdata username/password variables.", file=sys.stderr)

session = _make_session(auth_mode) if auth_mode == "basic" else None
if auth_mode != "basic":
    try:
        import earthaccess
        earthaccess.login(strategy=_earthaccess_strategy(auth_mode))
    except Exception as e:
        print(f"earthaccess login failed ({e}); will try HTTP fallback.", file=sys.stderr)
        session = _make_session("auto")

total = len(sample)
for i, s in enumerate(sample, start=1):
    name = _slug(s.file_id) + ".zip"
    dest = run_dir / name
    print(f"[{i}/{total}] {s.file_id}")
    print(f"  -> {dest}")
    if auth_mode != "basic":
        try:
            _download_via_earthaccess(s.download_url, dest)
        except Exception as e:
            print(f"  earthaccess: {e}\n  fallback HTTP...", file=sys.stderr)
            fb = _make_session("auto")
            _download_file(fb, s.download_url, dest)
    else:
        _download_file(session, s.download_url, dest)

print(f"Done: {run_dir}")
PY
