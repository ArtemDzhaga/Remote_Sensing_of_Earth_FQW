# Конфигурация YAML

Файлы:

| Файл | Назначение |
|------|------------|
| `regions.yaml` | Копия/зеркало регионов (источник истины по умолчанию — `dem.config.REGIONS`). |
| `sources.yaml` | Заготовка под alias DEM и эксперименты. |
| `train.yaml` | Заготовка гиперпараметров ML (`dem.ml`). |
| `storage.yaml` | Документированный профиль хранения без абсолютного пути конкретной машины. |

Загрузка YAML в рантайме пока не подключена к коду; правки синхронизируйте с `src/dem/config.py` до внедрения загрузчика.

## Предвыбор SLC-пар до SSD

До массовой загрузки ZIP на внешний диск используйте пакетный поиск кандидатов:

```bash
python -m dem.insar.pair_search \
  --region sochi_khosta_mzymta_small \
  --date-from 2024-06-01 \
  --date-to 2024-08-31 \
  --min-days 6 \
  --max-days 36 \
  --target-days 12 \
  --min-perp-baseline 80 \
  --max-perp-baseline 450
```

Точный каталог результата скрипт печатает в строке `Run dir:`; внутри него смотрите файл `pairs.md`.
Если `bperp_m` пустой, ASF не отдал перпендикулярный baseline; такую пару нельзя
считать финально выбранной для DEM без проверки baseline в SNAP.

Для подготовки manifest под скачивание без перекоса по годам используйте:

```bash
python -m dem.ingest.slc_budget_plan \
  --strategy yearly \
  --region sochi_khosta_mzymta_small \
  --date-from 2014-04-01 \
  --date-to 2026-05-01 \
  --year-from 2014 \
  --year-to 2026 \
  --scenes-per-year 10 \
  --pairs-per-year 30 \
  --budget-gb 200 \
  --enforce-budget \
  --min-days 6 \
  --max-days 36 \
  --out "${VKR_DATA_ROOT}/outputs/slc_yearly_2014_2026_10_per_year_manifest.json"
```

Затем скачивание:

```bash
python -m dem.ingest.sar_slc_download download \
  --from-manifest "${VKR_DATA_ROOT}/outputs/slc_yearly_2014_2026_10_per_year_manifest.json" \
  --auth auto
```

## Внешний SSD

Код уже поддерживает перенос тяжёлых артефактов через переменную окружения `VKR_DATA_ROOT`.
Перед тяжёлыми запусками задайте каталог данных:

```bash
export VKR_DATA_ROOT="${PWD}/.local_data"
```
