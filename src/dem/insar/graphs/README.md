# SNAP XML graphs

В этой папке лежат **параметризуемые** графы SNAP для Sentinel-1 IW InSAR.
Подстановки делает Python (`dem.insar.pipeline`), плейсхолдеры — точные строки `__NAME__`.

## `s1_topsar_insar_snaphu_export.xml`

Цепочка от пары SLC до каталога SNAPHU-экспорта.

| Плейсхолдер | Что подставляется | Пример |
|---|---|---|
| `__MASTER__` | путь к master `.zip` / `manifest.safe` | `data/raw/slc_runs/.../S1A_..._.zip` |
| `__SLAVE__` | путь к slave `.zip` / `manifest.safe` | `data/raw/slc_runs/.../S1B_..._.zip` |
| `__SUBSWATH__` | подсвэт TOPSAR | `IW1` · `IW2` · `IW3` |
| `__POLARIZATION__` | поляризация | `VV` · `VH` |
| `__DEM_NAME__` | DEM для Back-Geocoding | `Copernicus 30m Global DEM` · `SRTM 1Sec HGT` |
| `__EXPORT_DIR__` | каталог под `SnaphuExport` | `outputs/<дата>/insar/pairs/<pair_id>/snaphu_export` |
| `__IFG_DIM__` | BEAM-DIMAP интерферограммы | `outputs/<дата>/insar/pairs/<pair_id>/ifg.dim` |

Операторы:
`Read → TOPSAR-Split → Apply-Orbit-File → Read → TOPSAR-Split → Apply-Orbit-File →
Back-Geocoding → Enhanced-Spectral-Diversity → Interferogram → TOPSAR-Deburst →
GoldsteinPhaseFiltering → Write (DIMAP) + SnaphuExport`.

## `s1_phase_to_height.xml`

Постобработка после `snaphu`: импорт развёрнутой фазы → высота → terrain correction → GeoTIFF.

| Плейсхолдер | Что подставляется | Пример |
|---|---|---|
| `__IFG_DIM__` | продукт интерферограммы из первого графа | `…/ifg.dim` |
| `__UNW_HDR__` | `UnwPhase_*.snaphu.hdr` после unwrap | `…/snaphu_export/.../UnwPhase_…snaphu.hdr` |
| `__DEM_NAME__` | DEM для Range-Doppler Terrain Correction | `Copernicus 30m Global DEM` |
| `__OUT_TIF__` | итоговый GeoTIFF DEM | `…/dem_insar.tif` |
| `__PIXEL_SPACING__` | шаг сетки в метрах | `10.0` |

Операторы:
`Read (ifg) + Read (UnwPhase) → SnaphuImport → PhaseToElevation → Terrain-Correction → Write (GeoTIFF)`.

## Как запустить

```bash
# проверить окружение
python -m dem.insar.pipeline doctor

# одна пара
python -m dem.insar.pipeline run-pair \
  --master path/to/M.zip --slave path/to/S.zip \
  --subswath IW2 --polarization VV \
  --dem-name "Copernicus 30m Global DEM" \
  --extra-gpt-args -c 12G -q 4

# пакет (вход — pairs.json от dem.insar.pair_search)
python -m dem.insar.pipeline run-batch \
  --pairs outputs/<дата>/insar/slc_pairs/.../pairs.json \
  --slc-dir outputs/<дата>/data/raw/slc_runs \
  --limit 5
```
