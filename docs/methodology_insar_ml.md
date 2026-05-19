# Методология MVP: InSAR + ML-коррекция DEM

## Цель

Цель MVP — получить воспроизводимый конвейер:

```text
Sentinel-1 SLC pair
→ SNAP InSAR processing
→ SNAPHU phase unwrapping
→ InSAR DEM
→ сравнение с COP30
→ ML-коррекция
→ corrected DEM
→ сравнение метрик до/после
```

ML-часть важна как итоговая исследовательская часть проекта, но ей нужен
физический baseline: исходный InSAR DEM, который модель будет улучшать.

## Почему нужны SLC, а не RTC

Для классической интерферометрии нужна фаза радиолокационного сигнала.

- `RTC/GRD` подходит для амплитудных признаков: яркость, текстура, VV/VH.
- `SLC` содержит комплексный сигнал: амплитуду и фазу.
- Интерферограмма строится именно из разности фаз двух SLC-съёмок.

Поэтому RTC можно использовать как дополнительный ML-признак, но не как замену
InSAR-пары.

## Что делает SNAP

SNAP GPT выполняет XML-граф обработки Sentinel-1.

Основные шаги:

1. `Read` — открыть два архива Sentinel-1 SLC.
2. `TOPSAR-Split` — выбрать subswath (`IW2`) и поляризацию (`VV`).
3. `Apply-Orbit-File` — применить точные орбиты.
4. `Back-Geocoding` — совместить slave-снимок с master-снимком по геометрии.
5. `Enhanced-Spectral-Diversity` — уточнить смещения между burst-ами TOPSAR.
6. `Interferogram` — построить комплексную интерферограмму.
7. `TOPSAR-Deburst` — склеить burst-структуру.
8. `GoldsteinPhaseFiltering` — уменьшить шум фазы.
9. `Write` — сохранить `ifg.dim` / `ifg.data`.
10. `SnaphuExport` — подготовить фазу и когерентность для SNAPHU.

Выход первого этапа:

- `ifg.dim`
- `ifg.data/*`
- `snaphu_export/.../Phase_*.snaphu.img`
- `snaphu_export/.../coh_*.snaphu.img`
- `snaphu_export/.../snaphu.conf`

## Что делает SNAPHU

Интерферометрическая фаза завёрнута в диапазон `[-π, π]`.
SNAPHU восстанавливает непрерывную фазу.

Вход SNAPHU:

- `Phase_*.snaphu.img` — завёрнутая фаза;
- `coh_*.snaphu.img` — когерентность;
- `snaphu.conf` — геометрия, baseline, размеры, тайлы, параметры алгоритма.

Выход SNAPHU:

- `UnwPhase_*.snaphu.img`
- `UnwPhase_*.snaphu.hdr`

Если есть только `.hdr`, но нет `.img`, unwrap не завершён.

## Phase-to-height

После развёртки фазы SNAP выполняет:

```text
SnaphuImport
→ PhaseToElevation
→ Terrain-Correction
→ GeoTIFF
```

Итоговый файл:

```text
dem_insar.tif
```

Он является baseline DEM, который сравнивается с COP30 и затем подаётся в ML.

## Что делает ML-модель

ML-модель не заменяет физический InSAR-пайплайн. Она учится корректировать его
ошибки относительно эталона.

Входные каналы MVP:

- InSAR DEM;
- slope от COP30 или reference DEM;
- при наличии: coherence;
- при наличии: SAR amplitude VV/VH;
- дополнительные геоморфологические признаки.

Цель:

```text
target = COP30 DEM
prediction = corrected DEM
```

Базовая архитектура:

- U-Net;
- encoder `resnet18`;
- `in_channels = число признаков`;
- `classes = 1`.

Fallback для smoke-тестов — компактная CNN.

## Почему U-Net

DEM-коррекция — это raster-to-raster задача:

```text
несколько входных карт → одна выходная карта высот
```

U-Net подходит, потому что:

- сохраняет пространственную структуру;
- объединяет локальные детали и более широкий контекст;
- хорошо подходит для dense prediction;
- быстро даёт MVP на небольшом датасете.

## Метрики

Основные метрики:

- `MAE` — средняя абсолютная ошибка;
- `RMSE` — чувствительна к крупным ошибкам;
- `bias` — среднее смещение;
- `PSNR` — качество реконструкции как отношение диапазона к ошибке;
- `MAE/RMSE на slope > 20°` — отдельная проверка сложных склонов.

MVP должен показать таблицу:

```text
baseline InSAR DEM vs COP30
corrected DEM vs COP30
```

Ключевой результат — снижение MAE/RMSE после ML-коррекции.

