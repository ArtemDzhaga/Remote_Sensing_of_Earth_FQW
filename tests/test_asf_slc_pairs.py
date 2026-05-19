from __future__ import annotations

from dem.ingest.asf_slc import SlcScene, build_slc_pairs


def _scene(scene_id: str, day: int, bperp: float | None) -> SlcScene:
    return SlcScene(
        file_id=scene_id,
        start_time=f"2024-06-{day:02d}T03:00:00Z",
        stop_time=f"2024-06-{day:02d}T03:10:00Z",
        platform="Sentinel-1A",
        flight_direction="ASCENDING",
        path_number=42,
        frame_number=101,
        polarization="VV+VH",
        beam_mode="IW",
        download_url=f"https://example.invalid/{scene_id}.zip",
        perpendicular_baseline_m=bperp,
    )


def test_build_slc_pairs_ranks_dem_baseline_before_short_temporal_only_pair() -> None:
    scenes = [
        _scene("A", 1, 0.0),
        _scene("B_TOO_SMALL", 7, 10.0),
        _scene("C_OK", 13, 120.0),
        _scene("D_TOO_LARGE", 25, 600.0),
    ]

    pairs = build_slc_pairs(
        scenes,
        min_days=6,
        max_days=24,
        min_perpendicular_baseline_m=80.0,
        max_perpendicular_baseline_m=450.0,
        target_temporal_baseline_days=12.0,
    )

    assert pairs
    assert pairs[0]["master_id"] == "A"
    assert pairs[0]["slave_id"] == "C_OK"
    assert pairs[0]["perpendicular_baseline_m"] == 120.0
    assert pairs[0]["baseline_status"] == "ok"

    by_slave = {p["slave_id"]: p for p in pairs if p["master_id"] == "A"}
    assert by_slave["B_TOO_SMALL"]["baseline_status"] == "too_small"
    assert by_slave["D_TOO_LARGE"]["baseline_status"] == "too_large"


def test_build_slc_pairs_can_require_usable_perpendicular_baseline() -> None:
    scenes = [
        _scene("A", 1, 0.0),
        _scene("B_TOO_SMALL", 7, 10.0),
        _scene("C_OK", 13, 120.0),
        _scene("D_TOO_LARGE", 25, 600.0),
    ]

    pairs = build_slc_pairs(
        scenes,
        min_days=6,
        max_days=24,
        min_perpendicular_baseline_m=80.0,
        max_perpendicular_baseline_m=450.0,
        target_temporal_baseline_days=12.0,
        require_perpendicular_baseline=True,
    )

    assert pairs
    assert {p["baseline_status"] for p in pairs} == {"ok"}


def test_build_slc_pairs_marks_missing_perpendicular_baseline_as_unknown() -> None:
    pairs = build_slc_pairs(
        [_scene("A", 1, None), _scene("B", 13, None)],
        min_days=6,
        max_days=24,
        min_perpendicular_baseline_m=80.0,
        max_perpendicular_baseline_m=450.0,
    )

    assert len(pairs) == 1
    assert pairs[0]["perpendicular_baseline_m"] is None
    assert pairs[0]["baseline_status"] == "unknown"
