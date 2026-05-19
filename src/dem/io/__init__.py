# -*- coding: utf-8 -*-
"""Пути вывода (outputs/YYYY-MM-DD, legacy data/)."""

from dem.io.layout import (
    data_processed,
    data_raw,
    demo_runs_dir,
    insar_dir,
    iter_reference_dem_processed_bases_newest_first,
    iter_sar_run_roots_newest_first,
    outputs_root,
    progress_report_dir,
    quality_report_dir,
    reference_dem_processed_base,
    reference_dem_raw_base,
    resolve_out_dir,
    run_date_str,
    slc_runs_dir,
)
from dem.io.storage import LocalFSStorage, ObjectStorageStub, StorageBackend

__all__ = [
    "LocalFSStorage",
    "ObjectStorageStub",
    "StorageBackend",
    "data_processed",
    "data_raw",
    "demo_runs_dir",
    "insar_dir",
    "iter_reference_dem_processed_bases_newest_first",
    "iter_sar_run_roots_newest_first",
    "outputs_root",
    "progress_report_dir",
    "quality_report_dir",
    "reference_dem_processed_base",
    "reference_dem_raw_base",
    "resolve_out_dir",
    "run_date_str",
    "slc_runs_dir",
]
