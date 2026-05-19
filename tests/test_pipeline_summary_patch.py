# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from dem.insar import pipeline as insar_pipeline


def test_patch_pair_summary_updates_unw_and_dem(tmp_path: Path) -> None:
    pair = tmp_path / "pair_a"
    pair.mkdir()
    summary = pair / "summary.md"
    summary.write_text(
        "\n".join(
            [
                "# InSAR pair: X",
                "",
                "- unwrapped (UnwPhase.hdr): `None`",
                "- dem_insar.tif: `None`",
                "- finished_utc: `old`",
            ]
        ),
        encoding="utf-8",
    )

    unw = pair / "snaphu_export" / "Unw.hdr"
    dem = pair / "dem_insar.tif"
    insar_pipeline._patch_pair_summary(pair, unw_hdr=unw)
    text = summary.read_text(encoding="utf-8")
    assert f"- unwrapped (UnwPhase.hdr): `{unw}`" in text

    insar_pipeline._patch_pair_summary(pair, dem_tif=dem)
    text = summary.read_text(encoding="utf-8")
    assert f"- dem_insar.tif: `{dem}`" in text
    assert "- finished_utc:" in text
    assert "`old`" not in text
