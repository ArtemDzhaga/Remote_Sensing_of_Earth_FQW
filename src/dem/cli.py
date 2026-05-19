# -*- coding: utf-8 -*-
"""
Единый CLI: ``python -m dem <цепочка> ...`` проксирует в ``python -m dem.<модуль> ...``.

Примеры:
  python -m dem ingest sar download --region sochi_khosta_mzymta_small --month 2024-06 --limit 1
  python -m dem insar pipeline doctor
  python -m dem viz validate-dem path/to.tif

Полный список модулей см. docs/handbook.md.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Iterable


def _run_module(mod: str, args: Iterable[str]) -> int:
    cmd = [sys.executable, "-m", mod, *list(args)]
    return subprocess.call(cmd)


def dispatch(argv: list[str]) -> int:
    """Разбор цепочки после ``python -m dem``."""

    if not argv or argv[0] in ("-h", "--help", "help"):
        print(
            """dem — единый CLI (прокси).

Примеры:
  python -m dem ingest sar download --region sochi_khosta_mzymta_small --month 2024-06 --limit 1
  python -m dem ingest sar list --region sochi_khosta_mzymta_small --month 2024-06 --max-scenes 5
  python -m dem ingest service stac download --region sochi_khosta_mzymta_small --month 2024-06 --limit 1
  python -m dem ingest reference-dem --region sochi_khosta_mzymta_small
  python -m dem ingest optical download --region sochi_khosta_mzymta_wide --satellite sentinel2 --month 2025-09 --limit 1
  python -m dem viz validate-dem path/to/dem.tif
  python -m dem viz compare-dems --reference cop30.tif --candidate baseline=insar.tif
  python -m dem viz demo progress --region sochi_khosta_mzymta_small --month 2024-06
  python -m dem features slope path/to/dem.tif
  python -m dem features stack --channel insar.tif --channel slope.tif --target cop30.tif
  python -m dem ml train --data-dir outputs/<дата>/data/processed/dataset_v1 --epochs 20
  python -m dem ml infer --checkpoint best.pt --channel insar.tif --out-tif corrected.tif
  python -m dem insar pipeline doctor
  python -m dem insar pipeline run-pair --master M.zip --slave S.zip --subswath IW2 --polarization VV
  python -m dem insar pipeline run-batch --pairs pairs.json --limit 5
  python -m dem insar pair-search --region sochi_khosta_mzymta_small --date-from 2024-06-01 --date-to 2024-08-31

Справка по модулям: docs/handbook.md
"""
        )
        return 0

    # --- longest-prefix маршруты: ключ = первые N токенов через пробел ---
    raw = argv[:]
    for n in range(min(6, len(raw)), 0, -1):
        head = " ".join(raw[:n])
        rest = raw[n:]

        if head == "ingest sar download":
            return _run_module("dem.ingest.sar_rtc_stac", ["download", *rest])
        if head == "ingest sar list":
            return _run_module("dem.ingest.sar_rtc_stac", ["list", *rest])
        if head == "ingest reference-dem":
            return _run_module("dem.ingest.reference_dem", rest)
        if head == "ingest opentopography":
            return _run_module("dem.ingest.dem_opentopography", rest)
        if head == "ingest optical":
            return _run_module("dem.ingest.optical_stac", rest)
        if head == "ingest slc":
            return _run_module("dem.ingest.sar_slc_asf", rest)
        if head == "ingest service":
            return _run_module("dem.ingest.service", rest)
        if head == "viz validate-dem":
            return _run_module("dem.viz.validate_dem", rest)
        if head == "viz compare-dems":
            return _run_module("dem.viz.compare_dems", rest)
        if head == "viz progress":
            return _run_module("dem.viz.progress", rest)
        if head == "viz demo":
            return _run_module("dem.viz.demo", rest)
        if head == "viz demo-progress":
            return _run_module("dem.viz.demo_progress", rest)
        if head == "viz fetch-rtc":
            return _run_module("dem.viz.fetch_rtc_bundle", rest)
        if head == "features slope":
            return _run_module("dem.features.slope", rest)
        if head == "features stack":
            return _run_module("dem.features.stack", rest)
        if head == "ml train":
            return _run_module("dem.ml.train", rest)
        if head == "ml prepare-insar-dataset":
            return _run_module("dem.ml.prepare_insar_dataset", rest)
        if head == "ml infer":
            return _run_module("dem.ml.infer", rest)
        if head == "ml evaluate":
            return _run_module("dem.ml.evaluate", rest)
        if head == "insar pipeline":
            return _run_module("dem.insar.pipeline", rest)
        if head == "insar coherence-preview":
            return _run_module("dem.insar.coherence_preview", rest)
        if head == "insar pair-search":
            return _run_module("dem.insar.pair_search", rest)

    print(f"Неизвестная команда: {' '.join(raw)}. См. python -m dem --help", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    raise SystemExit(dispatch(args))


if __name__ == "__main__":
    main()
