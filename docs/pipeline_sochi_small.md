# Пайплайн для `sochi_khosta_mzymta_small`

Регион по умолчанию в `src/dem/config.py`: узкий полигон между Хостой и Мзымтой (STAC `intersects`).

## 1. Эталонные открытые DEM

Два источника (COP30 + SRTM) + `reference_dem_manifest.json`:

```bash
export OPENTOPOGRAPHY_API_KEY="..."
python -m dem.ingest.reference_dem
# или явно:
python -m dem.ingest.reference_dem --region sochi_khosta_mzymta_small --sources cop30,srtm30
```

Тест без ключа:

```bash
python -m dem.ingest.reference_dem --demo
```

Список alias источников:

```bash
cd src && python -c "from dem.ingest.open_dem_sources import list_sources_table; print(list_sources_table())"
```

(Из корня репозитория: `python -c "from dem.ingest.open_dem_sources import list_sources_table; print(list_sources_table())"` при `pip install -e .`.)

## 2. SAR для этого региона (основной путь)

Sentinel-1 RTC на Planetary Computer (амплитуда VV/VH, GeoTIFF):

```bash
python -m dem.ingest.service stac download --region sochi_khosta_mzymta_small --month 2024-06 --limit 1
```

Список сцен:

```bash
python -m dem.ingest.service stac list --region sochi_khosta_mzymta_small --month 2024-06 --max-scenes 5
```

Интервал дат:

```bash
python -m dem.ingest.sar_rtc_stac download \
  --region sochi_khosta_mzymta_small \
  --date-from 2021-07-01 --date-to 2021-07-07 --limit 2
```

## 2b. SLC (ASF) — поиск и загрузка

```bash
python -m dem.ingest.sar_slc_download list --region sochi_khosta_mzymta_small --date-from 2024-06-01 --date-to 2024-06-30 --limit 10
python -m dem.ingest.sar_slc_download download --region sochi_khosta_mzymta_small --date-from 2024-06-01 --date-to 2024-06-30 --limit 1
python -m dem.insar.pair_search --region sochi_khosta_mzymta_small --date-from 2024-06-01 --date-to 2024-08-31
```

Для скачивания с ASF обычно нужна учётная запись NASA Earthdata (см. docstring в `sar_slc_download`).

## 3. Датасеты DagsHub / AWS (образцы)

- **Indigo Sentinel-1 RTC** — CONUS, не покрывают Сочи.

  ```bash
  python -m dem.ingest.service external indigo-sample
  ```

- **Capella Open Data**

  ```bash
  python -m dem.ingest.service external capella-sample --scan-max-keys 2000
  ```

## 4. InSAR (SLC + SNAP)

RTC не содержит фазу для классической интерферометрии. Нужны **SLC** и цепочка в **SNAP** (+ при необходимости **SNAPHU**).

```bash
python -m dem.insar.pipeline doctor
python -m dem.insar.pipeline write-template --master /path/Master.zip --slave /path/Slave.zip --output runs/insar/read_pair.xml
```

Дальше в SNAP Desktop допишите операторы TOPSAR / Back-Geocoding / Interferogram и при необходимости экспорт для SNAPHU.

## 5. Валидация DEM

После `reference_dem` укажите путь к одному из `data/processed/reference_dem/.../*.tif` или актуальному пути в `outputs/`:

```bash
python -m dem.viz.validate_dem data/processed/reference_dem/sochi_khosta_mzymta_small/sochi_khosta_mzymta_small_cop30_COP30_epsg3857.tif
```
