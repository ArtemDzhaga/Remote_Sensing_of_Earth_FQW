from __future__ import annotations

from collections import Counter

from dem.ingest.asf_slc import SlcScene
from dem.ingest.slc_budget_plan import apply_scene_budget_to_pairs, select_yearly_scenes_from_pairs


def _scene(year: int, month: int, day: int, idx: int) -> SlcScene:
    scene_id = f"S1A_TEST_{year}_{idx:03d}"
    return SlcScene(
        file_id=scene_id,
        start_time=f"{year}-{month:02d}-{day:02d}T03:00:00Z",
        stop_time=f"{year}-{month:02d}-{day:02d}T03:10:00Z",
        platform="Sentinel-1A",
        flight_direction="ASCENDING",
        path_number=42,
        frame_number=101,
        polarization="VV+VH",
        beam_mode="IW",
        download_url=f"https://example.invalid/{scene_id}.zip",
        size_mb=100.0,
    )


def _year_scenes(year: int) -> list[SlcScene]:
    dates = [
        (1, 1),
        (1, 13),
        (1, 25),
        (2, 6),
        (2, 18),
        (3, 1),
        (3, 13),
        (3, 25),
        (4, 6),
        (4, 18),
        (4, 30),
        (5, 12),
    ]
    return [_scene(year, month, day, i) for i, (month, day) in enumerate(dates, start=1)]


def test_select_yearly_scenes_from_pairs_caps_unique_scenes_per_year() -> None:
    scenes = _year_scenes(2014) + _year_scenes(2015)

    pairs, total_b, selected_scenes, summary = select_yearly_scenes_from_pairs(
        scenes,
        year_from=2014,
        year_to=2015,
        scenes_per_year=10,
        pairs_per_year=30,
        min_days=6,
        max_days=36,
        default_size_mb=100.0,
    )

    assert pairs
    assert len(selected_scenes) <= 20
    assert total_b == len(selected_scenes) * 100 * 1024 * 1024
    by_year = Counter(int(s.start_time[:4]) for s in selected_scenes)
    assert by_year[2014] <= 10
    assert by_year[2015] <= 10
    assert {row["year"] for row in summary} == {2014, 2015}
    assert all(row["selected_scene_count"] <= 10 for row in summary)
    assert all(row["selected_pair_count"] > 0 for row in summary)


def test_apply_scene_budget_to_pairs_limits_unique_download_size() -> None:
    scenes = _year_scenes(2014)
    pairs, _, selected_scenes, _ = select_yearly_scenes_from_pairs(
        scenes,
        year_from=2014,
        year_to=2014,
        scenes_per_year=10,
        pairs_per_year=30,
        min_days=6,
        max_days=36,
        default_size_mb=100.0,
    )

    limited_pairs, total_b, limited_scenes = apply_scene_budget_to_pairs(
        pairs,
        selected_scenes,
        budget_gb=0.35,
        default_size_mb=100.0,
    )

    assert limited_pairs
    assert len(limited_scenes) <= 3
    assert total_b <= int(0.35 * (1024**3))
