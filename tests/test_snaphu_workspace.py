# -*- coding: utf-8 -*-
"""Рабочее место SNAPHU перед новым прогоном."""

from __future__ import annotations

from pathlib import Path

from dem.insar.snaphu import reset_snaphu_workspace


def test_reset_snaphu_workspace_removes_tiles_and_empty_unw(tmp_path: Path) -> None:
    tiles = tmp_path / "snaphu_tiles_99999"
    tiles.mkdir()
    (tiles / "dummy").write_bytes(b"x")
    unw = tmp_path / "UnwPhase_test.snaphu.img"
    unw.write_bytes(b"")
    keep = tmp_path / "Phase_test.snaphu.img"
    keep.write_bytes(b"phase")

    reset_snaphu_workspace(tmp_path)

    assert not tiles.exists()
    assert not unw.exists()
    assert keep.exists()

