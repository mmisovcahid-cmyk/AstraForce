# Scientific Harmonization Methodology: MODIS and VIIRS Hot Spots

NASA Space Apps Challenge 2026: **Harmonization of MODIS and VIIRS Hot Spots**  
Project: **Unified Fire Calendar (`fire-calendar`)**

---

## 1. Introduction and Core Dilemma

For more than two decades, the NASA Fire Information for Resource Management System (FIRMS) has provided near-real-time and archive active fire detections globally. However, analyzing long-term fire activity trends across the satellite record presents a fundamental sensor discontinuity:

1. **MODIS (Terra & Aqua, 2000–present):** 1 km spatial resolution at nadir.
2. **VIIRS (S-NPP, NOAA-20, NOAA-21, 2012–present):** 375 m spatial resolution with improved spatial sampling and higher thermal sensitivity.

Because VIIRS resolves fires roughly an order of magnitude smaller in physical footprint ($~375\text{ m}$ vs $1000\text{ m}$), raw hotspot counts increase dramatically after 2012. **Summing or comparing raw hotspot counts across sensors creates an artificial, unphysical surge in fire frequency.**

Conversely, attempting to "invent" small fires during the 2000–2011 MODIS-only era is ill-posed and mathematically unconstrained. Therefore, this project implements a rigorous, physically-grounded **detection-probability thinning framework** that standardizes the multi-decadal record into **MODIS-equivalent fire cell-days**.

---

## 2. Fundamental Spatial & Temporal Units

### 2.1 The Fire Cell-Day
- **Spatial Resolution:** Uber H3 Discrete Global Grid System at **Resolution 6** (average hexagon area $\approx 36.1\text{ km}^2$, edge length $\approx 3.23\text{ km}$).
- **Temporal Binning:** Keyed separately for Day ($D$) and Night ($N$) overpasses. "Both" represents the algebraic sum of Day and Night fire cell-days.
- **Local Solar Date Formulation (Rule 3):**
  Night overpasses near local midnight must not be split across two calendar days due to arbitrary UTC date boundaries. The local solar date is computed continuously from the acquisition longitude $\lambda$:
  $$t_{\text{local}} = t_{\text{UTC}} + \frac{\lambda}{15.0\text{ hours}}$$
  $$\text{Local Date} = \text{DatePart}(t_{\text{local}})$$

### 2.2 Independent Secondary FRP Metric
Fire Radiative Power (FRP, MW) measures instantaneous radiant heat output. In accordance with Scientific Rule 5, FRP from different sensors is never added or averaged for the same cell-day. Sensor-specific maximum FRP is preserved as an independent secondary intensity indicator.

---

## 3. Persistent Static Heat Source Masking

Active fire detection algorithms routinely trigger on industrial gas flaring (refineries, offshore platforms) and active volcanic vents. These non-vegetation thermal anomalies must be purged from natural fire statistics:

A cell $c$ is permanently masked if:
1. Any archive detection in $c$ carries an explicit non-vegetation type code:
   $$\text{type} \in \{1 \text{ (volcano)}, 2 \text{ (static land)}, 3 \text{ (offshore flaring)}\}$$
2. **Temporal Persistence:** Detections are present in $\ge 60\%$ of all calendar months across a span of $\ge 5$ years:
   $$\frac{N_{\text{active months}}}{12 \times \text{Years Span}} \ge 0.60 \quad \text{for } \text{Years Span} \ge 5$$

All masked cells are excluded from fire trend analysis and surfaced as an independent, transparent "Static Heat Sources" map layer.

---

## 4. Mathematical Harmonization Model

### 4.1 VIIRS-to-MODIS Detection Thinning Probability
For any fire cell-day where the reference VIIRS satellite detected active fire, we estimate the conditional probability $p_i$ that the MODIS union (Terra or Aqua) would have also detected it:

$$p_i = P(\text{MODIS Union} = 1 \mid \text{VIIRS Ref} = 1, \mathbf{x}_i)$$

The feature vector $\mathbf{x}_i$ captures physical fire magnitude, spatial density, and observational geometry:
$$\mathbf{x}_i = \left[ N_{\text{pixels}}, \ln(\text{FRP}_{\text{sum}} + 1), \text{FRP}_{\text{max}}, S_{\text{high\_conf}}, \bar{\theta}_{\text{scan}}, \mathbb{I}_{\text{day}}, \sin\left(\frac{2\pi m}{12}\right), \cos\left(\frac{2\pi m}{12}\right), \text{lat}, \bar{y}_{\text{parent\_res3}} \right]$$

- **Classifier:** Calibrated HistGradientBoosting / Logistic Regression with Isotonic Calibration.
- **Spatial Target Encoding:** Parent coarse H3 cell (resolution 3) target encoding regularized with global empirical shrinkage.

### 4.2 MODIS-Only Complement Term ($\alpha$)
Because of differing orbital tracks and fire intermittency, a small fraction of fire cell-days are detected by MODIS but missed by VIIRS. This is accounted for by the stratum-specific complement ratio $\alpha$:

$$\alpha_{\text{stratum}} = \frac{N(\text{MODIS}=1 \land \text{VIIRS}=0)}{N(\text{VIIRS}=1)}$$

To prevent noisy estimates in strata with few detections, $\alpha$ is stabilized via empirical Bayes shrinkage towards the global mean:
$$\alpha_{\text{stratum}}^{\text{shrunk}} = \frac{N_{\text{stratum}} \cdot \alpha_{\text{stratum}} + W \cdot \alpha_{\text{global}}}{N_{\text{stratum}} + W} \quad (W = 10.0)$$

### 4.3 Total Regional Expectation & Uncertainty Propagation
For any user-defined region and calendar day:
$$\hat{E} = \sum_{i \in \text{VIIRS}} p_i + \alpha_{\text{stratum}}^{\text{shrunk}} \cdot N_{\text{VIIRS}}$$

$$\text{Var}(\hat{E}) = \sum_{i \in \text{VIIRS}} p_i (1 - p_i) + \left(\hat{E} \cdot \sigma_{\text{residual}}\right)^2$$

Where $\sigma_{\text{residual}}$ is the standard deviation of monthly held-out log-ratio residuals. The 90% confidence interval $[p_{05}, p_{95}]$ is:
$$p_{05} = \max\left(0, \hat{E} - 1.645 \sqrt{\text{Var}(\hat{E})}\right)$$
$$p_{95} = \hat{E} + 1.645 \sqrt{\text{Var}(\hat{E})}$$

### 4.4 Terra-Only Pre-Aqua Bridge (2000 – Mid-2002)
Prior to the operational deployment of Aqua (July 2002), only Terra was operational. The Terra-to-Union scaling factor $R_{\text{bridge}}$ is learned from the first 3 years of concurrent dual-satellite operations (2002–2005):
$$R_{\text{bridge}} = \frac{N(\text{Terra} \cup \text{Aqua})}{N(\text{Terra})}$$

---

## 5. Satellite Sensor Milestones & Temporal Regime Status

| Temporal Regime | Date Range | Primary Sensor Basis | Status Flag |
| :--- | :--- | :--- | :--- |
| **Terra Pre-Aqua** | 2000-11-01 to 2002-07-03 | Terra $\times R_{\text{bridge}}$ | `modelled` |
| **Trusted MODIS Union** | 2002-07-04 to 2022-12-31 | Direct Terra $\cup$ Aqua observation | `observed` |
| **Post-MODIS Drift** | 2023-01-01 to Present | VIIRS reference thinned via $p_i$ | `modelled` |

---

## 6. Scientific References

1. **Giglio, L., Schroeder, W., & Justice, C. O. (2016).** The collection 6 MODIS active fire detection algorithm and fire products. *Remote Sensing of Environment*, 178, 31–41.
2. **Schroeder, W., Oliva, P., Giglio, L., & Csiszar, I. A. (2014).** The New VIIRS 375 m active fire detection product—Algorithm description and initial assessment. *Remote Sensing of Environment*, 143, 85–96.
3. **NASA FIRMS:** Earth Observing System Data and Information System (EOSDIS), NASA. *Fire Information for Resource Management System*. Available at: https://firms.modaps.eosdis.nasa.gov/
4. **Uber H3 Spatial Grid:** Discrete Global Grid System (DGGS) based on hierarchical hexagonal cells.
