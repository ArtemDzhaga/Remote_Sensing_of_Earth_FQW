# -*- coding: utf-8 -*-
from __future__ import annotations

import numpy as np
import rasterio
from affine import Affine
from rasterio.transform import from_origin

from dem.features.slope import slope_aspect_from_array
from dem.features.stack import write_npz_patches
from dem.features.tiling import extract_patches, iter_windows


def _write_tif(path, arr: np.ndarray) -> None:
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


def test_iter_windows_covers_edges() -> None:
    wins = list(iter_windows(300, 300, patch_size=128, overlap=32))

    assert wins[0].row == 0
    assert wins[0].col == 0
    assert max(w.row for w in wins) == 300 - 128
    assert max(w.col for w in wins) == 300 - 128


def test_extract_patches_filters_invalid_values() -> None:
    arr = np.ones((1, 128, 256), dtype="float32")
    arr[:, :, 128:] = np.nan

    patches = extract_patches(arr, patch_size=128, overlap=0, min_valid_fraction=0.8)

    assert len(patches) == 1
    win, patch = patches[0]
    assert (win.row, win.col) == (0, 0)
    assert patch.shape == (1, 128, 128)


def test_slope_for_flat_dem_is_zero() -> None:
    dem = np.ones((16, 16), dtype="float32") * 100.0
    slope, aspect = slope_aspect_from_array(dem, Affine.translation(0, 0) * Affine.scale(10, -10))

    assert np.nanmax(slope) == 0.0
    assert aspect.shape == dem.shape


def test_stack_residual_target(tmp_path) -> None:
    baseline = np.ones((128, 128), dtype="float32") * 10.0
    target = baseline + 3.0
    base_path = tmp_path / "baseline.tif"
    target_path = tmp_path / "target.tif"
    _write_tif(base_path, baseline)
    _write_tif(target_path, target)

    out_dir = write_npz_patches(
        channels=[base_path],
        target=target_path,
        out_dir=tmp_path / "dataset",
        patch_size=64,
        overlap=0,
        target_mode="residual",
        base_channel_index=0,
    )

    first = sorted(out_dir.glob("*.npz"))[0]
    with np.load(first) as z:
        assert np.allclose(z["y"], 3.0)
