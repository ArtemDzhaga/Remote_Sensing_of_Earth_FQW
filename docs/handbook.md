# Справочник команд (пакет `dem`)

Все команды из корня репозитория, с активированным venv и установленным пакетом (`pip install -e .`):

```bash
source .venv/bin/activate
```

Регионы задаются ключами из `src/dem/config.py` (`REGIONS`).

### Куда пишутся результаты

По умолчанию рабочие скрипты берут корень данных из `VKR_DATA_ROOT`, а корень конкретного запуска из `VKR_RUN_ROOT`. Структура внутри запуска: `data/raw`, `data/processed`, `quality_report`, `progress_report`, `demo_runs`, `insar` и т.д. Старые деревья `data/...` подключены как запасной поиск.

**Важно:** команды в shell выполняйте **раздельно** (не склеивайте `pip install ...` и `export VAR=...` в одну строку — переменная может не установиться).

### Быстрый сценарий для показа (RTC + COP30)

```bash
export OPENTOPOGRAPHY_API_KEY=...
python -m dem.viz.fetch_rtc_bundle --region sochi_khosta_mzymta_small --month 2024-06 --limit 1
```

Дальше откройте `README.md` внутри пакета `outputs/<дата>/demo_runs/rtc_cop30/<регион>_<время>/`: там пути к RTC `image.tif`, к COP30 и к папке **`quality_report/`** с интерактивным **`*_3d.html`**, **`*_hist.png`**, `*_map.png`, `*_report.md`.

---

## Конфигурация и гео

| Модуль | Назначение |
|--------|------------|
| `dem.config` | Регионы (bbox/полигон), спутники, типы DEM для OpenTopography. |
| `dem.geo.utils` | `region_bbox`, `region_polygon` для STAC/пересечений. |
| `dem.ingest.open_dem_sources` | Справочник alias → типы DEM OpenTopography (`cop30`, `srtm30`, …). |

---

## DEM (OpenTopography)

| Команда | Назначение |
|---------|------------|
| `python -m dem.ingest.opentopography_client` | Один DEM по региону, репроекция, статистика. `--demo` без API. |
| `python -m dem.ingest.reference_dem` | Пакет эталонных слоёв (по умолчанию COP30+SRTM), `reference_dem_manifest.json`. |

---

## Оптика (RGB / NIR)

| Команда | Назначение |
|---------|------------|
| `python -m dem.ingest.optical_stac` | STAC (Planetary Computer): список/загрузка оптики (ранее `download_satellite` / `download_satellite_rgb`). |

---

## SAR: RTC (амплитуда VV/VH)

| Команда | Назначение |
|---------|------------|
| `python -m dem.ingest.sar_rtc_stac` | Sentinel-1 RTC из STAC: `list` / `download`, `--month` или `--date-from` / `--date-to`, `--limit`. |
| `python -m dem.ingest.service` | `stac …` — проброс в `sar_rtc_stac`; `external …` — образцы Indigo/Capella с AWS. |
| `python -m dem.viz.fetch_rtc_bundle` | **Демо одной командой:** COP30 + RTC + отчёт `validate_dem`; итог в `outputs/<дата>/demo_runs/rtc_cop30/.../README.md`. |

Произвольный интервал дат:

```bash
python -m dem.ingest.sar_rtc_stac download \
  --region sochi_khosta_mzymta_small \
  --date-from 2021-07-01 --date-to 2021-07-07 --limit 2
```

(`--limit` — синоним `--max-scenes`.)

---

## SAR: SLC (для InSAR)

| Модуль | Назначение |
|--------|------------|
| `dem.ingest.asf_slc` | Поиск сцен SLC через ASF API. |
| `python -m dem.ingest.sar_slc_download` | `list` / `download` `.zip` с ASF. Авторизация **NASA Earthdata** через `~/.netrc`, `EARTHDATA_TOKEN` или `--auth interactive`. |
| `python -m dem.insar.pair_search` | Поиск пар InSAR; JSON + MD в `${VKR_RUN_ROOT}/insar/slc_pairs/`. |

Текущий рабочий сценарий для первой пары Сочи:

```bash
export SNAP_GPT="$(command -v gpt)"
export SNAPHU_EXEC="$(command -v snaphu)"

# Один раз сохранить Earthdata-доступ в ~/.netrc без отображения пароля:
bash scripts/setup_earthdata_netrc.sh

python -m dem.insar.pipeline doctor

python -m dem.insar.pair_search \
  --region sochi_khosta_mzymta_small \
  --date-from 2024-06-01 \
  --date-to 2024-09-30

python -m dem.ingest.sar_slc_download download \
  --region sochi_khosta_mzymta_small \
  --date-from 2024-06-01 \
  --date-to 2024-06-20 \
  --limit 2 \
  --auth netrc
```

После появления двух `.zip` в каталоге `${VKR_RUN_ROOT}/data/raw/slc_runs/`
можно автоматически взять свежую пару из последней папки `slc_runs`:

```bash
bash scripts/insar_run_latest_pair.sh
```

---

## InSAR / визуализация прогресса

| Команда | Назначение |
|---------|------------|
| `python -m dem.insar.pipeline` | Проверка SNAP (`doctor`), шаблон graph, запуск `gpt`. |
| `python -m dem.insar.coherence_preview` | Proxy-согласованность двух **амплитудных** RTC (не истинная когерентность SLC). |
| `python -m dem.viz.progress` | SAR vs эталонный DEM: карты + scatter + корреляция. |
| `python -m dem.viz.demo_progress` | Один прогон: DEM-отчёт + SAR vs DEM + `summary.md` в `outputs/<дата>/demo_runs/...`. |

---

## Валидация DEM

| Команда | Назначение |
|---------|------------|
| `python -m dem.viz.validate_dem` | 2D/3D/гистограмма/HTML; по умолчанию `outputs/<дата>/quality_report/`; `--region`, `--period-label`. |
| `python -m dem viz compare-dems --reference <ref.tif> --candidate baseline=<a.tif>` | Таблица MAE/RMSE/PSNR и метрики на крутых склонах для отчёта “до/после”. |
| `bash scripts/mvp_validate_latest_dem.sh` | Автоматически найти свежий `dem_insar.tif`, COP30 reference и собрать quality/metrics отчёт для MVP. |

---

## Feature Engineering / ML

| Команда | Назначение |
|---------|------------|
| `python -m dem features slope <dem.tif>` | Рассчитать slope/aspect GeoTIFF из DEM. |
| `python -m dem features stack --channel <a.tif> --target <target.tif>` | Собрать нормализованные `.npz` патчи для обучения. Повторяйте `--channel` для каждого входного канала. |
| `python -m dem ml train --data-dir <dataset_v1>` | Обучить MVP-модель, сохранить `best.pt`, `history.json`, `learning_curves.png`. |
| `python -m dem ml infer --checkpoint <best.pt> --channel <a.tif> --out-tif <corrected.tif>` | Применить модель к GeoTIFF-каналам и записать corrected DEM. |

Пример после появления InSAR-DEM и дополнительных каналов:

```bash
python -m dem features slope data/processed/reference_dem/.../cop30.tif

python -m dem features stack \
  --channel outputs/<дата>/insar/pairs/<pair>/dem_insar.tif \
  --channel outputs/<дата>/features/cop30_slope_deg.tif \
  --target data/processed/reference_dem/.../cop30.tif \
  --target-mode residual \
  --base-channel-index 0 \
  --out-dir outputs/<дата>/data/processed/dataset_v1

python -m dem ml train \
  --data-dir outputs/<дата>/data/processed/dataset_v1 \
  --epochs 20 \
  --batch-size 4 \
  --device auto

python -m dem ml infer \
  --checkpoint outputs/<дата>/models/dem_mvp/best.pt \
  --channel outputs/<дата>/insar/pairs/<pair>/dem_insar.tif \
  --channel outputs/<дата>/features/cop30_slope_deg.tif \
  --normalization outputs/<дата>/data/processed/dataset_v1/normalization.json \
  --residual-base-channel 0 \
  --out-tif outputs/<дата>/models/dem_mvp/corrected.tif

CORRECTED_TIF=outputs/<дата>/models/dem_mvp/corrected.tif bash scripts/mvp_validate_latest_dem.sh
```

---

## Внешние образцы (AWS)

| Модуль | Назначение |
|--------|------------|
| `dem.ingest.samples` | `indigo-sample`, `capella-sample` (через `python -m dem.ingest.service external …`). |
