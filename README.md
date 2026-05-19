# DEM VKR: построение и коррекция ЦМР по Sentinel-1 InSAR

Проект реализует воспроизводимую цепочку построения цифровой модели рельефа
по Sentinel-1 SLC: от отбора интерферометрических пар до нейросетевой
коррекции остаточной ошибки и устойчивого объединения нескольких ЦМР.

В документации намеренно не используются абсолютные пути конкретного
компьютера. Все тяжёлые данные задаются через переменные окружения.

## Быстрый старт

Команды ниже выполняются из корня репозитория.

```bash
export PROJECT_ROOT="$(pwd)"
export VKR_DATA_ROOT="${VKR_DATA_ROOT:-${PROJECT_ROOT}/.local_data}"
export VKR_INSAR_RUN_DATE="${VKR_INSAR_RUN_DATE:-2026-05-08}"
export VKR_RUN_ROOT="${VKR_DATA_ROOT}/outputs/${VKR_INSAR_RUN_DATE}"
export PYTHONPATH="${PROJECT_ROOT}/src"
```

Установка пакета:

```bash
python -m pip install -e ".[ml]"
```

Проверка импортов и тестов:

```bash
python -m pytest -q
```

Проверка нейросетевой архитектуры:

```bash
python -c "import segmentation_models_pytorch as smp; print(smp.__version__)"
```

## Переменные окружения

| Переменная | Назначение |
|---|---|
| `PROJECT_ROOT` | Корень репозитория. Обычно задаётся как `$(pwd)` после перехода в проект. |
| `VKR_DATA_ROOT` | Внешнее или локальное хранилище тяжёлых данных. В Git не добавляется. |
| `VKR_INSAR_RUN_DATE` | Дата рабочего запуска, например `2026-05-08`. |
| `VKR_RUN_ROOT` | Корень конкретного запуска: `${VKR_DATA_ROOT}/outputs/${VKR_INSAR_RUN_DATE}`. |
| `PYTHONPATH` | Должен указывать на `${PROJECT_ROOT}/src`, если пакет не установлен через `pip install -e`. |
| `SNAP_HOME` | Опционально: путь к ESA SNAP, если `gpt` не найден в `PATH`. |
| `SNAPHU_EXEC` | Опционально: путь к исполняемому файлу SNAPHU, если он не найден автоматически. |

## Структура репозитория

```text
.
├── conf/
│   ├── regions.yaml        # конфигурация областей интереса
│   ├── sources.yaml        # источники DEM/SAR/SLC
│   ├── storage.yaml        # документированный профиль хранения без обязательного локального пути
│   └── train.yaml          # параметры обучения модели
├── data/
│   ├── raw/                # локальные сырые данные; игнорируются Git
│   ├── interim/            # промежуточные данные; игнорируются Git
│   └── processed/          # локальные обработанные данные; игнорируются Git
├── docs/
│   ├── architecture/       # архитектурные схемы и Structurizr DSL
│   ├── final_pipeline_sequence.puml
│   │                       # PlantUML-диаграмма полной цепочки обработки
│   ├── methodology_insar_ml.md
│   │                       # текстовое описание методики
│   ├── pipeline_report_index.md
│   │                       # индекс отчётных файлов рабочего запуска
│   └── project_tree_inventory.md
│                           # инвентаризация дерева проекта для рефакторинга
├── notebooks/              # исследовательские ноутбуки; тяжёлые выводы не хранить в Git
├── outputs/                # локальные результаты запусков; игнорируются Git
├── reports/                # сгенерированные отчёты; тяжёлые/персональные выпуски игнорируются Git
├── scripts/
│   ├── insar_env.sh
│   │                       # единая настройка путей для shell-скриптов
│   ├── insar_preflight_baselines.sh
│   │                       # предварительный отбор интерферометрических пар
│   ├── insar_run_baseline_ok_pairs.sh
│   │                       # построение InSAR-ЦМР по допущенным парам
│   ├── insar_validate_full_pairs.sh
│   │                       # контроль качества всех построенных ЦМР
│   ├── insar_stack_roi_dems.sh
│   │                       # объединение отобранных InSAR-ЦМР
│   ├── ml_prepare_insar_dataset.sh
│   │                       # подготовка набора фрагментов для обучения
│   ├── ml_train_insar_residual.sh
│   │                       # обучение ResNet18-U-Net
│   ├── ml_evaluate_insar_residual.sh
│   │                       # оценка модели на валидации/тесте
│   ├── ml_apply_insar_residual_members.sh
│   │                       # применение модели к нескольким ЦМР
│   ├── ml_stack_corrected_robust.sh
│   │                       # устойчивое объединение исправленных ЦМР
│   └── build_vkr_final_artifacts.py
│                           # сборка таблиц и рисунков для ВКР
├── src/
│   └── dem/
│       ├── config.py       # регионы и базовые настройки
│       ├── features/       # уклоны, фрагменты, сборка признаков
│       ├── geo/            # геометрия областей интереса
│       ├── ingest/         # загрузка DEM, SLC, STAC/ASF
│       ├── insar/          # отбор пар, SNAP/SNAPHU, InSAR-цепочка
│       ├── io/             # раскладка директорий и поиск данных
│       ├── ml/             # датасет, модель, обучение, оценка, инференс
│       ├── viz/            # визуализация и сравнение ЦМР
│       └── webapp/         # экспериментальный интерфейс
└── tests/                  # модульные тесты ключевых частей пайплайна
```

## Ожидаемая структура тяжёлых данных

Тяжёлые данные лежат вне Git, в `${VKR_DATA_ROOT}`:

```text
${VKR_DATA_ROOT}/
└── outputs/
    ├── slc_yearly_2014_2026_unified_manifest.json
    └── ${VKR_INSAR_RUN_DATE}/
        ├── data/
        │   ├── raw/slc_runs/                         # Sentinel-1 SLC ZIP/SAFE
        │   └── processed/ml_insar_residual_dataset/  # фрагменты для обучения
        ├── insar/
        │   ├── baseline_preflight/                   # отчёты отбора пар
        │   ├── full_pairs_roi/                       # результаты SNAP/SNAPHU по парам
        │   └── stack_roi_filtered/                   # стек отобранных InSAR-ЦМР
        ├── models/insar_residual_runs/               # веса модели и история обучения
        ├── ml_eval/                                  # оценка модели
        ├── ml_corrected_pairs/                       # 15 исправленных ЦМР
        └── ml_corrected_stack/                       # итоговый Robust15-продукт
```

Эталонная ЦМР Copernicus GLO-30 в рабочем контуре ищется скриптами через
`VKR_DATA_ROOT`, `data/processed/reference_dem/` и стандартные функции
`dem.io.layout`. Если путь отличается, его нужно передать переменной `REF_TIF`
в конкретный скрипт валидации.

## Основной пайплайн

### 1. Единый манифест SLC-сцен

```bash
scripts/slc_merge_manifests.sh
```

### 2. Предварительный отбор интерферометрических пар

```bash
scripts/insar_preflight_baselines.sh
```

Результаты:

```text
${VKR_RUN_ROOT}/insar/baseline_preflight/baseline_preflight.json
${VKR_RUN_ROOT}/insar/baseline_preflight/baseline_ok_pairs.json
```

### 3. Построение InSAR-ЦМР по отобранным парам

```bash
scripts/insar_run_baseline_ok_pairs.sh
```

Результаты:

```text
${VKR_RUN_ROOT}/insar/full_pairs_roi/
```

Внутри этой директории каждая подпапка соответствует одной интерферометрической
паре и содержит `dem_insar.tif`, `summary.md`, журналы SNAP/SNAPHU и отчёты
контроля качества.

### 4. Контроль качества всех InSAR-ЦМР

```bash
scripts/insar_validate_full_pairs.sh
```

### 5. Объединение отобранных InSAR-ЦМР

```bash
scripts/insar_stack_roi_dems.sh
```

Результаты:

```text
${VKR_RUN_ROOT}/insar/stack_roi_filtered/insar_stack_mean.tif
${VKR_RUN_ROOT}/insar/stack_roi_filtered/insar_stack_median.tif
${VKR_RUN_ROOT}/insar/stack_roi_filtered/insar_stack_metrics.md
```

## Нейросетевая часть

### 1. Подготовка набора для обучения

```bash
MAX_RMSE=200 \
MIN_PIXELS=50000 \
PATCH_SIZE=128 \
OVERLAP=32 \
scripts/ml_prepare_insar_dataset.sh
```

### 2. Обучение ResNet18-U-Net

```bash
RUN_ID=resnet18_unet_bs32_ep120_seed42 \
EPOCHS=120 \
BATCH_SIZE=32 \
SEED=42 \
ENCODER_NAME=resnet18 \
scripts/ml_train_insar_residual.sh
```

### 3. Оценка модели на тестовой выборке

```bash
RUN_DIR="${VKR_RUN_ROOT}/models/insar_residual_runs/resnet18_unet_bs32_ep120_seed42" \
SPLIT=test \
BATCH_SIZE=32 \
scripts/ml_evaluate_insar_residual.sh
```

### 4. Применение модели к 15 отобранным ЦМР

```bash
RUN_DIR="${VKR_RUN_ROOT}/models/insar_residual_runs/resnet18_unet_bs32_ep120_seed42" \
scripts/ml_apply_insar_residual_members.sh
```

### 5. Устойчивое объединение исправленных ЦМР

```bash
RUN_DIR="${VKR_RUN_ROOT}/models/insar_residual_runs/resnet18_unet_bs32_ep120_seed42" \
scripts/ml_stack_corrected_robust.sh
```

### 6. Постобработка итоговой ЦМР

```bash
IN_TIF="${VKR_RUN_ROOT}/ml_corrected_stack/resnet18_unet_bs32_ep120_seed42_robust15/ml_corrected_stack_robust15.tif" \
MODE=clip_reference_min \
scripts/ml_postprocess_dem.sh
```

Для калиброванного, но не полностью независимого продукта:

```bash
IN_TIF="${VKR_RUN_ROOT}/ml_corrected_stack/resnet18_unet_bs32_ep120_seed42_robust15/ml_corrected_stack_robust15.tif" \
MODE=quantile_reference \
scripts/ml_postprocess_dem.sh
```

## Сборка материалов для ВКР

```bash
MPLCONFIGDIR=/tmp/vkr_matplotlib \
python scripts/build_vkr_final_artifacts.py
```

Результат:

```text
reports/vkr_final_artifacts_2026-05-15/
```

Перед публикацией отчётов нужно проверить, что в них нет абсолютных путей
конкретной машины. Для проверки:

```bash
rg -n "/Users/|/Volumes/|Desktop/Output" README.md docs reports scripts src conf
```

## Что нельзя хранить в Git

В репозиторий не должны попадать:

- SLC ZIP/SAFE и распакованные Sentinel-1 продукты;
- GeoTIFF, SNAP `.dim/.data`, SNAPHU `.img/.hdr`;
- обучающие `.npz`, `.npy`, чекпойнты `.pt/.pth/.ckpt`;
- локальные `outputs/`, `data/raw/`, `data/processed/`, `models/`;
- виртуальные окружения и кэши Python;
- отчёты, содержащие абсолютные пути конкретной машины.

Текущая защита описана в `.gitignore`. Если тяжёлые файлы уже попадали в
историю Git, одного `.gitignore` недостаточно: историю нужно чистить отдельно
через `git filter-repo` или BFG Repo-Cleaner.
