"""Kalibrasyon birimlerinin sentetik veriyle testleri (veritabanı gerekmez)."""

from datetime import date

import numpy as np
import pandas as pd

from app.harmonize.apply import compute_factors, harmonize_cells
from app.harmonize.calibrate import (
    CANDIDATES,
    RatioModel,
    build_series,
    evaluate,
    season_days,
    select_best,
    training_rows,
)


def _daily(rows):
    return pd.DataFrame(rows, columns=["day", "source", "n_det", "n_evt", "frp", "nrt"])


def _cov(sources_days):
    return pd.DataFrame(
        [(s, d) for s, days in sources_days.items() for d in days], columns=["source", "day"]
    )


def test_viirs_is_mean_of_available_satellites_and_outage_is_not_zero():
    d1, d2 = date(2020, 6, 1), date(2020, 6, 2)
    daily = _daily(
        [
            (d1, "VIIRS_SNPP", 10, 4, 1.0, False),
            (d1, "VIIRS_NOAA20", 6, 2, 1.0, False),
            (d2, "VIIRS_NOAA20", 8, 6, 1.0, True),  # SNPP o gün veri vermedi
            (d1, "MODIS", 2, 1, 1.0, False),
        ]
    )
    cov = _cov({"VIIRS_SNPP": [d1], "VIIRS_NOAA20": [d1, d2], "MODIS": [d1, d2]})
    s = build_series(daily, cov, t_factor=2.0)
    assert s.loc["2020-06-01", "v_evt"] == 3.0 and s.loc["2020-06-01", "v_n"] == 2
    assert s.loc["2020-06-02", "v_evt"] == 6.0 and s.loc["2020-06-02", "v_n"] == 1
    # MODIS veri verdi ama yangın yok -> 0 (NaN değil); NRT işareti taşınır
    assert s.loc["2020-06-02", "m_evt"] == 0.0 and s.loc["2020-06-02", "nrt"]


def test_terra_only_period_is_scaled():
    d = date(2001, 5, 1)
    s = build_series(_daily([(d, "MODIS", 3, 3, 9.0, False)]), _cov({"MODIS": [d]}), 2.0)
    assert s.loc["2001-05-01", "m_evt"] == 6.0


def _synthetic_series(k=0.35, years=range(2013, 2021), seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(f"{years[0]}-01-01", f"{years[-1]}-12-31", freq="D")
    season = 5 + 40 * np.exp(-(((idx.day_of_year - 210) / 30) ** 2))
    v = rng.poisson(season).astype(float)
    m = rng.poisson(k * v).astype(float)
    return pd.DataFrame(
        {
            "m_evt": m,
            "v_evt": v,
            "v_det": v * 2,
            "v_frp": v * 10,
            "m_frp": m * 30,
            "v_n": 2,
            "m_avail": True,
            "nrt": False,
            "year": idx.year,
            "month": idx.month,
        },
        index=idx,
    )


def test_ratio_model_recovers_known_factor():
    train = training_rows(_synthetic_series(k=0.35))
    model = RatioModel().fit(train)
    for f in model.factors(2016).values():
        assert abs(f - 0.35) < 0.05


def test_calibrated_models_beat_raw_viirs_on_held_out_years():
    s = _synthetic_series(k=0.35)
    results = {name: evaluate(s, factory) for name, factory in CANDIDATES.items()}
    assert results["viirs_raw"]["mean_abs_annual_bias_pct"] > 150
    assert results["ratio"]["mean_abs_annual_bias_pct"] < 5
    assert select_best(results) in ("ratio", "loglinear", "random_forest")


def test_season_days_are_ordered_and_bimodal_safe():
    idx = pd.date_range("2020-01-01", "2020-12-31", freq="D")
    # İki tepe: ilkbahar (gün ~100) ve yaz (gün ~220)
    s = pd.Series(
        np.exp(-(((idx.day_of_year - 100) / 10) ** 2))
        + np.exp(-(((idx.day_of_year - 220) / 10) ** 2)),
        index=idx,
    )
    start, mid, end = season_days(s)
    assert start < mid < end
    assert 90 <= start <= 100 and 220 <= end <= 235


def test_factors_reproduce_country_prediction_and_split_by_viirs_share():
    day = pd.Timestamp("2020-07-01")
    series = pd.DataFrame(
        {
            "v_n": [2],
            "v_evt": [4.0],  # (6 + 2) / 2 uydu
            "v_det": [10.0],
            "m_avail": [True],
            "nrt": [False],
        },
        index=pd.DatetimeIndex([day]),
    )
    preds = {"evt": pd.Series([2.0], index=[day]), "det": pd.Series([5.0], index=[day])}
    factors = compute_factors(series, preds, pd.Series([0.5], index=[day]), t_factor=2.0)
    assert factors.loc[day, "f_evt"] == 0.5 and factors.loc[day, "f_det"] == 0.5
    assert factors.loc[day, "basis"] == "viirs_calibrated"

    cells = pd.DataFrame(
        {
            "day": [day, day, day],
            "h3": ["a", "b", "a"],
            "source": ["VIIRS_SNPP", "VIIRS_SNPP", "MODIS"],
            "n_evt": [6, 2, 1],
            "n_det": [16, 4, 1],
            "frp": [10.0, 10.0, 5.0],
            "nrt": [False, True, False],
        }
    )
    out = harmonize_cells(cells, factors).set_index("h3")
    # hücre = katsayı × hücrenin VIIRS uydu ortalaması; hücreler toplamı = ülke tahmini
    assert out.loc["a", "hfi"] == 1.5 and out.loc["b", "hfi"] == 0.5  # 0.5 × 6/2, 0.5 × 2/2
    assert out["hfi"].sum() == 2.0 and out["hfi_det"].sum() == 5.0
    assert out.loc["a", "hfi_frp"] == 2.5  # (10 / 2 uydu) × 0.5
    assert out["basis"].eq("viirs_calibrated").all() and bool(out.loc["b", "nrt"])


def test_pre_aqua_modis_days_use_terra_scale():
    day = pd.Timestamp("2001-06-01")
    series = pd.DataFrame(
        {"v_n": [0], "v_evt": [np.nan], "v_det": [np.nan], "m_avail": [True], "nrt": [False]},
        index=pd.DatetimeIndex([day]),
    )
    empty = pd.Series(dtype=float)
    factors = compute_factors(series, {"evt": empty, "det": empty}, empty, t_factor=2.0)
    assert factors.loc[day, "basis"] == "modis_terra_scaled" and factors.loc[day, "f_det"] == 2.0
    cells = pd.DataFrame(
        {
            "day": [day],
            "h3": ["a"],
            "source": ["MODIS"],
            "n_evt": [3],
            "n_det": [4],
            "frp": [9.0],
            "nrt": [False],
        }
    )
    out = harmonize_cells(cells, factors).iloc[0]
    assert (out.hfi, out.hfi_det, out.hfi_frp) == (6.0, 8.0, 18.0)
