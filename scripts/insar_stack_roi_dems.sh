#!/usr/bin/env bash
set -euo pipefail

# Собрать несколько ROI InSAR DEM в один стек на сетке COP30:
# - reproject каждого dem_insar.tif к reference DEM;
# - mean-stack и median-stack;
# - метрики mean/median против COP30.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT_DIR"

source "${SCRIPT_DIR}/insar_env.sh"

PYTHON="${PYTHON:-python}"
PAIR_ROOT="${PAIR_ROOT:-$VKR_FULL_PAIRS_DIR}"
OUT_DIR="${OUT_DIR:-$VKR_STACK_DIR}"
DEM_GLOB="${DEM_GLOB:-*/dem_insar.tif}"
PRODUCT_PREFIX="${PRODUCT_PREFIX:-insar_stack}"
MIN_PIXELS="${MIN_PIXELS:-50000}"
MAX_RMSE="${MAX_RMSE:-500}"

if [[ -z "${REGION:-}" ]]; then
  REGION="$("$PYTHON" - <<'PY'
from dem.config import DEFAULT_REGION
print(DEFAULT_REGION)
PY
)"
fi

"$PYTHON" - "$PAIR_ROOT" "$OUT_DIR" "$REGION" "$MIN_PIXELS" "$MAX_RMSE" "$DEM_GLOB" "$PRODUCT_PREFIX" <<'PY'
import json
import os
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject

from dem.io.layout import iter_reference_dem_processed_bases_newest_first

pair_root = Path(sys.argv[1])
out_dir = Path(sys.argv[2])
region = sys.argv[3]
min_pixels = int(float(sys.argv[4]))
max_rmse = float(sys.argv[5])
dem_glob = sys.argv[6]
product_prefix = sys.argv[7]
out_dir.mkdir(parents=True, exist_ok=True)

dems = sorted(pair_root.glob(dem_glob))
if not dems:
    raise SystemExit(f"No DEM found in {pair_root} by glob={dem_glob!r}")

refs = []
for base in iter_reference_dem_processed_bases_newest_first():
    root = base / region
    if root.is_dir():
        refs.extend(p for p in root.rglob("*cop30*.tif") if p.is_file())
if not refs:
    raise SystemExit(f"No COP30 reference DEM found for region={region}")
reference = sorted(refs, key=lambda p: p.stat().st_mtime, reverse=True)[0]

with rasterio.open(reference) as ref:
    ref_arr = ref.read(1, masked=True).filled(np.nan).astype("float32")
    ref_profile = ref.profile.copy()
    ref_meta = {
        "crs": ref.crs,
        "transform": ref.transform,
        "width": ref.width,
        "height": ref.height,
        "nodata": ref.nodata,
    }

stack = []
members = []
excluded = []

def metrics(candidate: np.ndarray) -> dict[str, float]:
    valid = np.isfinite(candidate) & np.isfinite(ref_arr)
    if not valid.any():
        return {"pixels": 0, "mae": float("nan"), "rmse": float("nan"), "bias": float("nan")}
    err = candidate[valid] - ref_arr[valid]
    return {
        "pixels": int(valid.sum()),
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(np.sqrt(np.mean(err**2))),
        "bias": float(np.mean(err)),
    }

for dem in dems:
    with rasterio.open(dem) as src:
        dst = np.full((ref_meta["height"], ref_meta["width"]), np.nan, dtype="float32")
        reproject(
            source=src.read(1, masked=True).filled(np.nan).astype("float32"),
            destination=dst,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=src.nodata,
            dst_transform=ref_meta["transform"],
            dst_crs=ref_meta["crs"],
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )
    row = metrics(dst)
    row["path"] = str(dem)
    row["pair"] = dem.parent.name
    if row["pixels"] < min_pixels:
        row["reason"] = f"pixels<{min_pixels}"
        excluded.append(row)
        continue
    if not np.isfinite(row["rmse"]) or row["rmse"] > max_rmse:
        row["reason"] = f"rmse>{max_rmse:g}"
        excluded.append(row)
        continue
    stack.append(dst)
    members.append(row)

if not stack:
    raise SystemExit(f"No DEM passed filters: min_pixels={min_pixels}, max_rmse={max_rmse}")

arr = np.stack(stack)
products = {
    "mean": np.nanmean(arr, axis=0).astype("float32"),
    "median": np.nanmedian(arr, axis=0).astype("float32"),
}

profile = ref_profile.copy()
profile.update(dtype="float32", count=1, nodata=np.nan, compress="lzw")

rows = []
for name, candidate in products.items():
    out_tif = out_dir / f"{product_prefix}_{name}.tif"
    with rasterio.open(out_tif, "w", **profile) as dst:
        dst.write(candidate, 1)
    rows.append({"name": name, "path": str(out_tif), **metrics(candidate)})

report = {
    "region": region,
    "reference": str(reference),
    "dem_glob": dem_glob,
    "product_prefix": product_prefix,
    "members": members,
    "excluded": excluded,
    "filters": {"min_pixels": min_pixels, "max_rmse": max_rmse},
    "rows": rows,
}
(out_dir / "insar_stack_metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

lines = [
    "# InSAR ROI Stack Metrics",
    "",
    f"- region: `{region}`",
    f"- reference: `{reference}`",
    f"- dem_glob: `{dem_glob}`",
    f"- members: `{len(members)}`",
    f"- excluded: `{len(excluded)}`",
    f"- filters: `pixels >= {min_pixels}`, `RMSE <= {max_rmse:g}`",
    "",
    "| product | pixels | MAE | RMSE | bias | path |",
    "|---|---:|---:|---:|---:|---|",
]
for row in rows:
    lines.append(
        f"| {row['name']} | {row['pixels']} | {row['mae']:.3f} | {row['rmse']:.3f} | "
        f"{row['bias']:.3f} | `{row['path']}` |"
    )
lines.extend(["", "## Included DEMs", "", "| pair | pixels | MAE | RMSE | bias |", "|---|---:|---:|---:|---:|"])
for row in sorted(members, key=lambda x: x["rmse"]):
    lines.append(f"| {row['pair']} | {row['pixels']} | {row['mae']:.3f} | {row['rmse']:.3f} | {row['bias']:.3f} |")
lines.extend(["", "## Excluded DEMs", "", "| pair | reason | pixels | MAE | RMSE | bias |", "|---|---|---:|---:|---:|---:|"])
for row in sorted(excluded, key=lambda x: (x.get("reason", ""), x.get("rmse", 0))):
    lines.append(
        f"| {row['pair']} | {row.get('reason', '')} | {row['pixels']} | {row['mae']:.3f} | "
        f"{row['rmse']:.3f} | {row['bias']:.3f} |"
    )
(out_dir / "insar_stack_metrics.md").write_text("\n".join(lines), encoding="utf-8")

print(f"reference: {reference}")
print(f"members:   {len(members)}")
print(f"excluded:  {len(excluded)}")
print(f"report:    {out_dir / 'insar_stack_metrics.md'}")
for row in rows:
    print(f"{row['name']}: MAE={row['mae']:.3f} RMSE={row['rmse']:.3f} bias={row['bias']:.3f}")
PY
