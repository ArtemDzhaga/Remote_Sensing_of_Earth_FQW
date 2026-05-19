# -*- coding: utf-8 -*-
"""
Один запуск для демонстрации: Sentinel-1 RTC + эталонный COP30 (Copernicus 30 m) по тому же региону.

Важно: COP30 — статический рельеф (не «снимок на дату SAR»). По времени привязываем только RTC;
DEM — обрезка по bbox региона из OpenTopography (demtype=COP30).

Нужно: OPENTOPOGRAPHY_API_KEY, активный venv, сеть.

Пример:
  export OPENTOPOGRAPHY_API_KEY=...
  python -m dem.viz.fetch_rtc_bundle \\
    --region sochi_khosta_mzymta_small --month 2024-06 --limit 1
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dem.config import DEFAULT_REGION, REGIONS  # noqa: E402
from dem.io.layout import demo_runs_dir, resolve_out_dir  # noqa: E402


def _run(cmd: list[str], *, env: dict) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0:
        raise RuntimeError(f"Ошибка ({p.returncode}): {' '.join(cmd)}\n{out}")
    return out


def _extract_done_folder(text: str) -> Path | None:
    for line in text.splitlines():
        if line.startswith("Готово:"):
            return Path(line.split(":", 1)[1].strip())
    return None


def _first_rtc_scene_dir(run_dir: Path) -> Path | None:
    scenes = sorted(run_dir.glob("scene_*"), key=lambda p: p.name)
    return scenes[0] if scenes else None


def main() -> None:
    p = argparse.ArgumentParser(description="RTC Copernicus Sentinel-1 + эталон COP30 для региона.")
    p.add_argument("--region", type=str, default=DEFAULT_REGION, choices=sorted(REGIONS.keys()))
    p.add_argument("--month", type=str, default="", help="YYYY-MM (если не заданы date-from/to).")
    p.add_argument("--date-from", type=str, default="")
    p.add_argument("--date-to", type=str, default="")
    p.add_argument("--limit", type=int, default=1, help="Сколько RTC сцен скачать.")
    p.add_argument("--epsg", type=int, default=3857)
    p.add_argument(
        "--out-root",
        type=str,
        default="",
        help="Корень пакета; пусто = outputs/<дата>/demo_runs/rtc_cop30 (VKR_RUN_DATE).",
    )
    p.add_argument("--api-key", type=str, default=os.environ.get("OPENTOPOGRAPHY_API_KEY", ""))
    args = p.parse_args()

    if bool(args.date_from) ^ bool(args.date_to):
        p.error("Укажите оба: --date-from и --date-to, либо только --month.")

    if not (args.date_from and args.date_to) and not args.month:
        args.month = "2024-06"

    api_key = args.api_key.strip()
    if not api_key:
        print("Нужен ключ OpenTopography: export OPENTOPOGRAPHY_API_KEY=... или --api-key", file=sys.stderr)
        sys.exit(1)

    env = os.environ.copy()
    env["OPENTOPOGRAPHY_API_KEY"] = api_key

    py = sys.executable
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bundle_root = resolve_out_dir(args.out_root, lambda: demo_runs_dir() / "rtc_cop30")
    bundle = bundle_root / f"{args.region}_{stamp}"
    bundle.mkdir(parents=True, exist_ok=True)

    dem_out = _run(
        [
            sys.executable,
            "-m",
            "dem.ingest.reference_dem",
            "--region",
            args.region,
            "--sources",
            "cop30",
            "--epsg",
            str(args.epsg),
            "--api-key",
            api_key,
        ],
        env=env,
    )
    dem_manifest_line = None
    for line in dem_out.splitlines():
        if line.startswith("Manifest:"):
            dem_manifest_line = line.split(":", 1)[1].strip()

    cop30_path: Path | None = None
    if dem_manifest_line:
        mp = Path(dem_manifest_line)
        if mp.is_file():
            man = json.loads(mp.read_text(encoding="utf-8"))
            for layer in man.get("layers") or []:
                alias = str(layer.get("alias", "")).lower()
                demtype = str(layer.get("demtype", ""))
                if "cop30" in alias or "COP30" in demtype:
                    pp = layer.get("processed_path")
                    if pp:
                        cop30_path = Path(pp)
                    break
            if cop30_path is None and man.get("layers"):
                pp0 = man["layers"][0].get("processed_path")
                if pp0:
                    cop30_path = Path(pp0)
    if cop30_path and cop30_path.is_file():
        qdir = bundle / "quality_report"
        qdir.mkdir(parents=True, exist_ok=True)
        _run(
            [
                sys.executable,
                "-m",
                "dem.viz.validate_dem",
                str(cop30_path),
                "--out-dir",
                str(qdir),
                "--region",
                args.region,
            ],
            env=env,
        )

    sar_cmd = [
        sys.executable,
        "-m",
        "dem.ingest.sar_rtc_stac",
        "download",
        "--region",
        args.region,
        "--limit",
        str(args.limit),
        "--dst-epsg",
        str(args.epsg),
    ]
    if args.date_from and args.date_to:
        sar_cmd.extend(["--date-from", args.date_from, "--date-to", args.date_to])
    else:
        sar_cmd.extend(["--month", args.month])

    sar_out = _run(sar_cmd, env=env)
    sar_run = _extract_done_folder(sar_out)
    scene_dir = _first_rtc_scene_dir(sar_run) if sar_run else None

    sar_meta = {}
    if scene_dir:
        stac_json = scene_dir / "image.stac.json"
        if stac_json.is_file():
            sar_meta = json.loads(stac_json.read_text(encoding="utf-8"))

    props = sar_meta.get("properties") or {}
    sar_time = props.get("datetime", "")

    lines = [
        f"# RTC + COP30: {args.region}",
        "",
        f"- Время запуска: `{stamp}`",
        f"- SAR (RTC) run: `{sar_run}`" if sar_run else "- SAR: не найден run",
        f"- Первая сцена: `{scene_dir}`" if scene_dir else "",
        f"- Время съёмки (из STAC): `{sar_time}`",
        f"- DEM manifest: `{dem_manifest_line}`" if dem_manifest_line else "",
        "",
        "## Файлы",
    ]
    if scene_dir:
        lines.append(f"- RTC GeoTIFF: `{scene_dir / 'image.tif'}`")
    qdir = bundle / "quality_report"
    if qdir.is_dir():
        lines.extend(
            [
                "",
                "## Качество DEM (validate_dem)",
                f"- Папка: `{qdir}` — откройте в браузере `*_3d.html`, гистограмма `*_hist.png`, карта `*_map.png`, текст `*_report.md`.",
            ]
        )
    if dem_manifest_line:
        mp = Path(dem_manifest_line)
        if mp.is_file():
            data = json.loads(mp.read_text(encoding="utf-8"))
            for layer in data.get("layers") or []:
                if "cop30" in str(layer.get("alias", "")).lower() or "COP30" in str(layer.get("demtype", "")):
                    lines.append(f"- COP30 (обработанный): `{layer.get('processed_path')}`")
                    break

    readme = bundle / "README.md"
    readme.write_text("\n".join(l for l in lines if l is not None), encoding="utf-8")

    print(f"Пакет: {bundle}")
    print(f"Описание: {readme}")
    if scene_dir:
        print(f"RTC: {scene_dir / 'image.tif'}")
    if dem_manifest_line:
        print(f"DEM manifest: {dem_manifest_line}")


if __name__ == "__main__":
    main()
