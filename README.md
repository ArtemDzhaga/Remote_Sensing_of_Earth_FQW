## Проект: Система построения и улучшения ЦМР

Этот репозиторий содержит экспериментальную систему обработки спутниковых данных и цифровых моделей рельефа (DEM) для построения и улучшения цифровой модели рельефа.

### Текущее состояние

-Done- Инициализирован локальный git-репозиторий.<br>
-Done- Сделаны скрипты для скачивания RGB и SRA снимков с ряда спутников:<br>
-------1. Создан CLI для указанных скриптов<br>
-------2. Можно подсчитать количество существующих сцен по области за указанный период с помощью алиаса "list"<br>
-------3. Можно скачать изображения с заданными CLI-параметрами с помощью алиаса "download"<br>
-WIP-  Загрузка DEM с OpenTopography для **района рек Хоста и Мзымта (Сочи)** — горная местность с перепадом высот, реки, жилая застройка.<br>
-WIP-  Базовая предобработка: репроекция в выбранный EPSG, статистика по качеству.

### Быстрый старт (локально)

```bash
python3 -m venv .venv
source .venv/bin/activate  # macOS / Linux
pip install -r requirements.txt
```

**Скачивание спутниковых снимков в `raw/` + метаданные (Sentinel-2 или Landsat):**

```bash
python src/download_satellite_rgb.py --help
python src/download_satellite_rgb.py download --help
python src/download_satellite_rgb.py download --region sochi_khosta_mzymta_small --satellite sentinel2 --month 2025-09 --with-nir --limit 1
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
python src/download_satellite_sra.py download --region sochi_khosta_mzymta_small --month 2021-07 --limit 1
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

