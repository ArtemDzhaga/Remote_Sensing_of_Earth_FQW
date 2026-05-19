# -*- coding: utf-8 -*-
"""
SLC Sentinel-1 через ASF: поиск сцен (`asf_slc`) и CLI загрузки (`sar_slc_download`).
"""

from __future__ import annotations

from dem.ingest.asf_slc import SlcScene, build_slc_pairs, fetch_slc_scenes  # noqa: F401
from dem.ingest import sar_slc_download as _download


def main() -> None:
    _download.main()


if __name__ == "__main__":
    main()
