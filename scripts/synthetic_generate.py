"""
Synthetic Data Generator for NASA FIRMS Active Fire Detections.

Generates realistic MODIS (Terra/Aqua) and VIIRS (S-NPP/NOAA-20/NOAA-21) active fire datasets
adhering to real FIRMS CSV headers, physical detection characteristics (Giglio 2016, Schroeder 2014),
seasonal dynamics in Azerbaijan, and industrial flaring sources for static mask validation.
"""

from __future__ import annotations

import logging
import math
import random
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def get_project_root() -> Path:
    return Path(__file__).resolve().parent.parent

def generate_synthetic_firms(
    output_dir: Optional[str] = None,
    start_year: int = 2000,
    end_year: int = 2024,
    random_seed: int = 42,
) -> Dict[str, str]:
    """
    Generate synthetic FIRMS CSV archives for Azerbaijan (bbox: 44.7, 38.3, 50.7, 42.0).
    Produces CSV files with authentic FIRMS column names and formats:
    - modis_terra_2000_2024.csv
    - modis_aqua_2002_2024.csv
    - viirs_snpp_2012_2024.csv
    - viirs_noaa20_2018_2024.csv
    - viirs_noaa21_2023_2024.csv
    """
    np.random.seed(random_seed)
    random.seed(random_seed)
    if output_dir is None:
        out_path = get_project_root() / "data/raw"
    else:
        out_path = Path(output_dir)
        if not out_path.is_absolute():
            out_path = get_project_root() / out_path
    out_path.mkdir(parents=True, exist_ok=True)

    # Static flaring sites in Azerbaijan (Caspian offshore oil fields & Absheron industrial)
    # These sites will burn year-round to test Phase 2 static mask
    static_flare_sites = [
        {"lat": 40.35, "lon": 50.25, "type": 2, "name": "Bibiheybat/Absheron Industrial"},
        {"lat": 40.20, "lon": 50.60, "type": 3, "name": "Chirag Offshore Platform"},
        {"lat": 40.15, "lon": 50.80, "type": 3, "name": "Gunashli Deepwater"},
        {"lat": 40.05, "lon": 50.55, "type": 3, "name": "Shah Deniz Alpha"},
        {"lat": 40.45, "lon": 49.85, "type": 2, "name": "Sumgayit Petrochemical"},
    ]

    # Sensor specifications: (name, start_date, overpass_hours_day, overpass_hours_night)
    satellites = {
        "MODIS_Terra": {"sensor": "MODIS", "sat": "Terra", "start": date(2000, 11, 1), "day_h": 10.5, "night_h": 22.5},
        "MODIS_Aqua": {"sensor": "MODIS", "sat": "Aqua", "start": date(2002, 7, 4), "day_h": 13.5, "night_h": 1.5},
        "VIIRS_SNPP": {"sensor": "VIIRS", "sat": "N", "start": date(2012, 1, 20), "day_h": 13.3, "night_h": 1.3},
        "VIIRS_NOAA20": {"sensor": "VIIRS", "sat": "1", "start": date(2018, 1, 1), "day_h": 12.8, "night_h": 0.8},
        "VIIRS_NOAA21": {"sensor": "VIIRS", "sat": "2", "start": date(2023, 1, 1), "day_h": 13.0, "night_h": 1.0},
    }

    # Generate dates
    cur_date = date(start_year, 1, 1)
    end_date = date(end_year, 12, 31)

    # Store synthetic records per satellite key
    data_by_sat: Dict[str, List[dict]] = {k: [] for k in satellites}

    logger.info(f"Generating synthetic fire events from {cur_date} to {end_date}...")

    # Iterate day by day
    while cur_date <= end_date:
        doy = cur_date.timetuple().tm_yday
        month = cur_date.month

        # Seasonal burning cycle in Azerbaijan (peak July/August, minor spring peak April/May)
        # Baseline fire count follows sinusoidal envelope + random Poisson
        seasonal_intensity = (
            0.15
            + 0.85 * math.exp(-((doy - 215) ** 2) / (2 * (30 ** 2))) # Summer peak around Aug 3
            + 0.35 * math.exp(-((doy - 120) ** 2) / (2 * (20 ** 2))) # Spring agriculture around May 1
        )

        # Number of true fire events across Azerbaijan today
        n_events = np.random.poisson(lam=seasonal_intensity * 12.0)

        # Generate true physical fire events
        events = []
        for _ in range(n_events):
            # Spatial distribution: Lowland agricultural areas (Kur-Araz) or Southern foothills
            if random.random() < 0.70:
                # Kur-Araz plain: lat 39.5-40.8, lon 47.0-49.2
                flat = np.random.uniform(39.5, 40.8)
                flon = np.random.uniform(47.0, 49.2)
            else:
                # Foothills / Greater Caucasus slope: lat 40.8-41.5, lon 47.5-49.0
                flat = np.random.uniform(40.8, 41.5)
                flon = np.random.uniform(47.5, 49.0)

            # Fire size / Fire Radiative Power (MW) follows log-normal distribution
            # Small fires: 1-10 MW; medium: 10-40 MW; large: 50-250 MW
            true_frp = float(np.random.lognormal(mean=2.2, sigma=0.85))
            events.append((flat, flon, true_frp))

        # Also add persistent static flares (active ~90% of days)
        for flare in static_flare_sites:
            if random.random() < 0.90:
                flare_frp = float(np.random.uniform(25.0, 70.0))
                events.append((flare["lat"], flare["lon"], flare_frp, flare["type"]))

        # Check detection by each operational satellite today
        for sat_key, sat_info in satellites.items():
            if cur_date < sat_info["start"]:
                continue

            # Day and night overpasses
            for dn in ["D", "N"]:
                base_hour = sat_info["day_h"] if dn == "D" else sat_info["night_h"]

                for ev in events:
                    if len(ev) == 4:
                        flat, flon, true_frp, ev_type = ev
                    else:
                        flat, flon, true_frp = ev
                        ev_type = 0 # Vegetation fire

                    # Physical detection probability:
                    # VIIRS 375m has higher detection capability than MODIS 1km for small fires
                    # Schroeder et al. (2014) & Giglio et al. (2016)
                    if sat_info["sensor"] == "VIIRS":
                        # VIIRS 375m resolves down to ~2-3 MW
                        p_detect = 1.0 - math.exp(-0.35 * true_frp)
                    else:
                        # MODIS 1km requires larger FRP, detection probability rises slowly
                        # Thinning phenomenon: MODIS only detects ~35-50% of VIIRS hot spots
                        p_detect = 1.0 - math.exp(-0.06 * true_frp)

                    # Night overpasses slightly better contrast
                    if dn == "N":
                        p_detect = min(1.0, p_detect * 1.1)

                    if random.random() > p_detect:
                        continue # Fire missed by this sensor

                    # Satellite scan / track geometry
                    scan = round(float(np.random.uniform(1.0, 2.5 if sat_info["sensor"] == "MODIS" else 1.8)), 1)
                    track = round(float(np.random.uniform(1.0, 1.8 if sat_info["sensor"] == "MODIS" else 1.4)), 1)

                    # Overpass time with slight scan jitter
                    minute_offset = random.randint(-15, 15)
                    acq_minute = int((base_hour * 60 + minute_offset) % 1440)
                    acq_time_str = f"{acq_minute // 60:02d}{acq_minute % 60:02d}"

                    # FRP observed with sensor measurement noise
                    obs_frp = round(max(0.5, true_frp * float(np.random.normal(1.0, 0.15))), 1)

                    # Construct record according to sensor schema
                    if sat_info["sensor"] == "MODIS":
                        # MODIS archive headers
                        # latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_t31,frp,daynight,type
                        conf = int(min(100, max(15, 25 + 50 * (1 - math.exp(-0.05 * true_frp)) + random.randint(0, 25))))
                        b31 = round(285.0 + random.uniform(-5, 15), 1)
                        b_val = round(b31 + min(150.0, obs_frp * 1.5), 1)
                        row = {
                            "latitude": round(flat + np.random.normal(0, 0.003), 4),
                            "longitude": round(flon + np.random.normal(0, 0.003), 4),
                            "brightness": b_val,
                            "scan": scan,
                            "track": track,
                            "acq_date": cur_date.strftime("%Y-%m-%d"),
                            "acq_time": acq_time_str,
                            "satellite": sat_info["sat"],
                            "instrument": "MODIS",
                            "confidence": conf,
                            "version": "6.1NRT" if cur_date.year >= 2024 else "6.1",
                            "bright_t31": b31,
                            "frp": obs_frp,
                            "daynight": dn,
                            "type": ev_type,
                        }
                    else:
                        # VIIRS archive headers
                        # latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight,type
                        conf_letter = "h" if obs_frp > 15 or ev_type != 0 else ("n" if obs_frp > 4 else "l")
                        ti5 = round(288.0 + random.uniform(-5, 12), 1)
                        ti4 = round(ti5 + min(120.0, obs_frp * 2.2), 1)
                        row = {
                            "latitude": round(flat + np.random.normal(0, 0.001), 4),
                            "longitude": round(flon + np.random.normal(0, 0.001), 4),
                            "bright_ti4": ti4,
                            "scan": scan,
                            "track": track,
                            "acq_date": cur_date.strftime("%Y-%m-%d"),
                            "acq_time": acq_time_str,
                            "satellite": sat_info["sat"],
                            "instrument": "VIIRS",
                            "confidence": conf_letter,
                            "version": "2.0NRT" if cur_date.year >= 2024 else "1.0",
                            "bright_ti5": ti5,
                            "frp": obs_frp,
                            "daynight": dn,
                            "type": ev_type,
                        }
                    data_by_sat[sat_key].append(row)

        cur_date += timedelta(days=1)

    # Save to disk
    result_files = {}
    for sat_key, rows in data_by_sat.items():
        if not rows:
            continue
        fname = f"{sat_key.lower()}_{start_year}_{end_year}.csv"
        file_path = out_path / fname
        df = pd.DataFrame(rows)
        df.to_csv(file_path, index=False)
        logger.info(f"Saved {len(df)} synthetic detections to {file_path}")
        result_files[sat_key] = str(file_path)

    return result_files


if __name__ == "__main__":
    generate_synthetic_firms()
