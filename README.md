## Проект: Система построения и улучшения ЦМР

Этот репозиторий содержит экспериментальную систему обработки спутниковых данных и цифровых моделей рельефа (DEM) для построения и улучшения цифровой модели рельефа.

### Текущее состояние

- Инициализирован локальный git-репозиторий.
- Загрузка DEM с OpenTopography для **района рек Хоста и Мзымта (Сочи)** — горная местность с перепадом высот, реки, жилая застройка.
- Базовая предобработка: репроекция в выбранный EPSG, статистика по качеству.

### Быстрый старт (локально)

```bash
python3 -m venv .venv
source .venv/bin/activate  # macOS / Linux
pip install -r requirements.txt
```

Загрузка DEM по району Сочи (требуется API-ключ OpenTopography):

```bash
export OPENTOPOGRAPHY_API_KEY="ваш_ключ"
python src/opentopography_client.py
```

Тестовый запуск без API (искусственный DEM):

```bash
python src/opentopography_client.py --demo
```

Дополнительно: `--demtype SRTMGL1` (по умолчанию), `COP30`, `NASADEM`, `AW3D30`, `SRTMGL3`; `--epsg 3857`.

**Валидация и визуализация DEM (отчёт о качестве):**

```bash
python src/validate_dem.py data/processed/sochi_khosta_mzymta_dem_epsg3857.tif
```

Скрипт создаёт в `docs/quality_report/`:
- **2D-карту высот** (PNG)
- **3D-рендер** (PNG) — быстрый артефакт для отчётов/CI
- **интерактивную 3D-сцену** (HTML) — чтобы крутить/зумить рельеф
- гистограмму и Markdown-отчёт

Полезные параметры 3D:

```bash
python src/validate_dem.py data/processed/sochi_khosta_mzymta_dem_epsg3857.tif --view iso --z-exag 2.0
```

Если HTML не нужен:

```bash
python src/validate_dem.py data/processed/sochi_khosta_mzymta_dem_epsg3857.tif --no-html
```

Для проверки геопривязки откройте GeoTIFF в QGIS.

**Скачивание спутниковых снимков в `raw/` + метаданные (Sentinel-2 или Landsat):**

```bash
python src/download_satellite_rgb.py --help
python src/download_satellite_rgb.py download --help
python src/download_satellite_rgb.py download --region sochi_khosta_mzymta_wide --satellite sentinel2 --month 2025-09 --with-nir --limit 1
```

Скрипт кладёт в `data/raw/runs/<параметры>_<дата_до_секунд>/`:
- для каждой загруженной сцены — отдельная папка `scene_*`
- внутри `scene_*`:
  - `image.tif`
  - `image.md`
  - `image.stac.json`
  - `quicklook_rgb.png` (быстрый preview)

**Скачивание всепогодных SAR-снимков (Sentinel-1 RTC):**

```bash
python src/download_satellite_sra.py --help
python src/download_satellite_sra.py download --region sochi_khosta_mzymta_wide --month 2021-07 --limit 1
```

### Контекст проекта (дальнейшие этапы)

- **Этап 4:** синтетические данные (Blender/BlenderGIS — процедурный рельеф, пары «снимок–DEM»).
- **Этап 5:** ML-модели (DeepDEM, ImageToDEM, PyTorch), обучение, метрики (RMSE, MAE, PSNR), **3D-профили рельефа** для сравнения результатов.
- **Этап 6:** пайплайны (Prefect/GH Actions), Docker, REST API (FastAPI) и веб-визуализация (Folium/Dash).

Модуль визуализации рельефа (2D + 3D) на этапе 1 закладывает основу для 3D-сравнений на этапе 5.

### Структура (на первом этапе)

- `src/` — исходный код Python.
- `data/raw/` — необработанные данные (DEM, спутниковые снимки).
- `data/processed/` — предобработанные данные.
- `docs/quality_report/` — отчёты о качестве и визуализации DEM.
- `notebooks/` — исследовательские ноутбуки (при необходимости).

