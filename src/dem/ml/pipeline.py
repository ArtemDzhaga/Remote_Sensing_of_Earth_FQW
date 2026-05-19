# -*- coding: utf-8 -*-
"""Совместимый CLI-алиас для ML training pipeline."""

from __future__ import annotations

from dem.ml.train import build_parser, main, train

__all__ = ["build_parser", "main", "train"]
