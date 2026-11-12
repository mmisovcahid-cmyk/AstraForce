"""Takvim ve sezon analitiği: renk düzeyleri, sezon tarihleri, klimatoloji, trend, ay × yıl
matrisi ve tarihsel medyana göre anomali.

Fonksiyonlar saf (pandas/numpy) ve bir "alan"ın (ülke ya da kullanıcı bölgesi) günlük
serisi üzerinde çalışır; veritabanı erişimi app/areas.py ve routes/ altında.
"""

from datetime import date

import numpy as np
import pandas as pd
from scipy.stats import kendalltau, theilslopes

# Renk düzeyleri: 0 = yangın yok, 1..4 = alanın yangınlı günlerinin bu yüzdeliklerine göre
LEVEL_QUANTILES = (0.5, 0.8, 0.95)
# Eşiklerin, medyanların ve klimatolojinin hesaplandığı tam yıllar (veri 2000 Kasım'da başlıyor)
BASE_FIRST_YEAR = 2001
SEASON_QUANTILES = (0.1, 0.5, 0.9)
SMOOTH_DAYS = 7
# Anomali sınıfları (tarihsel medyana göre yüzde fark)
ANOMALY_CLASSES = (
    (-50.0, "much_below"),
    (-15.0, "below"),
    (15.0, "normal"),
    (100.0, "above"),
    (float("inf"), "much_above"),
)


def last_complete_year(today: date | None = None) -> int:
    return (today or date.today()).year - 1


def base_years(today: date | None = None) -> list[int]:
    return list(range(BASE_FIRST_YEAR, last_complete_year(today) + 1))


def levels(values, thresholds: list[float]) -> np.ndarray:
    """Değerleri 0..4 düzeyine çevirir.

    0 = yangın yok, 1 = ≤p50, 2 = ≤p80, 3 = ≤p95, 4 = >p95 (eşikler: LEVEL_QUANTILES).
    """
    v = np.asarray(values, dtype=float)
    if not len(thresholds):
        return np.where(v > 0, 1, 0).astype(int)
    lv = 1 + np.searchsorted(np.asarray(thresholds, dtype=float), v, side="left")
    return np.where(v > 0, np.minimum(lv, 4), 0).astype(int)


def thresholds(s: pd.Series, today: date | None = None) -> list[float]:
    """Alanın tam yıllarındaki yangınlı günlerden renk eşikleri (p50, p80, p95)."""
    yrs = base_years(today)
    v = s[(s.index.year >= yrs[0]) & (s.index.year <= yrs[-1]) & (s > 0)]
    if v.empty:
        return []
    return [round(float(x), 4) for x in np.quantile(v.to_numpy(), LEVEL_QUANTILES)]


def full_series(daily: pd.Series, first: date, last: date) -> pd.Series:
    """Eksik (yangınsız) günleri 0 ile doldurulmuş günlük seri."""
    idx = pd.date_range(first, last, freq="D")
    s = daily.copy()
    s.index = pd.to_datetime(s.index)
    return s.reindex(idx, fill_value=0.0).astype(float)


def season_dates(year_series: pd.Series) -> dict:
    """Bir yılın sezon başlangıcı / ortası / bitişi (%10/%50/%90) ve en yoğun 7 günü."""
    total = float(year_series.sum())
    if total <= 0:
        return {"total": 0.0, "start": None, "mid": None, "end": None, "peak_week_start": None}
    cum = year_series.cumsum().to_numpy() / total
    start, mid, end = (
        year_series.index[int(np.searchsorted(cum, q))].date().isoformat() for q in SEASON_QUANTILES
    )
    roll = year_series.rolling(SMOOTH_DAYS, min_periods=1).sum()
    peak_end = roll.idxmax()
    peak_start = max(peak_end - pd.Timedelta(days=SMOOTH_DAYS - 1), year_series.index[0])
    return {
        "total": round(total, 2),
        "start": start,
        "mid": mid,
        "end": end,
        "peak_week_start": peak_start.date().isoformat(),
    }


def climatology(s: pd.Series, years: list[int]) -> list[dict]:
    """Yılın her günü (1..366) için 7 günlük kayan ortalamanın ortalaması, medyanı, p10–p90."""
    smooth = s.rolling(SMOOTH_DAYS, center=True, min_periods=1).mean()
    df = pd.DataFrame({"v": smooth, "year": smooth.index.year, "doy": smooth.index.day_of_year})
    df = df[df["year"].isin(years)]
    g = df.groupby("doy")["v"]
    out = pd.DataFrame(
        {"mean": g.mean(), "median": g.median(), "p10": g.quantile(0.1), "p90": g.quantile(0.9)}
    )
    return [
        {"doy": int(d), **{k: round(float(r[k]), 3) for k in ("mean", "median", "p10", "p90")}}
        for d, r in out.iterrows()
    ]


def trend(years: list[int], totals: list[float]) -> dict | None:
    """Theil–Sen eğimi ve Mann–Kendall (Kendall tau) anlamlılığı."""
    if len(years) < 5:
        return None
    slope, intercept, lo, hi = theilslopes(totals, years)
    tau, p = kendalltau(years, totals)
    mean = float(np.mean(totals))
    return {
        "slope_per_year": round(float(slope), 3),
        "intercept": round(float(intercept), 3),
        "slope_ci95": [round(float(lo), 3), round(float(hi), 3)],
        "pct_per_decade": round(float(slope) * 10 / mean * 100, 1) if mean > 0 else None,
        "kendall_tau": round(float(tau), 3),
        "p_value": round(float(p), 4),
        "years": [int(years[0]), int(years[-1])],
    }


# Medyan bundan küçükse yüzde fark anlamsızlaşır (0,2'ye göre −%100 / +%900 gibi);
# o durumda yüzde verilmez, sınıf yalnızca "yangın var/yok"a göre belirlenir.
MIN_MEDIAN_FOR_PCT = 1.0


def anomaly_pct(value: float, median: float) -> float | None:
    """Tarihsel medyana göre yüzde fark. Medyan çok küçükse tanımsız (None)."""
    if median < MIN_MEDIAN_FOR_PCT:
        return None
    return round((value / median - 1) * 100, 1)


def anomaly_class(pct: float | None, value: float, median: float) -> str:
    if pct is None:
        # Medyan ~0: yangın yoksa normal; medyanın en az 2 katı ve ≥ 2 ise olağandışı
        if value >= max(2.0, 2 * median):
            return "much_above"
        return "normal"
    for limit, name in ANOMALY_CLASSES:
        if pct <= limit:
            return name
    return "much_above"


def month_matrix(s: pd.Series, first_day: date, today: date | None = None) -> dict:
    """Ay × yıl matrisi: her hücrede toplam, o ayın tarihsel medyanı ve medyana göre anomali.

    İçinde bulunulan ay "kısmi" işaretlenir ve anomalisi, aynı ayın aynı gün aralığının
    tarihsel medyanına göre hesaplanır (ayın ilk N günü ile ilk N günü karşılaştırılır).
    """
    today = today or date.today()
    yrs = base_years(today)
    monthly = s.groupby([s.index.year, s.index.month]).sum()
    medians = {}
    for m in range(1, 13):
        vals = [float(monthly.get((y, m), 0.0)) for y in yrs]
        medians[m] = float(np.median(vals)) if vals else 0.0

    cells = []
    for y in range(first_day.year, today.year + 1):
        for m in range(1, 13):
            if (y, m) < (first_day.year, first_day.month) or (y, m) > (today.year, today.month):
                continue
            value = float(monthly.get((y, m), 0.0))
            partial = (y, m) == (today.year, today.month)
            med = month_to_date_median(s, m, today.day, yrs) if partial else medians[m]
            pct = anomaly_pct(value, med)
            cells.append(
                {
                    "year": y,
                    "month": m,
                    "value": round(value, 2),
                    "median": round(med, 2),
                    "anomaly_pct": pct,
                    "anomaly_class": anomaly_class(pct, value, med),
                    "partial": partial,
                }
            )
    month_values = [c["value"] for c in cells if not c["partial"] and c["value"] > 0]
    month_thresholds = (
        [round(float(x), 3) for x in np.quantile(month_values, LEVEL_QUANTILES)]
        if month_values
        else []
    )
    for c in cells:
        c["level"] = int(levels([c["value"]], month_thresholds)[0])
    return {
        "base_years": [yrs[0], yrs[-1]],
        "monthly_median": [round(medians[m], 2) for m in range(1, 13)],
        "thresholds": month_thresholds,
        "cells": cells,
    }


def month_to_date_median(s: pd.Series, month: int, upto_day: int, yrs: list[int]) -> float:
    vals = [
        float(s[(s.index.year == y) & (s.index.month == month) & (s.index.day <= upto_day)].sum())
        for y in yrs
    ]
    return float(np.median(vals)) if vals else 0.0


def current_status(s: pd.Series, today: date | None = None) -> dict:
    """Acil durum özeti: bu ayın şimdiye kadarki toplamı ve son 7 gün, tarihsel medyana göre."""
    today = today or date.today()
    yrs = base_years(today)
    mtd = float(
        s[
            (s.index.year == today.year)
            & (s.index.month == today.month)
            & (s.index.day <= today.day)
        ].sum()
    )
    mtd_med = month_to_date_median(s, today.month, today.day, yrs)

    last7_end = pd.Timestamp(today)
    last7 = float(s[(s.index > last7_end - pd.Timedelta(days=7)) & (s.index <= last7_end)].sum())
    hist7 = []
    for y in yrs:
        try:
            end = last7_end.replace(year=y)
        except ValueError:  # 29 Şubat
            end = last7_end.replace(year=y, day=28)
        hist7.append(float(s[(s.index > end - pd.Timedelta(days=7)) & (s.index <= end)].sum()))
    last7_med = float(np.median(hist7)) if hist7 else 0.0

    mtd_pct = anomaly_pct(mtd, mtd_med)
    return {
        "as_of": today.isoformat(),
        "month": today.month,
        "month_to_date": round(mtd, 2),
        "month_to_date_median": round(mtd_med, 2),
        "month_anomaly_pct": mtd_pct,
        "month_anomaly_class": anomaly_class(mtd_pct, mtd, mtd_med),
        "last7": round(last7, 2),
        "last7_median": round(last7_med, 2),
        "last7_anomaly_pct": anomaly_pct(last7, last7_med),
        "base_years": [yrs[0], yrs[-1]],
    }
