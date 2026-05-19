# -*- coding: utf-8 -*-
"""
InSAR-пайплайн поверх ESA SNAP + SNAPHU.

Подкоманды:
    doctor             — проверить gpt/snaphu и регион по умолчанию
    write-template     — минимальный graph с двумя Read (для ручной правки в SNAP)
    write-full-graph   — параметризовать полный граф (TOPSAR → SnaphuExport / Phase-to-Height)
    run-pair           — прогнать одну пару SLC (graph + Snaphu + Phase-to-Height)
    run-batch          — пакетно прогнать пары из JSON, выданного pair_search
    snaphu-unwrap      — отдельно запустить snaphu по результату SnaphuExport
    phase-to-height    — отдельно запустить второй граф (импорт UnwPhase → DEM GeoTIFF)
    run-gpt            — отладочный запуск gpt с готовым graph.xml

RTC-амплитуда из STAC не содержит фазы; для классической интерферометрии нужны Sentinel-1 SLC.
Установка SNAP:    https://step.esa.int/main/download/snap-download/
SNAPHU:            https://web.stanford.edu/group/radar/softwareandlinks/sw/snaphu/
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from dem.config import DEFAULT_REGION, REGIONS
from dem.geo.utils import region_bbox
from dem.insar.snaphu import expected_unwrapped_hdr, find_wrapped_phase_img, resolve_snaphu_binary, run_snaphu
from dem.io.layout import insar_dir, resolve_out_dir, slc_runs_dir

GRAPHS_DIR = Path(__file__).resolve().parent / "graphs"
GRAPH_FULL = GRAPHS_DIR / "s1_topsar_insar_snaphu_export.xml"
GRAPH_PHASE_TO_HEIGHT = GRAPHS_DIR / "s1_phase_to_height.xml"

SNAP_GRAPH_TEMPLATE_MIN = """<?xml version="1.0" encoding="UTF-8"?>
<graph id="S1_SLC_read_pair">
  <version>3.0</version>
  <node id="Read-M">
    <operator>Read</operator>
    <sources/>
    <parameters class="com.bc.ceres.binding.dom.Xpp3DomElement">
      <file>{master_slc}</file>
    </parameters>
  </node>
  <node id="Read-S">
    <operator>Read</operator>
    <sources/>
    <parameters class="com.bc.ceres.binding.dom.Xpp3DomElement">
      <file>{slave_slc}</file>
    </parameters>
  </node>
  <!-- Дальше: TOPSAR-Split, Apply-Orbit-File, Back-Geocoding, Interferogram, Goldstein, SnaphuExport -->
</graph>
"""


# --------------------------------------------------------------------------- helpers


def which_or_empty(name: str) -> str:
    return shutil.which(name) or ""


def _looks_like_snap_gpt(gpt_path: str) -> bool:
    if not gpt_path:
        return False
    if sys.platform == "darwin" and gpt_path == "/usr/sbin/gpt":
        return False
    low = gpt_path.lower()
    if "snap" in low or "esa" in low or "step" in low:
        return True
    try:
        r = subprocess.run([gpt_path, "-h"], capture_output=True, text=True, timeout=5)
        out = ((r.stdout or "") + (r.stderr or "")).upper()
        return "SNAP" in out or "SENTINEL" in out or "TOOLBOX" in out
    except Exception:
        return False


def _darwin_snap_gpt_candidates() -> list[str]:
    if sys.platform != "darwin":
        return []
    return ["/Applications/esa-snap/bin/gpt", "/Applications/snap/bin/gpt"]


def _find_snap_gpt(gpt_executable: str = "") -> str | None:
    candidates: list[str] = []
    if gpt_executable.strip():
        candidates.append(gpt_executable.strip())
    env_gpt = os.environ.get("SNAP_GPT", "").strip()
    if env_gpt:
        candidates.append(env_gpt)
    candidates.extend(_darwin_snap_gpt_candidates())
    w = which_or_empty("gpt")
    if w and not (sys.platform == "darwin" and w == "/usr/sbin/gpt"):
        candidates.append(w)

    for c in candidates:
        if Path(c).is_file() and _looks_like_snap_gpt(c):
            return c
    return None


def _resolve_gpt(gpt_executable: str = "") -> str:
    gpt = _find_snap_gpt(gpt_executable)
    if not gpt:
        raise SystemExit(
            "gpt (ESA SNAP) не найден. На macOS: export SNAP_GPT=/Applications/esa-snap/bin/gpt "
            "или добавьте esa-snap/bin в PATH перед /usr/sbin. Либо --gpt-exec."
        )
    return gpt


def _resolve_snaphu_exec(snaphu_executable: str | None = None) -> str | None:
    """Бинарь SNAPHU: CLI → SNAPHU_EXEC → PATH."""

    exe = (snaphu_executable or "").strip() or None
    return resolve_snaphu_binary(exe)


def _render_template(graph_xml: Path, replacements: dict[str, str]) -> str:
    text = graph_xml.read_text(encoding="utf-8")
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text


def _run_gpt(gpt: str, graph_path: Path, *, extra_args: list[str] | None = None, log_path: Path | None = None) -> int:
    cmd = [gpt, *(extra_args or []), str(graph_path)]
    print("[gpt]", " ".join(cmd))
    env = {**os.environ, "COPYFILE_DISABLE": "1"}
    if log_path is None:
        return subprocess.call(cmd, env=env)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"# cmd: {' '.join(cmd)}\n\n")
        log.flush()
        return subprocess.call(cmd, stdout=log, stderr=subprocess.STDOUT, env=env)


def _gpt_extra_args(args: argparse.Namespace) -> list[str]:
    out: list[str] = []
    cache = getattr(args, "gpt_cache", "")
    threads = getattr(args, "gpt_threads", 0)
    if cache:
        out.extend(["-c", str(cache)])
    if threads:
        out.extend(["-q", str(threads)])
    out.extend(getattr(args, "extra_gpt_args", []) or [])
    return out


def _slc_short(p: str) -> str:
    """Короткий человекочитаемый идентификатор SLC из имени файла."""

    name = Path(p).stem
    parts = name.split("_")
    if len(parts) >= 6:
        return "_".join(parts[:6])
    return name[:32]


def _pair_id(master: str, slave: str) -> str:
    return f"{_slc_short(master)}__VS__{_slc_short(slave)}"


def _bbox_tuple(region: dict) -> tuple[float, float, float, float]:
    bb = region_bbox(region)
    return (float(bb["west"]), float(bb["south"]), float(bb["east"]), float(bb["north"]))


def _bbox_intersects(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    west_a, south_a, east_a, north_a = a
    west_b, south_b, east_b, north_b = b
    return west_a <= east_b and east_a >= west_b and south_a <= north_b and north_a >= south_b


def _ifg_geobounds(ifg_dim: Path) -> tuple[float, float, float, float] | None:
    """Грубые WGS84 bounds IFG по tie-point grids: west, south, east, north."""

    data_dir = ifg_dim.with_suffix(".data")
    lon_path = data_dir / "tie_point_grids" / "longitude.img"
    lat_path = data_dir / "tie_point_grids" / "latitude.img"
    if not lon_path.is_file() or not lat_path.is_file():
        return None
    try:
        import numpy as np
        import rasterio

        with rasterio.open(lon_path) as lon_src, rasterio.open(lat_path) as lat_src:
            lon = lon_src.read(1).astype("float64")
            lat = lat_src.read(1).astype("float64")
        valid = np.isfinite(lon) & np.isfinite(lat)
        if not valid.any():
            return None
        return (
            float(np.nanmin(lon[valid])),
            float(np.nanmin(lat[valid])),
            float(np.nanmax(lon[valid])),
            float(np.nanmax(lat[valid])),
        )
    except Exception:
        return None


def _format_bounds(bounds: tuple[float, float, float, float] | None) -> str:
    if bounds is None:
        return "unknown"
    west, south, east, north = bounds
    return f"{west:.6f},{south:.6f},{east:.6f},{north:.6f}"


def _ifg_overlaps_region(ifg_dim: Path, region_name: str) -> tuple[bool, tuple[float, float, float, float] | None]:
    region = REGIONS.get(region_name)
    if region is None:
        raise ValueError(f"Неизвестный регион: {region_name}")
    ifg_bounds = _ifg_geobounds(ifg_dim)
    if ifg_bounds is None:
        return False, None
    return _bbox_intersects(ifg_bounds, _bbox_tuple(region)), ifg_bounds


def _remove_appledouble_files(root: Path) -> int:
    """Удалить служебные macOS AppleDouble-файлы, которые SNAP пытается читать как данные."""

    if not root.exists():
        return 0
    removed = 0
    for p in root.rglob("._*"):
        if not p.name.startswith("._"):
            continue
        if p.is_file():
            p.unlink()
            removed += 1
    return removed


# --------------------------------------------------------------------------- run-pair


@dataclass
class PairArtifacts:
    pair_dir: Path
    ifg_dim: Path
    export_dir: Path
    unw_hdr: Path | None
    dem_tif: Path | None
    summary: Path
    subswath: str
    first_burst: int
    last_burst: int
    region: str
    ifg_bounds: tuple[float, float, float, float] | None
    region_overlap: bool


def _pair_summary_path(pair_dir: Path) -> Path:
    return pair_dir / "summary.md"


def _patch_pair_summary(
    pair_dir: Path,
    *,
    unw_hdr: Path | None = None,
    dem_tif: Path | None = None,
) -> Path:
    """Обновить ``summary.md`` в каталоге пары (пути без принудительного resolve — как в ``run-pair``)."""

    summary_path = _pair_summary_path(pair_dir)
    if summary_path.is_file():
        lines = summary_path.read_text(encoding="utf-8").splitlines()
    else:
        lines = [
            f"# InSAR pair: {pair_dir.name}",
            "",
            f"- ifg_dim: `{pair_dir / 'ifg.dim'}`",
            f"- snaphu_export: `{pair_dir / 'snaphu_export'}`",
            "- unwrapped (UnwPhase.hdr): `None`",
            "- dem_insar.tif: `None`",
        ]

    def _replace_or_append(prefix: str, new_line: str) -> None:
        for i, ln in enumerate(lines):
            if ln.startswith(prefix):
                lines[i] = new_line
                return
        lines.append(new_line)

    if unw_hdr is not None:
        _replace_or_append("- unwrapped (UnwPhase.hdr):", f"- unwrapped (UnwPhase.hdr): `{unw_hdr}`")
    if dem_tif is not None:
        _replace_or_append("- dem_insar.tif:", f"- dem_insar.tif: `{dem_tif}`")

    fin_p = "- finished_utc:"
    fin_line = f"- finished_utc: `{datetime.now(timezone.utc).isoformat(timespec='seconds')}`"
    for i, ln in enumerate(lines):
        if ln.startswith(fin_p):
            lines[i] = fin_line
            break
    else:
        lines.append(fin_line)

    summary_path.write_text("\n".join(lines), encoding="utf-8")
    return summary_path


def _run_full_graph(
    *,
    gpt: str,
    master: str,
    slave: str,
    subswath: str,
    polarization: str,
    dem_name: str,
    first_burst: int,
    last_burst: int,
    export_dir: Path,
    ifg_dim: Path,
    workspace: Path,
    extra_gpt_args: list[str],
    eap_correction: str = "none",
) -> Path:
    burst_range = ""
    if first_burst > 0 and last_burst > 0:
        if last_burst < first_burst:
            raise ValueError("last_burst должен быть >= first_burst")
        burst_range = f"<firstBurstIndex>{first_burst}</firstBurstIndex>\n      <lastBurstIndex>{last_burst}</lastBurstIndex>"
    eap_mode = (eap_correction or "none").strip().lower()
    if eap_mode not in {"none", "master", "slave", "both"}:
        raise ValueError("eap_correction должен быть одним из: none, master, slave, both")
    eap_master_node = ""
    eap_slave_node = ""
    master_source = "Apply-Orbit-File-Master"
    slave_source = "Apply-Orbit-File-Slave"
    if eap_mode in {"master", "both"}:
        eap_master_node = """<node id="EAP-Phase-Correction-Master">
    <operator>EAP-Phase-Correction</operator>
    <sources>
      <sourceProduct refid="Apply-Orbit-File-Master"/>
    </sources>
    <parameters/>
  </node>"""
        master_source = "EAP-Phase-Correction-Master"
    if eap_mode in {"slave", "both"}:
        eap_slave_node = """<node id="EAP-Phase-Correction-Slave">
    <operator>EAP-Phase-Correction</operator>
    <sources>
      <sourceProduct refid="Apply-Orbit-File-Slave"/>
    </sources>
    <parameters/>
  </node>"""
        slave_source = "EAP-Phase-Correction-Slave"
    rendered = _render_template(
        GRAPH_FULL,
        {
            "__MASTER__": str(Path(master).resolve()),
            "__SLAVE__": str(Path(slave).resolve()),
            "__SUBSWATH__": subswath,
            "__POLARIZATION__": polarization,
            "__DEM_NAME__": dem_name,
            "__BURST_RANGE__": burst_range,
            "__EAP_MASTER_NODE__": eap_master_node,
            "__EAP_SLAVE_NODE__": eap_slave_node,
            "__MASTER_BACK_GEOCODING_SOURCE__": master_source,
            "__SLAVE_BACK_GEOCODING_SOURCE__": slave_source,
            "__EXPORT_DIR__": str(export_dir.resolve()),
            "__IFG_DIM__": str(ifg_dim.resolve()),
        },
    )
    graph_out = workspace / "graph_topsar_insar.xml"
    graph_out.write_text(rendered, encoding="utf-8")
    rc = _run_gpt(gpt, graph_out, extra_args=extra_gpt_args, log_path=workspace / "gpt_topsar_insar.log")
    if rc != 0:
        raise SystemExit(f"gpt (TOPSAR/InSAR) завершился с кодом {rc}; см. лог {workspace / 'gpt_topsar_insar.log'}")
    return graph_out


def _run_phase_to_height_graph(
    *,
    gpt: str,
    ifg_dim: Path,
    unw_hdr: Path,
    dem_name: str,
    out_tif: Path,
    pixel_spacing_m: float,
    workspace: Path,
    extra_gpt_args: list[str],
) -> Path:
    rendered = _render_template(
        GRAPH_PHASE_TO_HEIGHT,
        {
            "__IFG_DIM__": str(ifg_dim.resolve()),
            "__UNW_HDR__": str(unw_hdr.resolve()),
            "__DEM_NAME__": dem_name,
            "__OUT_TIF__": str(out_tif.resolve()),
            "__PIXEL_SPACING__": f"{pixel_spacing_m:.3f}",
        },
    )
    graph_out = workspace / "graph_phase_to_height.xml"
    graph_out.write_text(rendered, encoding="utf-8")
    rc = _run_gpt(gpt, graph_out, extra_args=extra_gpt_args, log_path=workspace / "gpt_phase_to_height.log")
    if rc != 0:
        raise SystemExit(f"gpt (Phase-to-Height) завершился с кодом {rc}; см. лог {workspace / 'gpt_phase_to_height.log'}")
    return graph_out


def _process_pair(
    *,
    master: str,
    slave: str,
    subswath: str,
    polarization: str,
    dem_name: str,
    pixel_spacing_m: float,
    first_burst: int,
    last_burst: int,
    out_dir: Path,
    gpt: str,
    snaphu_exec: str | None,
    extra_gpt_args: list[str],
    skip_unwrap: bool,
    skip_phase_to_height: bool,
    eap_correction: str = "none",
    region: str = DEFAULT_REGION,
    require_region_overlap: bool = True,
) -> PairArtifacts:
    pair_dir = out_dir / _pair_id(master, slave)
    pair_dir.mkdir(parents=True, exist_ok=True)
    export_dir = pair_dir / "snaphu_export"
    export_dir.mkdir(parents=True, exist_ok=True)
    ifg_dim = pair_dir / "ifg.dim"
    summary = pair_dir / "summary.md"

    subswath_mode = (subswath or "auto").strip().upper()
    subswath_candidates = ["IW1", "IW2", "IW3"] if subswath_mode == "AUTO" else [subswath_mode]
    selected_subswath = ""
    ifg_bounds: tuple[float, float, float, float] | None = None
    region_overlap = False
    last_error: str | None = None
    for candidate in subswath_candidates:
        try:
            _run_full_graph(
                gpt=gpt,
                master=master,
                slave=slave,
                subswath=candidate,
                polarization=polarization,
                dem_name=dem_name,
                first_burst=first_burst,
                last_burst=last_burst,
                export_dir=export_dir,
                ifg_dim=ifg_dim,
                workspace=pair_dir,
                extra_gpt_args=extra_gpt_args,
                eap_correction=eap_correction,
            )
            region_overlap, ifg_bounds = _ifg_overlaps_region(ifg_dim, region)
            print(
                f"[coverage] region={region} subswath={candidate} "
                f"ifg_bounds={_format_bounds(ifg_bounds)} overlap={region_overlap}"
            )
            if region_overlap or not require_region_overlap:
                selected_subswath = candidate
                break
            last_error = (
                f"IFG не пересекает регион {region}: subswath={candidate}, "
                f"ifg_bounds={_format_bounds(ifg_bounds)}"
            )
        except SystemExit as e:
            last_error = str(e)
            if subswath_mode != "AUTO":
                raise
            continue

    if not selected_subswath:
        raise SystemExit(last_error or f"Не удалось подобрать subswath для региона {region}")

    unw_hdr: Path | None = None
    if not skip_unwrap:
        run = run_snaphu(export_dir, snaphu_executable=snaphu_exec)
        unw_hdr = run.out_unw_hdr or expected_unwrapped_hdr(find_wrapped_phase_img(export_dir))

    dem_tif: Path | None = None
    if not skip_phase_to_height and unw_hdr is not None:
        dem_tif = pair_dir / "dem_insar.tif"
        removed = _remove_appledouble_files(pair_dir)
        if removed:
            print(f"[cleanup] removed {removed} macOS AppleDouble files before Phase-to-Height")
        _run_phase_to_height_graph(
            gpt=gpt,
            ifg_dim=ifg_dim,
            unw_hdr=unw_hdr,
            dem_name=dem_name,
            out_tif=dem_tif,
            pixel_spacing_m=pixel_spacing_m,
            workspace=pair_dir,
            extra_gpt_args=extra_gpt_args,
        )

    lines = [
        f"# InSAR pair: {_pair_id(master, slave)}",
        "",
        f"- master: `{master}`",
        f"- slave:  `{slave}`",
        f"- region: `{region}`",
        f"- subswath: `{selected_subswath}` · polarization: `{polarization}` · DEM (back-geocoding): `{dem_name}`",
        f"- burst range: `{first_burst or 'auto'}..{last_burst or 'auto'}`",
        f"- ifg_bounds_wgs84: `{_format_bounds(ifg_bounds)}`",
        f"- region_overlap: `{region_overlap}`",
        f"- EAP correction: `{eap_correction}`",
        f"- ifg_dim: `{ifg_dim}`",
        f"- snaphu_export: `{export_dir}`",
        f"- unwrapped (UnwPhase.hdr): `{unw_hdr}`",
        f"- dem_insar.tif: `{dem_tif}`",
        f"- finished_utc: `{datetime.now(timezone.utc).isoformat(timespec='seconds')}`",
    ]
    summary.write_text("\n".join(lines), encoding="utf-8")
    return PairArtifacts(
        pair_dir=pair_dir,
        ifg_dim=ifg_dim,
        export_dir=export_dir,
        unw_hdr=unw_hdr,
        dem_tif=dem_tif,
        summary=summary,
        subswath=selected_subswath,
        first_burst=first_burst,
        last_burst=last_burst,
        region=region,
        ifg_bounds=ifg_bounds,
        region_overlap=region_overlap,
    )


# --------------------------------------------------------------------------- batch


def _resolve_slc_path(idx: dict[str, Path], file_id: str) -> Path | None:
    p = idx.get(file_id)
    if p is None:
        cands = [v for k, v in idx.items() if file_id in k]
        if cands:
            return cands[0]
    return p


def _index_local_slcs(slc_root: Path | None) -> dict[str, Path]:
    out: dict[str, Path] = {}
    if slc_root is None or not slc_root.is_dir():
        return out
    for ext in ("*.zip", "*.SAFE"):
        for p in slc_root.rglob(ext):
            if p.name.startswith("._"):
                continue
            out[p.stem] = p
            out[p.name] = p
    return out


# --------------------------------------------------------------------------- subcommands


def cmd_doctor(_: argparse.Namespace) -> None:
    print("=== InSAR окружение ===")

    snap_gpt = _find_snap_gpt("")
    if snap_gpt:
        print(f"gpt (SNAP):     {snap_gpt}")
        if not os.environ.get("SNAP_GPT", "").strip() and snap_gpt in _darwin_snap_gpt_candidates():
            print(
                "                Можно зафиксировать путь в ~/.zshrc:\n"
                f'                export SNAP_GPT="{snap_gpt}"'
            )
    else:
        gpt_path = which_or_empty("gpt")
        if gpt_path and sys.platform == "darwin" and gpt_path == "/usr/sbin/gpt":
            print(f"gpt в PATH:     {gpt_path}  (это не ESA SNAP — утилита разделов macOS)")
        elif gpt_path:
            print(f"gpt в PATH:     {gpt_path}  (не распознан как ESA SNAP)")
        print(
            "gpt (SNAP):     НЕ НАЙДЕН. На macOS: export SNAP_GPT=/Applications/esa-snap/bin/gpt"
        )

    snaphu_path = _resolve_snaphu_exec(None)
    if snaphu_path:
        print(f"snaphu:         {snaphu_path}")
        if not os.environ.get("SNAPHU_EXEC", "").strip():
            print(
                "                Можно закрепить путь в ~/.zshrc:\n"
                f'                export SNAPHU_EXEC="{snaphu_path}"'
            )
    else:
        print("snaphu:         НЕ НАЙДЕН в PATH и $SNAPHU_EXEC.")
        print(
            "                Сборка из исходников → bin/snaphu; затем:\n"
            '                export SNAPHU_EXEC="/полный/путь/к/snaphu"'
        )
    print(f"\nГрафы:")
    print(f"  full:           {GRAPH_FULL}{' (ok)' if GRAPH_FULL.is_file() else ' (ОТСУТСТВУЕТ)'}")
    print(f"  phase_to_height:{GRAPH_PHASE_TO_HEIGHT}{' (ok)' if GRAPH_PHASE_TO_HEIGHT.is_file() else ' (ОТСУТСТВУЕТ)'}")
    print("\nРегион по умолчанию:", DEFAULT_REGION)
    bb = region_bbox(REGIONS[DEFAULT_REGION])
    print(f"  bbox WGS84: {bb}")


def cmd_write_template(args: argparse.Namespace) -> None:
    out = resolve_out_dir(args.output, lambda: insar_dir() / "s1_slc_read_pair.xml")
    out.parent.mkdir(parents=True, exist_ok=True)
    text = SNAP_GRAPH_TEMPLATE_MIN.format(master_slc=args.master, slave_slc=args.slave)
    out.write_text(text, encoding="utf-8")
    print(f"Записано: {out}")
    print("Откройте файл в SNAP Graph Builder и допишите цепочку TOPSAR/InSAR.")


def cmd_write_full_graph(args: argparse.Namespace) -> None:
    if str(args.subswath).strip().lower() == "auto":
        raise SystemExit("write-full-graph требует конкретный --subswath IW1|IW2|IW3; auto доступен в run-pair/run-batch.")
    out = resolve_out_dir(args.output, lambda: insar_dir() / "graph_topsar_insar_rendered.xml")
    out.parent.mkdir(parents=True, exist_ok=True)
    rendered = _render_template(
        GRAPH_FULL,
        {
            "__MASTER__": str(Path(args.master).resolve()),
            "__SLAVE__": str(Path(args.slave).resolve()),
            "__SUBSWATH__": args.subswath,
            "__POLARIZATION__": args.polarization,
            "__DEM_NAME__": args.dem_name,
            "__BURST_RANGE__": (
                f"<firstBurstIndex>{args.first_burst}</firstBurstIndex>\n      <lastBurstIndex>{args.last_burst}</lastBurstIndex>"
                if args.first_burst > 0 and args.last_burst > 0
                else ""
            ),
            "__EAP_MASTER_NODE__": "",
            "__EAP_SLAVE_NODE__": "",
            "__MASTER_BACK_GEOCODING_SOURCE__": "Apply-Orbit-File-Master",
            "__SLAVE_BACK_GEOCODING_SOURCE__": "Apply-Orbit-File-Slave",
            "__EXPORT_DIR__": str(Path(args.export_dir).resolve()),
            "__IFG_DIM__": str(Path(args.ifg_dim).resolve()),
        },
    )
    out.write_text(rendered, encoding="utf-8")
    print(f"Записано: {out}")


def cmd_run_pair(args: argparse.Namespace) -> None:
    gpt = _resolve_gpt(args.gpt_executable)
    out_dir = resolve_out_dir(args.out_dir, lambda: insar_dir() / "pairs")
    out_dir.mkdir(parents=True, exist_ok=True)
    art = _process_pair(
        master=args.master,
        slave=args.slave,
        subswath=args.subswath,
        polarization=args.polarization,
        dem_name=args.dem_name,
        pixel_spacing_m=args.pixel_spacing,
        first_burst=args.first_burst,
        last_burst=args.last_burst,
        out_dir=out_dir,
        gpt=gpt,
        snaphu_exec=args.snaphu_executable or None,
        extra_gpt_args=_gpt_extra_args(args),
        skip_unwrap=args.skip_unwrap,
        skip_phase_to_height=args.skip_phase_to_height,
        eap_correction=args.eap_correction,
        region=args.region,
        require_region_overlap=not args.allow_outside_region,
    )
    print(f"Готово: {art.pair_dir}")
    print(f"Summary: {art.summary}")
    if art.dem_tif:
        print(f"DEM:   {art.dem_tif}")


def cmd_run_batch(args: argparse.Namespace) -> None:
    gpt = _resolve_gpt(args.gpt_executable)
    pairs_path = Path(args.pairs)
    if not pairs_path.is_file():
        raise SystemExit(f"Не найден файл пар: {pairs_path}")
    pairs = json.loads(pairs_path.read_text(encoding="utf-8"))
    if not isinstance(pairs, list):
        raise SystemExit("pairs.json должен быть JSON-массивом (вывод dem.insar.pair_search).")
    if args.limit:
        pairs = pairs[: args.limit]

    slc_root = Path(args.slc_dir) if args.slc_dir else slc_runs_dir()
    idx = _index_local_slcs(slc_root)
    if not idx:
        raise SystemExit(f"Не найдено локальных SLC в {slc_root}. Сначала dem.ingest.sar_slc_download download …")

    out_dir = resolve_out_dir(args.out_dir, lambda: insar_dir() / "pairs")
    out_dir.mkdir(parents=True, exist_ok=True)

    log_lines = ["# InSAR batch run", "", f"- pairs.json: `{pairs_path}`", f"- slc_dir: `{slc_root}`", ""]
    successes = 0
    failures = 0
    for i, pair in enumerate(pairs, start=1):
        m_id = pair.get("master_id", "")
        s_id = pair.get("slave_id", "")
        m_path = _resolve_slc_path(idx, m_id)
        s_path = _resolve_slc_path(idx, s_id)
        if m_path is None or s_path is None:
            log_lines.append(f"- [{i}] **skipped** (не найден локальный SLC) master=`{m_id}` slave=`{s_id}`")
            failures += 1
            continue
        try:
            art = _process_pair(
                master=str(m_path),
                slave=str(s_path),
                subswath=str(pair.get("subswath") or args.subswath),
                polarization=pair.get("polarization", args.polarization).split()[0] if pair.get("polarization") else args.polarization,
                dem_name=args.dem_name,
                pixel_spacing_m=args.pixel_spacing,
                first_burst=int(pair.get("first_burst") or args.first_burst),
                last_burst=int(pair.get("last_burst") or args.last_burst),
                out_dir=out_dir,
                gpt=gpt,
                snaphu_exec=args.snaphu_executable or None,
                extra_gpt_args=_gpt_extra_args(args),
                skip_unwrap=args.skip_unwrap,
                skip_phase_to_height=args.skip_phase_to_height,
                eap_correction=str(pair.get("eap_correction") or args.eap_correction),
                region=str(pair.get("region") or args.region),
                require_region_overlap=not args.allow_outside_region,
            )
            log_lines.append(
                f"- [{i}] ok → `{art.pair_dir}` "
                f"(region=`{art.region}`, subswath=`{art.subswath}`, ifg_bounds=`{_format_bounds(art.ifg_bounds)}`)"
            )
            successes += 1
        except SystemExit as e:
            log_lines.append(f"- [{i}] **fail**: {e}")
            failures += 1
        except Exception as e:  # noqa: BLE001
            log_lines.append(f"- [{i}] **error**: {e}")
            failures += 1

    log = out_dir / "batch_log.md"
    log.write_text("\n".join(log_lines + ["", f"successes: {successes}", f"failures: {failures}"]), encoding="utf-8")
    print(f"Batch log: {log}")
    print(f"successes={successes}  failures={failures}")


def cmd_snaphu_unwrap(args: argparse.Namespace) -> None:
    export_dir = Path(args.export_dir)
    if not export_dir.is_dir():
        raise SystemExit(f"Нет каталога экспорта: {export_dir}")
    run = run_snaphu(export_dir, snaphu_executable=args.snaphu_executable or None)
    print(f"snaphu log: {run.log_path}")
    if run.out_unw_hdr:
        print(f"Unwrapped:  {run.out_unw_hdr}")
    pair_dir = export_dir.parent
    if pair_dir.is_dir() and export_dir.name == "snaphu_export":
        sp = _patch_pair_summary(pair_dir, unw_hdr=run.out_unw_hdr)
        print(f"Summary:    {sp}")


def cmd_phase_to_height(args: argparse.Namespace) -> None:
    gpt = _resolve_gpt(args.gpt_executable)
    workspace = Path(args.workspace) if args.workspace else Path(args.ifg_dim).parent
    out_tif = Path(args.out_tif) if args.out_tif else workspace / "dem_insar.tif"
    removed = _remove_appledouble_files(workspace)
    if removed:
        print(f"[cleanup] removed {removed} macOS AppleDouble files before Phase-to-Height")
    _run_phase_to_height_graph(
        gpt=gpt,
        ifg_dim=Path(args.ifg_dim),
        unw_hdr=Path(args.unw_hdr),
        dem_name=args.dem_name,
        out_tif=out_tif,
        pixel_spacing_m=args.pixel_spacing,
        workspace=workspace,
        extra_gpt_args=_gpt_extra_args(args),
    )
    print(f"DEM: {out_tif}")
    if workspace.is_dir():
        sp = _patch_pair_summary(workspace, dem_tif=out_tif)
        print(f"Summary: {sp}")


def cmd_run_gpt(args: argparse.Namespace) -> None:
    gpt = _resolve_gpt(args.gpt_executable)
    graph = Path(args.graph)
    if not graph.is_file():
        raise SystemExit(f"Нет файла graph: {graph}")
    rc = _run_gpt(gpt, graph, extra_args=_gpt_extra_args(args))
    raise SystemExit(rc)


# --------------------------------------------------------------------------- argparse


def _add_gpt_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--gpt-exec", dest="gpt_executable", default="", help="Полный путь к gpt (либо $SNAP_GPT)")
    p.add_argument("--gpt-cache", default="", help="SNAP GPT cache size, например 12G (передаётся как -c 12G).")
    p.add_argument("--gpt-threads", type=int, default=0, help="SNAP GPT parallelism, например 4 (передаётся как -q 4).")
    p.add_argument(
        "--snaphu-exec",
        dest="snaphu_executable",
        default="",
        help="Полный путь к snaphu; иначе $SNAPHU_EXEC или PATH",
    )
    p.add_argument(
        "--extra-gpt-args",
        nargs="*",
        default=[],
        help="Доп. аргументы gpt перед graph.xml (например -c 12G -q 4)",
    )


def _add_pair_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--region", type=str, default=DEFAULT_REGION, choices=sorted(REGIONS.keys()), help="Регион, с которым обязан пересекаться IFG/DEM.")
    p.add_argument("--subswath", default="auto", help="auto|IW1|IW2|IW3; auto перебирает IW1/IW2/IW3 до пересечения с регионом.")
    p.add_argument("--polarization", default="VV", help="VV|VH (по умолчанию VV)")
    p.add_argument("--first-burst", type=int, default=0, help="Первый burst (1-based) для TOPSAR-Split; 0 = SNAP auto/all.")
    p.add_argument("--last-burst", type=int, default=0, help="Последний burst (1-based) для TOPSAR-Split; 0 = SNAP auto/all.")
    p.add_argument("--dem-name", default="Copernicus 30m Global DEM", help="DEM для Back-Geocoding/Terrain-Correction")
    p.add_argument("--pixel-spacing", type=float, default=10.0, help="Шаг сетки в метрах для Terrain-Correction")
    p.add_argument(
        "--eap-correction",
        choices=["none", "master", "slave", "both"],
        default="none",
        help="Где применять EAP-Phase-Correction перед Back-Geocoding.",
    )
    p.add_argument("--skip-unwrap", action="store_true", help="Не запускать snaphu (для отладки)")
    p.add_argument("--skip-phase-to-height", action="store_true", help="Не запускать второй граф")
    p.add_argument("--allow-outside-region", action="store_true", help="Не останавливать прогон, если IFG не пересёк выбранный регион.")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="InSAR-пайплайн (SNAP + SNAPHU): doctor / run-pair / run-batch / …")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="Проверить gpt/snaphu и показать графы.")
    d.set_defaults(func=cmd_doctor)

    w = sub.add_parser("write-template", help="Минимальный graph с двумя Read.")
    w.add_argument("--master", type=str, required=True)
    w.add_argument("--slave", type=str, required=True)
    w.add_argument("--output", type=str, default="")
    w.set_defaults(func=cmd_write_template)

    wf = sub.add_parser("write-full-graph", help="Подставить параметры в полный TOPSAR/InSAR граф (без запуска).")
    wf.add_argument("--master", required=True)
    wf.add_argument("--slave", required=True)
    wf.add_argument("--export-dir", required=True)
    wf.add_argument("--ifg-dim", required=True)
    _add_pair_args(wf)
    wf.add_argument("--output", default="")
    wf.set_defaults(func=cmd_write_full_graph)

    rp = sub.add_parser("run-pair", help="Полный прогон: SNAP graph → SNAPHU → Phase-to-Height.")
    rp.add_argument("--master", required=True)
    rp.add_argument("--slave", required=True)
    _add_pair_args(rp)
    rp.add_argument("--out-dir", default="", help="Куда писать; пусто = outputs/<дата>/insar/pairs")
    _add_gpt_args(rp)
    rp.set_defaults(func=cmd_run_pair)

    rb = sub.add_parser("run-batch", help="Пакет пар из pairs.json (вывод dem.insar.pair_search).")
    rb.add_argument("--pairs", required=True, help="Путь к pairs.json")
    rb.add_argument("--slc-dir", default="", help="Каталог с локальными SLC (.zip/.SAFE); по умолчанию outputs/<дата>/data/raw/slc_runs")
    rb.add_argument("--limit", type=int, default=0, help="Сколько первых пар брать (0 = все)")
    _add_pair_args(rb)
    rb.add_argument("--out-dir", default="")
    _add_gpt_args(rb)
    rb.set_defaults(func=cmd_run_batch)

    su = sub.add_parser("snaphu-unwrap", help="Запустить snaphu в каталоге SnaphuExport.")
    su.add_argument("--export-dir", required=True)
    su.add_argument(
        "--snaphu-exec",
        dest="snaphu_executable",
        default="",
        help="Полный путь к snaphu; иначе $SNAPHU_EXEC или PATH",
    )
    su.set_defaults(func=cmd_snaphu_unwrap)

    ph = sub.add_parser("phase-to-height", help="Импорт развёрнутой фазы → DEM GeoTIFF (второй граф).")
    ph.add_argument("--ifg-dim", required=True)
    ph.add_argument("--unw-hdr", required=True)
    ph.add_argument("--dem-name", default="Copernicus 30m Global DEM")
    ph.add_argument("--pixel-spacing", type=float, default=10.0)
    ph.add_argument("--out-tif", default="")
    ph.add_argument("--workspace", default="")
    _add_gpt_args(ph)
    ph.set_defaults(func=cmd_phase_to_height)

    rg = sub.add_parser("run-gpt", help="Запустить gpt с готовым graph.xml")
    rg.add_argument("--graph", required=True)
    _add_gpt_args(rg)
    rg.set_defaults(func=cmd_run_gpt)

    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
