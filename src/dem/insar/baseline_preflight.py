# -*- coding: utf-8 -*-
"""SNAP preflight для оценки perpendicular baseline до полного SNAPHU/DEM-прогона."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dem.ingest.asf_slc import SlcScene, build_slc_pairs
from dem.config import DEFAULT_REGION, REGIONS
from dem.insar.pipeline import _find_snap_gpt, _format_bounds, _index_local_slcs, _pair_id, _process_pair
from dem.io.layout import insar_dir, slc_runs_dir


def parse_snaphu_baseline(conf_path: Path) -> dict[str, float | None]:
    text = conf_path.read_text(encoding="utf-8", errors="ignore")

    def value(name: str) -> float | None:
        m = re.search(rf"^\s*{re.escape(name)}\s+([-+0-9.eE]+)\s*$", text, re.MULTILINE)
        if not m:
            return None
        try:
            return float(m.group(1))
        except ValueError:
            return None

    return {
        "baseline_m": value("BASELINE"),
        "baseline_angle_rad": value("BASELINEANGLE_RAD"),
    }


def baseline_status(baseline_m: float | None, *, min_m: float, max_m: float) -> str:
    if baseline_m is None:
        return "unknown"
    b = abs(baseline_m)
    if b < min_m:
        return "too_small"
    if b > max_m:
        return "too_large"
    return "ok"


def _scene_from_row(row: dict[str, Any]) -> SlcScene:
    names = set(SlcScene.__dataclass_fields__.keys())
    return SlcScene(**{k: row[k] for k in names if k in row})


def _load_pairs(manifest_path: Path, *, min_days: int, max_days: int) -> list[dict]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    pairs = data.get("pairs")
    if isinstance(pairs, list) and pairs:
        return [p for p in pairs if isinstance(p, dict)]
    scenes_raw = data.get("scenes")
    if not isinstance(scenes_raw, list) or not scenes_raw:
        raise SystemExit(f"В manifest нет pairs или scenes: {manifest_path}")
    scenes = [_scene_from_row(x) for x in scenes_raw if isinstance(x, dict)]
    return build_slc_pairs(scenes, min_days=min_days, max_days=max_days)


def _resolve_pair_paths(pair: dict, slc_index: dict[str, Path]) -> tuple[Path | None, Path | None]:
    def resolve(file_id: str) -> Path | None:
        hit = slc_index.get(file_id)
        if hit is not None:
            return hit
        matches = [p for key, p in slc_index.items() if file_id in key or key in file_id]
        return matches[0] if matches else None

    return resolve(str(pair.get("master_id", ""))), resolve(str(pair.get("slave_id", "")))


def _find_snaphu_conf(export_dir: Path) -> Path | None:
    direct = export_dir / "snaphu.conf"
    if direct.is_file():
        return direct
    matches = sorted(export_dir.glob("**/snaphu.conf"))
    return matches[0] if matches else None


def _write_reports(rows: list[dict[str, Any]], out_dir: Path) -> tuple[Path, Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "baseline_preflight.json"
    csv_path = out_dir / "baseline_preflight.csv"
    md_path = out_dir / "baseline_preflight.md"

    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    fields = [
        "index",
        "status",
        "baseline_status",
        "baseline_m",
        "eap_correction",
        "region",
        "subswath",
        "first_burst",
        "last_burst",
        "ifg_bounds_wgs84",
        "region_overlap",
        "dt_days",
        "master_id",
        "slave_id",
        "pair_dir",
        "error",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})

    lines = [
        "# Baseline Preflight",
        "",
        f"- generated_utc: `{datetime.now(timezone.utc).isoformat(timespec='seconds')}`",
        f"- rows: `{len(rows)}`",
        "",
        "| # | status | baseline_status | baseline_m | region_overlap | subswath | bursts | dt_days | master | slave |",
        "| ---: | --- | --- | ---: | --- | --- | --- | ---: | --- | --- |",
    ]
    for row in rows:
        baseline = row.get("baseline_m")
        baseline_s = "" if baseline is None else f"{float(baseline):.3f}"
        lines.append(
            f"| {row.get('index')} | {row.get('status')} | {row.get('baseline_status')} | "
            f"{baseline_s} | {row.get('region_overlap', '')} | {row.get('subswath', '')} | "
            f"{row.get('first_burst', '')}..{row.get('last_burst', '')} | {row.get('dt_days', '')} | "
            f"`{row.get('master_id', '')}` | `{row.get('slave_id', '')}` |"
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, csv_path, md_path


def _write_ok_pairs(rows: list[dict[str, Any]], out_dir: Path) -> tuple[Path, Path, Path]:
    ok_rows = [
        row
        for row in rows
        if row.get("status") == "ok"
        and row.get("baseline_status") == "ok"
        and bool(row.get("region_overlap"))
    ]
    json_path = out_dir / "baseline_ok_pairs.json"
    csv_path = out_dir / "baseline_ok_pairs.csv"
    md_path = out_dir / "baseline_ok_pairs.md"
    json_path.write_text(json.dumps(ok_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    fields = [
        "index",
        "baseline_m",
        "eap_correction",
        "region",
        "subswath",
        "first_burst",
        "last_burst",
        "ifg_bounds_wgs84",
        "dt_days",
        "master_id",
        "slave_id",
        "pair_dir",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in ok_rows:
            writer.writerow({k: row.get(k, "") for k in fields})

    lines = [
        "# Baseline OK Pairs",
        "",
        f"- rows: `{len(ok_rows)}`",
        "- filter: `status=ok`, `baseline_status=ok`, `region_overlap=true`",
        "",
        "| # | baseline_m | eap | region | subswath | bursts | dt_days | master | slave |",
        "| ---: | ---: | --- | --- | --- | --- | ---: | --- | --- |",
    ]
    for row in ok_rows:
        lines.append(
            f"| {row.get('index')} | {float(row.get('baseline_m')):.3f} | {row.get('eap_correction')} | "
            f"{row.get('region')} | {row.get('subswath')} | {row.get('first_burst')}..{row.get('last_burst')} | "
            f"{row.get('dt_days', '')} | `{row.get('master_id', '')}` | `{row.get('slave_id', '')}` |"
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, csv_path, md_path


def _gpt_extra_args(args: argparse.Namespace) -> list[str]:
    out: list[str] = []
    if args.gpt_cache:
        out.extend(["-c", str(args.gpt_cache)])
    if args.gpt_threads:
        out.extend(["-q", str(args.gpt_threads)])
    out.extend(args.extra_gpt_args or [])
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="SNAP preflight: извлечь BASELINE из SnaphuExport без запуска SNAPHU.")
    p.add_argument("--manifest", required=True, help="Manifest от slc_budget_plan или download manifest со scenes.")
    p.add_argument("--slc-dir", default="", help="Каталог скачанных SLC ZIP; пусто = текущий VKR_DATA_ROOT outputs.")
    p.add_argument("--out-dir", default="", help="Куда писать preflight; пусто = outputs/<date>/insar/baseline_preflight.")
    p.add_argument("--limit", type=int, default=3, help="Сколько пар прогнать через SNAP.")
    p.add_argument("--min-days", type=int, default=6)
    p.add_argument("--max-days", type=int, default=36)
    p.add_argument("--min-baseline", type=float, default=80.0)
    p.add_argument("--max-baseline", type=float, default=450.0)
    p.add_argument("--region", type=str, default=DEFAULT_REGION, choices=sorted(REGIONS.keys()))
    p.add_argument("--subswath", default="auto", help="auto|IW1|IW2|IW3; auto подбирает subswath по пересечению с --region.")
    p.add_argument("--polarization", default="VV")
    p.add_argument("--first-burst", type=int, default=0, help="0 = все bursts в выбранном subswath.")
    p.add_argument("--last-burst", type=int, default=0, help="0 = все bursts в выбранном subswath.")
    p.add_argument("--dem-name", default="Copernicus 30m Global DEM")
    p.add_argument("--gpt-exec", default="", help="Полный путь к SNAP gpt; иначе авто-поиск.")
    p.add_argument("--gpt-cache", default="12G", help="SNAP GPT cache size, например 12G.")
    p.add_argument("--gpt-threads", type=int, default=4, help="SNAP GPT parallelism, например 4.")
    p.add_argument("--extra-gpt-args", nargs="*", default=[])
    p.add_argument(
        "--eap-mode",
        choices=["auto", "none", "master", "slave", "both"],
        default="auto",
        help="auto перебирает EAP-Phase-Correction: none, master, slave, both.",
    )
    p.add_argument("--force", action="store_true", help="Перезапускать SNAP, даже если snaphu.conf уже есть.")
    p.add_argument(
        "--cleanup-workdirs",
        action="store_true",
        help="Удалять тяжёлые SNAP workdir пары после извлечения baseline; отчёты JSON/CSV/MD сохраняются.",
    )
    args = p.parse_args()

    manifest_path = Path(args.manifest).expanduser()
    pairs = _load_pairs(manifest_path, min_days=args.min_days, max_days=args.max_days)
    if args.limit > 0:
        pairs = pairs[: args.limit]
    if not pairs:
        raise SystemExit("Нет пар для preflight.")

    slc_root = Path(args.slc_dir).expanduser() if args.slc_dir else slc_runs_dir()
    slc_index = _index_local_slcs(slc_root)
    if not slc_index:
        raise SystemExit(f"Не найдены SLC ZIP в {slc_root}")

    out_dir = Path(args.out_dir).expanduser() if args.out_dir else insar_dir() / "baseline_preflight"
    out_dir.mkdir(parents=True, exist_ok=True)
    gpt = _find_snap_gpt(args.gpt_exec)
    if not gpt:
        raise SystemExit("SNAP gpt не найден. Укажите --gpt-exec или export SNAP_GPT=/Applications/esa-snap/bin/gpt")

    rows: list[dict[str, Any]] = []
    for i, pair in enumerate(pairs, start=1):
        master_id = str(pair.get("master_id", ""))
        slave_id = str(pair.get("slave_id", ""))
        master_path, slave_path = _resolve_pair_paths(pair, slc_index)
        row: dict[str, Any] = {
            "index": i,
            "master_id": master_id,
            "slave_id": slave_id,
            "dt_days": pair.get("temporal_baseline_days"),
            "status": "pending",
            "baseline_status": "unknown",
            "baseline_m": None,
            "baseline_angle_rad": None,
            "eap_correction": "",
            "region": args.region,
            "subswath": "",
            "first_burst": args.first_burst,
            "last_burst": args.last_burst,
            "ifg_bounds_wgs84": "",
            "region_overlap": False,
            "pair_dir": "",
            "error": "",
        }
        if master_path is None or slave_path is None:
            row["status"] = "missing_slc"
            row["error"] = "master/slave ZIP not found locally"
            rows.append(row)
            continue

        pair_dir = out_dir / _pair_id(str(master_path), str(slave_path))
        export_dir = pair_dir / "snaphu_export"
        conf_path = _find_snaphu_conf(export_dir)
        try:
            if conf_path is None or args.force:
                modes = ["none", "master", "slave", "both"] if args.eap_mode == "auto" else [args.eap_mode]
                last_error: str | None = None
                for mode in modes:
                    print(f"[{i}/{len(pairs)}] SNAP preflight ({mode}): {master_id} VS {slave_id}", flush=True)
                    try:
                        art = _process_pair(
                            master=str(master_path),
                            slave=str(slave_path),
                            subswath=args.subswath,
                            polarization=args.polarization,
                            dem_name=args.dem_name,
                            pixel_spacing_m=10.0,
                            first_burst=args.first_burst,
                            last_burst=args.last_burst,
                            out_dir=out_dir,
                            gpt=gpt,
                            snaphu_exec=None,
                            extra_gpt_args=_gpt_extra_args(args),
                            skip_unwrap=True,
                            skip_phase_to_height=True,
                            eap_correction=mode,
                            region=args.region,
                            require_region_overlap=True,
                        )
                        pair_dir = art.pair_dir
                        export_dir = art.export_dir
                        conf_path = _find_snaphu_conf(export_dir)
                        row["eap_correction"] = mode
                        row["subswath"] = art.subswath
                        row["first_burst"] = art.first_burst
                        row["last_burst"] = art.last_burst
                        row["ifg_bounds_wgs84"] = _format_bounds(art.ifg_bounds)
                        row["region_overlap"] = art.region_overlap
                        break
                    except SystemExit as e:
                        last_error = str(e)
                        row["eap_correction"] = mode
                        continue
                if conf_path is None and last_error:
                    raise RuntimeError(last_error)
            if conf_path is None:
                raise RuntimeError(f"snaphu.conf не найден в {export_dir}")
            values = parse_snaphu_baseline(conf_path)
            row["baseline_m"] = values["baseline_m"]
            row["baseline_angle_rad"] = values["baseline_angle_rad"]
            row["baseline_status"] = baseline_status(
                values["baseline_m"],
                min_m=args.min_baseline,
                max_m=args.max_baseline,
            )
            row["status"] = "ok"
            row["pair_dir"] = str(pair_dir)
        except SystemExit as e:
            row["status"] = "snap_failed"
            row["pair_dir"] = str(pair_dir)
            row["error"] = str(e)
        except Exception as e:  # noqa: BLE001
            row["status"] = "error"
            row["pair_dir"] = str(pair_dir)
            row["error"] = str(e)
        rows.append(row)
        if args.cleanup_workdirs and pair_dir.exists():
            shutil.rmtree(pair_dir, ignore_errors=True)
        _, _, md_path = _write_reports(rows, out_dir)
        _write_ok_pairs(rows, out_dir)
        print(f"  report: {md_path}", flush=True)

    json_path, csv_path, md_path = _write_reports(rows, out_dir)
    ok_json_path, ok_csv_path, ok_md_path = _write_ok_pairs(rows, out_dir)
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print(f"MD:   {md_path}")
    print(f"OK JSON: {ok_json_path}")
    print(f"OK CSV:  {ok_csv_path}")
    print(f"OK MD:   {ok_md_path}")


if __name__ == "__main__":
    main()
