from __future__ import annotations

from dem.ml import pipeline as ml_pipeline
from dem.ml import ready as ml_ready


def test_ml_pipeline_build_parser() -> None:
    parser = ml_pipeline.build_parser()
    assert parser.prog


def test_ml_ready_build_parser() -> None:
    parser = ml_ready.build_parser()
    assert parser.prog
