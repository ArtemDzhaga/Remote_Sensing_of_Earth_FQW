# -*- coding: utf-8 -*-
"""Smoke: импорт пакета и CLI без падений."""

from __future__ import annotations


def test_import_dem() -> None:
    import dem  # noqa: F401

    import dem.cli  # noqa: F401
    import dem.ingest.sar_rtc_stac  # noqa: F401
    import dem.insar.pipeline  # noqa: F401


def test_cli_help_exit_code() -> None:
    from dem.cli import dispatch

    assert dispatch(["--help"]) == 0
