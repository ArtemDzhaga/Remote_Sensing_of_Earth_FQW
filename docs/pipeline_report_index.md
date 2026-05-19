# Индекс отчётности пайплайна

Этот файл фиксирует, какие артефакты использовать в ВКР: где лежит отчёт, какой исходный файл подтверждает этап, и как трактовать результат.

Пути записаны через переменные окружения, чтобы документ не раскрывал локальную
структуру конкретного компьютера.

## Геопривязка и разрешение

- Эталонная ЦМР COP30: `${PROJECT_ROOT}/data/processed/reference_dem/sochi_khosta_mzymta_small/20260325T043705Z/sochi_khosta_mzymta_small_cop30_COP30_opentopo_dl20260325T043705Z_epsg3857.tif`
- Дополнительные эталонные ЦМР: `${PROJECT_ROOT}/data/processed/reference_dem/sochi_khosta_mzymta_small/`
- Рабочие InSAR/ML DEM перепроецированы на ту же сетку, что COP30: `EPSG:3857`, размер `431 x 675`, bounds `4443178.324,5369789.315,4459534.045,5395404.423`.
- Разрешение итоговой сетки: `37.948 x 37.948 м/пиксель`.
- Это не исходное разрешение Sentinel-1 SLC; это разрешение выходной сетки ЦМР после приведения к сетке COP30.

## Этапы

| Этап пайплайна | Отчётный файл | Пример исходного файла | Трактовка |
|---|---|---|---|
| Единый манифест SLC 2014-2026 | `${VKR_DATA_ROOT}/outputs/slc_yearly_2014_2026_unified_manifest.json` | `${VKR_RUN_ROOT}/data/raw/slc_runs/slc_sochi_khosta_mzymta_small_2014-04-01_2026-05-01_20260508_023404/manifest.json` | Подтверждает состав SLC-сцен, даты, орбиты и путь к ZIP-архиву. |
| Эталонная ЦМР | `${PROJECT_ROOT}/data/processed/reference_dem/sochi_khosta_mzymta_small/20260325T043705Z/reference_dem_manifest.json` | `${PROJECT_ROOT}/data/processed/reference_dem/sochi_khosta_mzymta_small/20260325T043705Z/sochi_khosta_mzymta_small_cop30_COP30_opentopo_dl20260325T043705Z_epsg3857.tif` | COP30 используется как эталон высот и как целевая сетка для сравнения. |
| Предварительная проверка пар | `${VKR_RUN_ROOT}/insar/baseline_preflight/baseline_preflight.md` | `${VKR_RUN_ROOT}/insar/baseline_preflight/baseline_preflight.json` | Полный список проверенных пар с базовой линией, временным интервалом и параметрами. |
| Отбор пригодных пар | `${VKR_RUN_ROOT}/insar/baseline_preflight/baseline_ok_pairs.md` | `${VKR_RUN_ROOT}/insar/baseline_preflight/baseline_ok_pairs.json` | Пары, допущенные к InSAR-обработке. |
| Обработка одной InSAR-пары | `${VKR_RUN_ROOT}/insar/full_pairs_roi/S1A_IW_SLC__1SDV_20141014T032349__VS__S1A_IW_SLC__1SDV_20141026T032349/summary.md` | `${VKR_RUN_ROOT}/insar/full_pairs_roi/S1A_IW_SLC__1SDV_20141014T032349__VS__S1A_IW_SLC__1SDV_20141026T032349/dem_insar.tif` | Пример результата одной пары: SNAP/SNAPHU, развёртка фазы, перевод фазы в высоту и ЦМР. |
| Контроль качества ЦМР по паре | `${VKR_RUN_ROOT}/insar/full_pairs_roi/S1A_IW_SLC__1SDV_20141014T032349__VS__S1A_IW_SLC__1SDV_20141026T032349/quality_check/dem_vs_cop30_metrics/dem_comparison_metrics.md` | `${VKR_RUN_ROOT}/insar/full_pairs_roi/S1A_IW_SLC__1SDV_20141014T032349__VS__S1A_IW_SLC__1SDV_20141026T032349/quality_check/dem_visual_quality/dem_insar_map.png` | Ошибка InSAR-ЦМР относительно COP30: MAE/RMSE/bias и визуальный контроль. |
| Исходный стек InSAR-ЦМР | `${VKR_RUN_ROOT}/insar/stack_roi_filtered/insar_stack_metrics.md` | `${VKR_RUN_ROOT}/insar/stack_roi_filtered/insar_stack_median.tif` | Базовый стек до нейросетевой коррекции. Используется как исходный уровень качества. |
| Набор данных для обучения | `${VKR_RUN_ROOT}/data/processed/ml_insar_residual_dataset/manifest.json` | `${VKR_RUN_ROOT}/data/processed/ml_insar_residual_dataset/normalization.json` | Разбиение на обучающую, валидационную и тестовую части, список фрагментов, нормировка входного канала. |
| Обучение модели | `${VKR_RUN_ROOT}/models/insar_residual_runs/resnet18_unet_bs8_ep120_seed42_20260511/history.json` | `${VKR_RUN_ROOT}/models/insar_residual_runs/resnet18_unet_bs8_ep120_seed42_20260511/best.pt` | История обучения ResNet18-U-Net и лучшие веса модели. |
| Оценка модели | `${VKR_RUN_ROOT}/ml_eval/resnet18_unet_bs8_ep120_seed42_20260511/ml_eval_test.md` | `${VKR_RUN_ROOT}/ml_eval/resnet18_unet_bs8_ep120_seed42_20260511/ml_eval_test.json` | Независимая тестовая оценка модели на фрагментах: до коррекции и после коррекции. |
| Коррекция 15 ЦМР моделью | `${VKR_RUN_ROOT}/ml_corrected_pairs/resnet18_unet_bs8_ep120_seed42_20260511/` | `${VKR_RUN_ROOT}/ml_corrected_pairs/resnet18_unet_bs8_ep120_seed42_20260511/S1A_IW_SLC__1SDV_20150205T151836__VS__S1A_IW_SLC__1SDV_20150217T151836/dem_ml_corrected.tif` | Модель применена к каждой из 15 ЦМР отдельно, без тайловых швов. |
| Итоговое объединение Robust15 | `${VKR_RUN_ROOT}/ml_corrected_stack/resnet18_unet_bs8_ep120_seed42_20260511_robust15/robust_stack_metrics.md` | `${VKR_RUN_ROOT}/ml_corrected_stack/resnet18_unet_bs8_ep120_seed42_20260511_robust15/ml_corrected_stack_robust15.tif` | Все 15 ЦМР участвуют в устойчивом взвешенном объединении; вес зависит от RMSE и динамического диапазона, затем применяется поправка среднего смещения. |
| Диаграмма PlantUML | `${PROJECT_ROOT}/docs/final_pipeline_sequence.puml` | `${PROJECT_ROOT}/docs/final_pipeline_sequence.puml` | Диаграмма полного пайплайна для вставки в документацию. |

## Текущий основной итог

- Основной продукт по 15 ЦМР: `${VKR_RUN_ROOT}/ml_corrected_stack/resnet18_unet_bs8_ep120_seed42_20260511_robust15/ml_corrected_stack_robust15.tif`
- Отчёт: `${VKR_RUN_ROOT}/ml_corrected_stack/resnet18_unet_bs8_ep120_seed42_20260511_robust15/robust_stack_metrics.md`
- Метрики: `MAE=63.548 м`, `RMSE=84.613 м`, `bias=-1.532 м`.
- Важно: этот итоговый стек калиброван по COP30. Его можно использовать как итоговый демонстрационный продукт качества, но независимое качество модели надо показывать по `ml_eval_test.md`.
