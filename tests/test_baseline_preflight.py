from __future__ import annotations

from dem.insar.baseline_preflight import baseline_status, parse_snaphu_baseline


def test_parse_snaphu_baseline_reads_baseline_values(tmp_path) -> None:
    conf = tmp_path / "snaphu.conf"
    conf.write_text(
        "\n".join(
            [
                "BASELINE \t\t10.534",
                "BASELINEANGLE_RAD \t3.087",
            ]
        ),
        encoding="utf-8",
    )

    values = parse_snaphu_baseline(conf)

    assert values["baseline_m"] == 10.534
    assert values["baseline_angle_rad"] == 3.087


def test_baseline_status_uses_absolute_value() -> None:
    assert baseline_status(None, min_m=80.0, max_m=450.0) == "unknown"
    assert baseline_status(10.0, min_m=80.0, max_m=450.0) == "too_small"
    assert baseline_status(-120.0, min_m=80.0, max_m=450.0) == "ok"
    assert baseline_status(600.0, min_m=80.0, max_m=450.0) == "too_large"
