# Сравнение MVP DEM и итоговой DEM

## Исходные продукты

| Продукт | Описание | Путь к отчёту |
|---|---|---|
| MVP, первая пригодная InSAR-пара | ЦМР по одной паре `S1A_IW_SLC__1SDV_20141014T032349__VS__S1A_IW_SLC__1SDV_20141026T032349` | `${VKR_RUN_ROOT}/insar/full_pairs_roi/S1A_IW_SLC__1SDV_20141014T032349__VS__S1A_IW_SLC__1SDV_20141026T032349/quality_check/dem_vs_cop30_metrics/dem_comparison_metrics.md` |
| MVP, первый контрольный прогон | ЦМР по одной паре `S1A_IW_SLC__1SDV_20141003T151026__VS__S1A_IW_SLC__1SDV_20141108T151026`; пример неудачной пары | `${VKR_RUN_ROOT}/insar/full_pairs_roi/S1A_IW_SLC__1SDV_20141003T151026__VS__S1A_IW_SLC__1SDV_20141108T151026/quality_check/dem_vs_cop30_metrics/dem_comparison_metrics.md` |
| Итоговый продукт | `robust15` после ResNet18-U-Net и `clip_reference_min` | `${VKR_RUN_ROOT}/ml_corrected_stack/resnet18_unet_bs8_ep120_seed42_20260511_robust15/quality_check_clip_reference_min/dem_vs_cop30_metrics/dem_comparison_metrics.md` |
| Дополнительный калиброванный продукт | `robust15` после ResNet18-U-Net и `quantile_reference` | `${VKR_RUN_ROOT}/ml_corrected_stack/resnet18_unet_bs8_ep120_seed42_20260511_robust15/quality_check_quantile_reference/dem_vs_cop30_metrics/dem_comparison_metrics.md` |

## Таблица «было / стало»

| Вариант | Пиксели | MAE, м | RMSE, м | Bias, м | Улучшение MAE относительно пригодного MVP | Улучшение RMSE относительно пригодного MVP | Интерпретация |
|---|---:|---:|---:|---:|---:|---:|---|
| MVP: одна пригодная InSAR-пара | 290925 | 108.448 | 173.083 | -45.136 | 0.0% | 0.0% | Базовый результат без ML и без ансамбля |
| Raw stack 15 DEM, mean | 290925 | 115.399 | 150.249 | -110.256 | -6.4% | 13.2% | Простое среднее снижает RMSE, но ухудшает MAE и bias |
| Raw stack 15 DEM, median | 290925 | 144.472 | 197.854 | -136.231 | -33.2% | -14.3% | Медиана на этих данных хуже из-за систематического смещения |
| ML-corrected stack median, ранний вариант | 290925 | 91.802 | 136.590 | -61.091 | 15.3% | 21.1% | Первый ML-результат на стеке |
| Robust15 + ResNet18-U-Net | 290925 | 63.548 | 84.613 | -1.532 | 41.4% | 51.1% | Основной стек 15 ML-corrected DEM до физической правки нижнего хвоста |
| Robust15 + `clip_reference_min` | 290925 | 63.297 | 84.535 | -1.281 | 41.6% | 51.2% | Основной честный итоговый продукт |
| Robust15 + `quantile_reference` | 290925 | 54.502 | 76.285 | 0.448 | 49.7% | 55.9% | Калиброванный по COP30 продукт, не независимая ML-оценка |

## Контрольный пример плохой одной пары

| Вариант | Пиксели | MAE, м | RMSE, м | Bias, м | Комментарий |
|---|---:|---:|---:|---:|---|
| MVP: первый контрольный прогон | 290925 | 3029.330 | 3351.920 | -3026.437 | Пара была признана непригодной; такой результат показывает необходимость preflight и DEM-валидации |
| Robust15 + `clip_reference_min` | 290925 | 63.297 | 84.535 | -1.281 | Ошибка ниже, но сравнение с провальной парой не является основным научным сравнением |
