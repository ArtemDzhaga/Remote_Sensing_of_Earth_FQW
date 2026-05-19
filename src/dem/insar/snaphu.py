# -*- coding: utf-8 -*-
"""
Запуск SNAPHU поверх результата ``SnaphuExport``.

После выполнения первого графа SNAP кладёт в ``targetFolder`` файлы:
- ``Phase_*.snaphu.img`` (обёрнутая фаза)
- ``Coh_*.snaphu.img`` (когерентность)
- ``snaphu.conf`` — текстовый конфиг с готовой командой ``snaphu …``

Эта обёртка читает ``snaphu.conf``, извлекает из него команду и запускает её.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class SnaphuRun:
    export_dir: Path
    cmd: list[str]
    out_unw_hdr: Path | None
    log_path: Path


def find_snaphu_conf(export_dir: Path) -> Path:
    """В подпапке ``Ifg_*`` либо в самом ``export_dir`` лежит ``snaphu.conf``."""

    direct = export_dir / "snaphu.conf"
    if direct.is_file():
        return direct
    matches = sorted(export_dir.glob("**/snaphu.conf"))
    if not matches:
        raise FileNotFoundError(f"snaphu.conf не найден внутри {export_dir}")
    return matches[0]


def _corrfile_name_from_conf(conf_path: Path) -> str | None:
    """Имя файла когерентности из ``CORRFILE`` (одна строка конфига SNAPHU)."""

    text = conf_path.read_text(encoding="utf-8", errors="ignore")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        if stripped.upper().startswith("CORRFILE"):
            parts = stripped.split(None, 1)
            if len(parts) >= 2:
                return parts[1].strip()
    return None


def _parse_envi_bs_grid(hdr_path: Path) -> tuple[int, int, int, np.dtype]:
    """samples, lines, bands и dtype float32 с учётом ENVI byte order (0=LE, 1=BE)."""

    text = hdr_path.read_text(encoding="utf-8", errors="ignore")
    samples = int(re.search(r"^\s*samples\s*=\s*(\d+)", text, re.MULTILINE | re.I).group(1))
    lines = int(re.search(r"^\s*lines\s*=\s*(\d+)", text, re.MULTILINE | re.I).group(1))
    bm = re.search(r"^\s*bands\s*=\s*(\d+)", text, re.MULTILINE | re.I)
    bands = int(bm.group(1)) if bm else 1
    bom = re.search(r"^\s*byte order\s*=\s*(\d+)", text, re.MULTILINE | re.I)
    byte_order = int(bom.group(1)) if bom else 0
    dt_m = re.search(r"^\s*data type\s*=\s*(\d+)", text, re.MULTILINE | re.I)
    dt_code = int(dt_m.group(1)) if dt_m else 4
    if dt_code != 4:
        raise ValueError(f"Поддержан только ENVI data type 4 (float32), в {hdr_path} указано {dt_code}")
    dt = np.dtype(">f4") if byte_order == 1 else np.dtype("<f4")
    return samples, lines, bands, dt


def _write_sanitized_coherence(*, src_img: Path, dst_img: Path, fill_value: float = 0.01) -> None:
    """Пишет копию coherence без NaN/Inf (SNAPHU иначе: «NaN or infinity found in correlation data»)."""

    hdr = src_img.with_suffix(".hdr")
    if not hdr.is_file():
        raise FileNotFoundError(f"Нет ENVI hdr рядом с {src_img}")
    samples, lines, bands, dt = _parse_envi_bs_grid(hdr)
    if bands != 1:
        raise ValueError(f"Ожидается одна полоса coherence, в {hdr} указано bands={bands}")
    expected = samples * lines * bands * dt.itemsize
    if src_img.stat().st_size < expected:
        raise RuntimeError(f"Файл {src_img} меньше ожидаемого размера {expected} байт")
    raw = np.fromfile(src_img, dtype=dt, count=samples * lines)
    arr = raw.reshape((lines, samples))
    # заполнитель как DEFAULTCORR в snaphu.conf — мягкая «низкая» когерентность
    a = np.nan_to_num(arr.astype(np.float64, copy=True), nan=fill_value, posinf=fill_value, neginf=fill_value)
    np.clip(a, 0.0, 1.0, out=a)
    # SNAPHU на типичной macOS/Linux читает FLOAT_DATA как native float32; ENVI hdr может быть BE,
    # из‑за чего запись «как в hdr» даёт мусор и «NaN or infinity found in correlation data».
    np.ascontiguousarray(a, dtype=np.float32).tofile(dst_img)


def ensure_corr_snaphu_img(*, export_dir: Path, conf_path: Path, work_dir: Path) -> None:
    """SNAPHU ждёт ``coh_*.snaphu.img`` рядом с ``snaphu.conf``; SNAP иногда оставляет coherence только в ``ifg.data``."""

    corr_name = _corrfile_name_from_conf(conf_path)
    if not corr_name:
        return
    dst = work_dir / corr_name
    pair_dir = export_dir.parent
    if corr_name.endswith(".snaphu.img"):
        src_name = corr_name[: -len(".snaphu.img")] + ".img"
    else:
        src_name = corr_name
    src = pair_dir / "ifg.data" / src_name
    if not src.is_file():
        raise FileNotFoundError(
            f"Для SNAPHU нужен CORRFILE `{corr_name}` в `{work_dir}`, но не найден источник `{src}`. "
            "Повторите SnaphuExport или скопируйте coherence из ifg.data вручную."
        )
    # всегда пересобираем из ifg.data: SNAP coherence часто содержит NaN за пределами покрытия
    _write_sanitized_coherence(src_img=src, dst_img=dst)


def parse_snaphu_command(conf_path: Path) -> list[str]:
    """Из ``snaphu.conf`` извлекает строку вида ``snaphu -f snaphu.conf <wrap.img> <cols>``."""

    text = conf_path.read_text(encoding="utf-8", errors="ignore")
    cmd_match = re.search(r"^#?\s*snaphu\s+([^\n\r]+)$", text, re.MULTILINE)
    if not cmd_match:
        raise RuntimeError(f"Команда snaphu не найдена в {conf_path}")
    args = cmd_match.group(1).strip()
    return ["snaphu", *args.split()]


def find_wrapped_phase_img(export_dir: Path) -> Path:
    cands = sorted(export_dir.glob("**/Phase_*.snaphu.img"))
    if not cands:
        raise FileNotFoundError(f"Phase_*.snaphu.img не найден в {export_dir}")
    return cands[0]


def expected_unwrapped_hdr(wrap_img: Path) -> Path:
    """SNAPHU кладёт UnwPhase_*.snaphu.hdr рядом с обёрткой."""

    name = wrap_img.name.replace("Phase_", "UnwPhase_").replace(".img", ".hdr")
    return wrap_img.with_name(name)


def expected_unwrapped_img(wrap_img: Path) -> Path:
    """SNAPHU кладёт UnwPhase_*.snaphu.img рядом с обёрткой."""

    name = wrap_img.name.replace("Phase_", "UnwPhase_")
    return wrap_img.with_name(name)


def resolve_snaphu_binary(snaphu_executable: str | None = None) -> str | None:
    """Путь к бинарю: аргумент → SNAPHU_EXEC (файл или каталог с snaphu) → PATH."""

    def from_spec(spec: str) -> str | None:
        p = Path(spec)
        if p.is_file():
            return str(p)
        if p.is_dir():
            cand = p / "snaphu"
            if cand.is_file():
                return str(cand)
        return None

    if snaphu_executable:
        hit = from_spec(snaphu_executable.strip())
        if hit:
            return hit
    env_s = os.environ.get("SNAPHU_EXEC", "").strip()
    if env_s:
        hit = from_spec(env_s)
        if hit:
            return hit
    bundled_candidates = [
        "snaphu",
        "/usr/local/bin/snaphu",
        "/opt/homebrew/bin/snaphu",
    ]
    for cand in bundled_candidates:
        hit = from_spec(cand)
        if hit:
            return hit
    return shutil.which("snaphu")


def reset_snaphu_workspace(work_dir: Path) -> None:
    """Убирает хвосты прошлых прогонов: без этого SNAPHU падает на ``Can't open file snaphu_tiles_…``."""

    if not work_dir.is_dir():
        return
    n = 0
    for p in sorted(work_dir.glob("snaphu_tiles_*")):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
            n += 1
    for p in work_dir.glob("UnwPhase_*.snaphu.img"):
        try:
            if p.is_file() and p.stat().st_size == 0:
                p.unlink()
                n += 1
        except OSError:
            pass
    if n:
        print(f"[snaphu] removed stale snaphu workspace artifacts in {work_dir} ({n} items)", flush=True)


def run_snaphu(export_dir: Path, *, snaphu_executable: str | None = None, log_name: str = "snaphu.log") -> SnaphuRun:
    """Запустить snaphu в каталоге экспорта; вернуть метаданные прогона."""

    snaphu_bin = resolve_snaphu_binary(snaphu_executable)
    if not snaphu_bin:
        raise SystemExit(
            "snaphu не найден. Задайте SNAPHU_EXEC, добавьте bin в PATH или укажите --snaphu-exec."
        )

    conf = find_snaphu_conf(export_dir)
    work_dir = conf.parent
    reset_snaphu_workspace(work_dir)
    ensure_corr_snaphu_img(export_dir=export_dir, conf_path=conf, work_dir=work_dir)
    cmd = parse_snaphu_command(conf)
    cmd[0] = snaphu_bin

    log_path = work_dir / log_name
    print(f"[snaphu] cwd={work_dir}")
    print(f"[snaphu] cmd={' '.join(cmd)}")
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"# cwd: {work_dir}\n# cmd: {' '.join(cmd)}\n\n")
        log.flush()
        rc = subprocess.call(cmd, cwd=str(work_dir), stdout=log, stderr=subprocess.STDOUT)
    if rc != 0:
        raise SystemExit(f"snaphu завершился с кодом {rc}; см. лог {log_path}")

    wrap = find_wrapped_phase_img(export_dir)
    unw_hdr = expected_unwrapped_hdr(wrap)
    unw_img = expected_unwrapped_img(wrap)
    if not unw_hdr.is_file() or not unw_img.is_file():
        raise SystemExit(
            f"snaphu не создал полный UnwPhase output; ожидались {unw_hdr} и {unw_img}. "
            f"См. лог {log_path}"
        )
    return SnaphuRun(export_dir=export_dir, cmd=cmd, out_unw_hdr=unw_hdr, log_path=log_path)
