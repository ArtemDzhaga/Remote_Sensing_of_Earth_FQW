# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from dem.viz.compare_dems import compare_dems


def _write_tif(path: Path, arr: np.ndarray) -> None:
    profile = {
        "driver": "GTiff",
        "height": arr.shape[0],
        "width": arr.shape[1],
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:3857",
        "transform": from_origin(0, 100, 10, 10),
        "nodata": np.nan,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr.astype("float32"), 1)


def test_compare_dems_writes_metrics(tmp_path: Path) -> None:
    ref = np.ones((32, 32), dtype="float32") * 100.0
    cand = ref + 5.0
    ref_path = tmp_path / "ref.tif"
    cand_path = tmp_path / "cand.tif"
    _write_tif(ref_path, ref)
    _write_tif(cand_path, cand)

    report = compare_dems(
        reference=ref_path,
        candidates=[("baseline", cand_path)],
        out_dir=tmp_path / "report",
        psnr_range=1000.0,
    )

    assert report.is_file()
    metrics = json.loads((tmp_path / "report" / "dem_comparison_metrics.json").read_text(encoding="utf-8"))
    row = metrics["rows"][0]
    assert row["name"] == "baseline"
    assert row["all"]["mae"] == 5.0
    assert row["all"]["rmse"] == 5.0
