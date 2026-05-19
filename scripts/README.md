# Project scripts

Текущий InSAR-маршрут для региона из `dem.config.DEFAULT_REGION`:

1. `insar_preflight_baselines.sh` — пересчитать baseline/SNAP coverage и создать `baseline_ok_pairs.json`.
2. `insar_run_baseline_ok_pairs.sh` — полный последовательный прогон пар, прошедших `baseline_preflight`.
3. `insar_validate_dem_against_reference.sh` — проверка одного `dem_insar.tif` против COP30.
4. `insar_validate_full_pairs.sh` — последовательная проверка всех `dem_insar.tif` в `full_pairs`.
5. `insar_stack_roi_dems.sh` — собрать mean/median DEM из нескольких ROI-пар и посчитать метрики.

Временные одноразовые скрипты для `latest pair`, `mvp validate` и ручного `SnaphuExport` удалены, чтобы не было двух конкурирующих способов запускать один и тот же пайплайн.
