# Scientific Limitations and Assumptions

NASA Space Apps 2026: **Unified Fire Calendar**

Transparency regarding satellite observation limits is fundamental to geospatial data integrity. The following known constraints should be considered when interpreting the harmonized record:

---

## 1. Cloud Cover and Obscuration (No Daily Cloud Masking)
Thermal infrared sensors (MODIS 4 µm / 11 µm and VIIRS 3.75 µm / 11 µm) cannot penetrate thick clouds, deep fog, or extremely dense pyrocumulonimbus smoke plumes.
- **Current Architecture:** Detections are evaluated conditional on cloud-free view. If an active fire occurs beneath heavy cloud cover, it is not detected by either sensor.
- **Future Roadmap:** Ingestion of MOD14A1 / MYD14A1 and VNP14A1 daily cloud mask products to compute explicit observation probabilities per cell-day ($P(\text{viewable})$).

## 2. Diurnal Cycle and the Morning Overpass Discontinuity
Terra has historically provided the sole morning (~10:30 AM local solar time) thermal overpass, capturing early-day fire ignitions.
- Aqua, S-NPP, NOAA-20, and NOAA-21 are all stationed in afternoon orbits (~13:00–13:30 local solar time).
- With Terra's equatorial crossing time drifting and eventual decommissioning, **there is currently no planned direct operational 10:30 AM constellation successor**.
- Consequently, morning fire activity during the post-MODIS era must be inferred statistically from the diurnal relationship learned during concurrent operational years.

## 3. Early MODIS Era (2000 – Mid-2002)
Prior to July 4, 2002, only the Terra satellite was operational. While our Terra-only bridge ratio $R_{\text{bridge}}$ scales Terra observations to union-equivalent levels using multi-year empirical ratios, values during this initial 20-month window carry slightly wider uncertainty intervals ($~15\%$ relative standard error) than the subsequent dual-MODIS period.

## 4. Land Cover Stratification
While the pipeline supports optional land cover classification if `data/landcover_h3.parquet` is present, the baseline model utilizes spatial parent cell target encoding (H3 resolution 3) and cyclic seasonal terms to capture biome differences. Fine-scale agricultural stubble burning vs forest canopy fires may experience modest residual variance differences.

## 5. Active Fire Cell-Days vs. Total Burned Area
The unified fire cell-day is a metric of **fire occurrence and persistence**, not a direct measurement of burned surface area in hectares. High-intensity fires that consume large areas within an hour and slow smoldering fires across multiple days exhibit different temporal cell-day signatures.
