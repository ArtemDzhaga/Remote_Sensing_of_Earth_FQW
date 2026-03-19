# -*- coding: utf-8 -*-
"""
Валидация DEM: проверка качества, статистика, визуализация и автоматический отчёт.
Этап 1 — визуальная проверка предобработанных данных, 2D/3D модель рельефа,
отсутствие NaN, корректность геопривязки. 3D-визуализация закладывает основу
для этапа 5 (3D-профили рельефа при оценке моделей).
"""
import argparse
import sys
from pathlib import Path
from datetime import datetime

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import numpy as np
import rasterio
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:
    import pyvista as pv
    PYVISTA_AVAILABLE = True
except ImportError:
    PYVISTA_AVAILABLE = False

# Для сохранения подписей на русском
plt.rcParams["font.family"] = ["DejaVu Sans", "sans-serif"]


def dem_stats(path: Path):
    """Читает DEM, возвращает массив (float), статистику и метаданные."""
    with rasterio.open(path) as src:
        data = src.read(1, masked=True)
        arr_float = np.ma.filled(data.astype(np.float64), np.nan)
        valid = arr_float[~np.isnan(arr_float)]
        if valid.size == 0:
            stats = (float("nan"),) * 5
        else:
            stats = (
                float(np.nanmin(arr_float)),
                float(np.nanmax(arr_float)),
                float(np.nanmean(arr_float)),
                float(np.nanstd(arr_float)),
                float(np.mean(np.isnan(arr_float))),
            )
        meta = {
            "crs": str(src.crs),
            "bounds": src.bounds,
            "width": src.width,
            "height": src.height,
            "transform": src.transform,
            "nodata": src.nodata,
        }
        return arr_float, stats, meta


def plot_dem_map(arr: np.ndarray, out_path: Path, title: str = "DEM") -> None:
    """Карта высот (2D), сохранение в PNG."""
    fig, ax = plt.subplots(1, 1, figsize=(10, 8))
    vmin, vmax = np.nanpercentile(arr, [2, 98])
    im = ax.imshow(arr, cmap="terrain", vmin=vmin, vmax=vmax, aspect="auto")
    ax.set_title(title)
    plt.colorbar(im, ax=ax, label="Высота (м)")
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()


def plot_dem_histogram(arr: np.ndarray, out_path: Path, title: str = "Распределение высот") -> None:
    """Гистограмма высот."""
    valid = arr[~np.isnan(arr)]
    if valid.size == 0:
        return
    fig, ax = plt.subplots(1, 1, figsize=(8, 4))
    ax.hist(valid.ravel(), bins=min(100, max(20, int(np.sqrt(valid.size) / 10))), color="steelblue", edgecolor="white", alpha=0.8)
    ax.set_xlabel("Высота (м)")
    ax.set_ylabel("Количество пикселей")
    ax.set_title(title)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()


def plot_dem_3d(
    arr: np.ndarray,
    transform: "rasterio.Affine",
    out_png_path: Path,
    title: str = "3D модель рельефа",
    subsample: int = 4,
    z_exaggeration: float = 1.0,
    view: str = "iso",
    out_html_path: Path | None = None,
) -> None:
    """
    Строит 3D-поверхность рельефа (модуль визуализации рельефа из архитектуры).
    - PNG: быстрый артефакт для отчёта/CI.
    - HTML (опционально): интерактивный viewer (крутить/зумить) для реальной проверки
      и для этапа 5 (3D-профили/сравнения).
    """
    if not PYVISTA_AVAILABLE:
        return
    # Уменьшаем разрешение для быстрой отрисовки и читаемого ракурса
    step = max(1, subsample)
    arr_s = arr[::step, ::step].copy()
    nans = np.isnan(arr_s)
    if nans.any():
        arr_s[nans] = np.nanmin(arr_s[~nans]) if np.any(~nans) else 0.0
    rows, cols = arr_s.shape
    t = transform
    cc, rr = np.meshgrid(np.arange(cols) * step, np.arange(rows) * step)
    xx = t.a * cc + t.b * rr + t.c
    yy = t.d * cc + t.e * rr + t.f
    zz = arr_s
    # PyVista StructuredGrid: 3D массивы формы (nx, ny, 1)
    x3 = xx.reshape(rows, cols, 1)
    y3 = yy.reshape(rows, cols, 1)
    z3 = zz.reshape(rows, cols, 1)
    grid = pv.StructuredGrid(x3, y3, z3)
    # Vertical exaggeration (часто полезно, если XY в метрах и Z «плоский» визуально)
    grid.points[:, 2] *= float(z_exaggeration)
    plotter = pv.Plotter(off_screen=True)
    plotter.add_mesh(grid, scalars=zz.ravel(), cmap="terrain", show_scalar_bar=True, scalar_bar_args={"title": "Высота (м)"})
    plotter.add_title(title, font_size=10)
    if view == "top":
        plotter.view_xy()
    elif view == "front":
        plotter.view_xz()
    elif view == "side":
        plotter.view_yz()
    else:
        plotter.view_isometric()
    plotter.screenshot(str(out_png_path))
    if out_html_path is not None:
        try:
            plotter.export_html(str(out_html_path))
        except ImportError as e:
            # PyVista export_html требует trame/trame-vtk; PNG всё равно будет сохранён
            print(f"HTML 3D не создан: {e}")
    plotter.close()


def write_report(
    path: Path,
    stats: tuple,
    meta: dict,
    fig_map: Path | None,
    fig_hist: Path | None,
    fig_3d: Path | None,
    fig_3d_html: Path | None,
    report_path: Path,
) -> None:
    """Пишет Markdown-отчёт о качестве DEM."""
    vmin, vmax, mean, std, nan_frac = stats
    lines = [
        f"# Отчёт о качестве DEM: {path.name}",
        "",
        f"**Дата проверки:** {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Метаданные",
        f"- **CRS:** {meta['crs']}",
        f"- **Размер:** {meta['width']} × {meta['height']}",
        f"- **Границы (bounds):** {meta['bounds']}",
        f"- **NoData в источнике:** {meta['nodata']}",
        "",
        "## Статистика высот",
        f"- min: {vmin:.3f} м",
        f"- max: {vmax:.3f} м",
        f"- mean: {mean:.3f} м",
        f"- std: {std:.3f} м",
        f"- доля пропусков (NaN/NoData): {nan_frac:.6%}",
        "",
        "## Визуализация",
    ]
    if fig_map and fig_map.exists():
        lines.append(f"- Карта высот (2D): [{fig_map.name}]({fig_map.name})")
    if fig_3d and fig_3d.exists():
        lines.append(f"- **3D модель рельефа:** [{fig_3d.name}]({fig_3d.name})")
    if fig_3d_html and fig_3d_html.exists():
        lines.append(f"- **Интерактивная 3D сцена (HTML):** [{fig_3d_html.name}]({fig_3d_html.name})")
    if fig_hist and fig_hist.exists():
        lines.append(f"- Гистограмма высот: [{fig_hist.name}]({fig_hist.name})")
    lines.extend(["", "## Вывод"])
    if nan_frac == 0:
        lines.append("- Пропусков нет — данные пригодны для дальнейшей обработки.")
    else:
        lines.append(f"- Обнаружены пропуски ({nan_frac:.2%}) — при использовании учитывать маску.")
    lines.append("- Геопривязка задана (CRS и transform присутствуют); для визуальной проверки в QGIS откройте GeoTIFF.")
    report_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Валидация DEM: статистика, визуализация, отчёт о качестве.")
    parser.add_argument("dem", type=str, nargs="?", default="data/processed/sochi_khosta_mzymta_dem_epsg3857.tif", help="Путь к GeoTIFF DEM")
    parser.add_argument("--out-dir", type=str, default="docs/quality_report", help="Каталог для отчёта и рисунков")
    parser.add_argument("--subsample", type=int, default=4, help="Субдискретизация для 3D (1=без уменьшения, 4=каждый 4-й пиксель)")
    parser.add_argument("--z-exag", type=float, default=1.5, help="Vertical exaggeration для 3D (например 1.5..5.0)")
    parser.add_argument("--view", type=str, default="iso", choices=["iso", "top", "front", "side"], help="Ракурс 3D (iso/top/front/side)")
    parser.add_argument("--no-html", action="store_true", help="Не генерировать интерактивный HTML (только PNG)")
    args = parser.parse_args()

    path = Path(args.dem)
    if not path.is_file():
        print(f"Ошибка: файл не найден: {path}")
        sys.exit(1)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = path.stem

    print(f"Чтение DEM: {path}")
    arr, stats, meta = dem_stats(path)
    vmin, vmax, mean, std, nan_frac = stats
    print(f"  min={vmin:.2f} max={vmax:.2f} mean={mean:.2f} std={std:.2f} NaN%={nan_frac:.4%}")

    fig_map = out_dir / f"{base}_map.png"
    fig_hist = out_dir / f"{base}_hist.png"
    fig_3d = out_dir / f"{base}_3d.png"
    fig_3d_html = out_dir / f"{base}_3d.html"
    report_path = out_dir / f"{base}_report.md"

    print(f"Сохранение карты высот (2D): {fig_map}")
    plot_dem_map(arr, fig_map, title=f"DEM: {path.name}")
    if PYVISTA_AVAILABLE:
        print(f"Сохранение 3D модели рельефа: {fig_3d}")
        plot_dem_3d(
            arr,
            meta["transform"],
            fig_3d,
            title=f"3D рельеф: {path.name}",
            subsample=args.subsample,
            z_exaggeration=args.z_exag,
            view=args.view,
            out_html_path=None if args.no_html else fig_3d_html,
        )
    else:
        fig_3d = None
        fig_3d_html = None
        print("PyVista не установлен — 3D визуализация пропущена (pip install pyvista).")
    print(f"Сохранение гистограммы: {fig_hist}")
    plot_dem_histogram(arr, fig_hist, title=f"Распределение высот: {path.name}")
    print(f"Сохранение отчёта: {report_path}")
    write_report(path, stats, meta, fig_map, fig_hist, fig_3d, fig_3d_html, report_path)

    print("Готово. Для детальной проверки геопривязки откройте GeoTIFF в QGIS.")


if __name__ == "__main__":
    main()
