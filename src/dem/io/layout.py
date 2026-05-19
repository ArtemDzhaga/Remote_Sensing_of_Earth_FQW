# -*- coding: utf-8 -*-
"""
Единая схема выходных данных.

По умолчанию всё пишется локально в ``outputs/YYYY-MM-DD/``.
Для тяжёлых InSAR-прогонов можно перенести корень на внешний SSD через
``VKR_DATA_ROOT``. Конкретный локальный путь не зашивается в код и задаётся
переменными окружения.

Переопределение даты (тесты, воспроизводимость): переменная окружения
``VKR_RUN_DATE=2025-03-25``.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path


DATA_ROOT_ENV = "VKR_DATA_ROOT"
PROJECT_ROOT = Path(__file__).resolve().parents[3]

EXTERNAL_SSD_ROOT_STUB = PROJECT_ROOT / ".local_data"


def run_date_str() -> str:
    return os.environ.get("VKR_RUN_DATE", date.today().isoformat())


def data_root() -> Path:
    """Корень рабочих артефактов: корень проекта или путь из ``VKR_DATA_ROOT``."""

    root = os.environ.get(DATA_ROOT_ENV, "").strip()
    if root:
        p = Path(root).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return p
    return PROJECT_ROOT


def outputs_root() -> Path:
    p = data_root() / "outputs" / run_date_str()
    p.mkdir(parents=True, exist_ok=True)
    return p


def data_raw() -> Path:
    p = outputs_root() / "data" / "raw"
    p.mkdir(parents=True, exist_ok=True)
    return p


def data_processed() -> Path:
    p = outputs_root() / "data" / "processed"
    p.mkdir(parents=True, exist_ok=True)
    return p


def quality_report_dir() -> Path:
    p = outputs_root() / "quality_report"
    p.mkdir(parents=True, exist_ok=True)
    return p


def progress_report_dir() -> Path:
    p = outputs_root() / "progress_report"
    p.mkdir(parents=True, exist_ok=True)
    return p


def demo_runs_dir() -> Path:
    p = outputs_root() / "demo_runs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def insar_dir() -> Path:
    p = outputs_root() / "insar"
    p.mkdir(parents=True, exist_ok=True)
    return p


def reference_dem_raw_base() -> Path:
    p = data_raw() / "reference_dem"
    p.mkdir(parents=True, exist_ok=True)
    return p


def reference_dem_processed_base() -> Path:
    p = data_processed() / "reference_dem"
    p.mkdir(parents=True, exist_ok=True)
    return p


def slc_runs_dir() -> Path:
    p = data_raw() / "slc_runs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def iter_reference_dem_processed_bases_newest_first() -> list[Path]:
    """Поиск эталонных DEM: сначала свежие дни в outputs/, затем старый путь data/processed."""
    out: list[Path] = []
    root = data_root() / "outputs"
    if root.is_dir():
        days = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True)
        for d in days:
            cand = d / "data" / "processed" / "reference_dem"
            if cand.is_dir():
                out.append(cand)
    legacy = Path("data/processed/reference_dem")
    if legacy.is_dir():
        out.append(legacy)
    return out


def iter_sar_run_roots_newest_first() -> list[Path]:
    out: list[Path] = []
    root = data_root() / "outputs"
    if root.is_dir():
        days = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True)
        for d in days:
            cand = d / "data" / "raw" / "runs"
            if cand.is_dir():
                out.append(cand)
    legacy = Path("data/raw/runs")
    if legacy.is_dir():
        out.append(legacy)
    return out


def resolve_out_dir(cli_value: str, default_factory) -> Path:
    """Если cli_value пустой — default_factory()."""
    s = (cli_value or "").strip()
    if s:
        return Path(s)
    return default_factory()
