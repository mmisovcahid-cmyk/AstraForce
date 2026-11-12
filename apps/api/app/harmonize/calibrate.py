"""VIIRS → MODIS eşdeğeri kalibrasyonu ve yıl-dışı (leave-one-year-out) doğrulama.

Hedef (y): ülke düzeyinde günlük MODIS olay-gün sayısı.
Girdi (x): aynı gün veri veren VIIRS uydularının (SNPP, NOAA-20) ortalaması.
Modeller ülke-gün düzeyinde eğitilir; hücre düzeyi, günlük tahminin VIIRS payına göre
dağıtılmasıyla elde edilir (apply.py). VIIRS hiç yangın görmediyse tahmin 0'dır.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import psycopg
from sklearn.ensemble import RandomForestRegressor

from app.harmonize.settings import (
    AQUA_FIRST_DAY,
    MIN_CONFIDENCE,
    MODIS,
    RATIO_PRIOR_WEIGHT,
    RATIO_WINDOW_YEARS,
    TERRA_FACTOR_YEARS,
    VIIRS_FIRST_DAY,
    VIIRS_SOURCES,
)

# ---------------------------------------------------------------- veri yükleme


def load_country_daily(conn: psycopg.Connection, country: str) -> pd.DataFrame:
    rows = conn.execute(
        """
        SELECT day, source, sum(n_det), sum(n_evt), sum(frp_sum), bool_or(has_nrt)
        FROM daily_cell_stats WHERE country = %s GROUP BY 1, 2
        """,
        (country,),
    ).fetchall()
    return pd.DataFrame(rows, columns=["day", "source", "n_det", "n_evt", "frp", "nrt"])


def load_coverage(conn: psycopg.Connection) -> pd.DataFrame:
    """Bir uydunun o gün veri verdiği günler: tüm ülkelerde en az bir tespit (temizlik öncesi).

    Yangın olmayan gün ile uydu kesintisini ayırmak için kullanılır; ABD gibi büyük
    bölgeler neredeyse her gün tespit içerdiği için güvenilir bir göstergedir.
    """
    rows = conn.execute("SELECT source, acq_date FROM fire_detection GROUP BY 1, 2").fetchall()
    return pd.DataFrame(rows, columns=["source", "day"])


def terra_factor(conn: psycopg.Connection, country: str) -> float:
    """(Terra + Aqua) / Terra tespit oranı; Aqua öncesi (2000–2002) MODIS'i ölçeklemek için."""
    total, terra = conn.execute(
        """
        SELECT count(*), count(*) FILTER (WHERE satellite = 'Terra')
        FROM fire_detection f
        WHERE country = %s AND source = %s AND confidence_level >= %s
          AND coalesce(fire_type, 0) = 0
          AND extract(year FROM acq_date) BETWEEN %s AND %s
          AND NOT EXISTS (SELECT 1 FROM static_mask m WHERE m.h3_r8 = f.h3_r8)
        """,
        (country, MODIS, MIN_CONFIDENCE, *TERRA_FACTOR_YEARS),
    ).fetchone()
    return float(total) / terra if terra else 1.0


# ---------------------------------------------------------------- seriler


def build_series(daily: pd.DataFrame, coverage: pd.DataFrame, t_factor: float) -> pd.DataFrame:
    """Ülke-gün serisi: m_* (MODIS), v_* (VIIRS uydu ortalaması), v_n, m_avail, nrt."""
    days = pd.to_datetime(pd.concat([daily["day"], coverage["day"]]))
    idx = pd.date_range(days.min(), days.max(), freq="D", name="day")
    cov = coverage.assign(day=pd.to_datetime(coverage["day"]), v=True)
    cov = cov.pivot_table(index="day", columns="source", values="v", aggfunc="any")
    cov = cov.reindex(idx).fillna(False).astype(bool)

    d = daily.assign(day=pd.to_datetime(daily["day"]))
    out = pd.DataFrame(index=idx)
    nrt = pd.Series(False, index=idx)

    def per_source(src: str) -> pd.DataFrame:
        s = d[d["source"] == src].set_index("day")[["n_det", "n_evt", "frp", "nrt"]].reindex(idx)
        avail = cov[src] if src in cov else pd.Series(False, index=idx)
        vals = s[["n_det", "n_evt", "frp"]].astype(float).fillna(0.0)
        vals[~avail] = np.nan
        return vals.assign(nrt=s["nrt"].fillna(False).astype(bool))

    m = per_source(MODIS)
    scale = np.where(idx < pd.Timestamp(AQUA_FIRST_DAY), t_factor, 1.0)
    out["m_det"], out["m_evt"], out["m_frp"] = (
        m["n_det"] * scale,
        m["n_evt"] * scale,
        m["frp"] * scale,
    )
    out["m_avail"] = m["n_evt"].notna()
    nrt |= m["nrt"]

    v = [per_source(s) for s in VIIRS_SOURCES]
    for col, name in (("n_det", "v_det"), ("n_evt", "v_evt"), ("frp", "v_frp")):
        out[name] = pd.concat([x[col] for x in v], axis=1).mean(axis=1, skipna=True)
    out["v_n"] = pd.concat([x["n_evt"].notna() for x in v], axis=1).sum(axis=1).astype(int)
    for x in v:
        nrt |= x["nrt"]
    out["nrt"] = nrt
    out["year"] = idx.year
    out["month"] = idx.month
    return out


def training_rows(series: pd.DataFrame) -> pd.DataFrame:
    """İki sensörün de veri verdiği, kesinleşmiş (SP) günler."""
    s = series
    mask = s["m_avail"] & (s["v_n"] > 0) & ~s["nrt"] & (s.index >= pd.Timestamp(VIIRS_FIRST_DAY))
    return s[mask]


# ---------------------------------------------------------------- modeller


class Model:
    method: str = ""
    target: str = "m_evt"
    x: str = "v_evt"

    def fit(self, train: pd.DataFrame) -> "Model":
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        raise NotImplementedError

    def params(self) -> dict:
        return {}


class RawViirs(Model):
    """Karşılaştırma tabanı: kalibrasyon yok (VIIRS olay-gün olduğu gibi)."""

    method = "viirs_raw"

    def predict(self, df):
        return df[self.x].to_numpy(dtype=float)


@dataclass
class RatioModel(Model):
    """Ay × kayan yıl penceresi oranı: k = (Σy + α·k0) / (Σx + α).

    k0 aynı penceredeki tüm ayların oranıdır; az yangınlı aylarda oran k0'a çekilir.
    Kayan pencere MODIS yörünge kaymasını (geçiş saatinin yıllara göre değişmesi) yakalar.
    """

    target: str = "m_evt"
    x: str = "v_evt"
    window: int = RATIO_WINDOW_YEARS
    alpha: float = RATIO_PRIOR_WEIGHT
    method: str = "ratio"
    _train: pd.DataFrame | None = field(default=None, repr=False)
    _cache: dict = field(default_factory=dict, repr=False)

    def fit(self, train):
        self._train = train[["year", "month", self.target, self.x]]
        self._cache = {}
        return self

    def factors(self, year: int) -> dict[int, float]:
        if year in self._cache:
            return self._cache[year]
        t = self._train
        years = np.array(sorted(t["year"].unique()))
        win = years[np.abs(years - year) <= self.window]
        if len(win) == 0:  # pencere dışı (ör. gelecek yıl): en yakın yıllar
            win = years[np.argsort(np.abs(years - year))[: 2 * self.window + 1]]
        w = t[t["year"].isin(win)]
        sy, sx = w[self.target].sum(), w[self.x].sum()
        k0 = sy / sx if sx > 0 else 1.0
        by_m = w.groupby("month")[[self.target, self.x]].sum()
        k = {m: k0 for m in range(1, 13)}
        for mo, r in by_m.iterrows():
            k[int(mo)] = (r[self.target] + self.alpha * k0) / (r[self.x] + self.alpha)
        self._cache[year] = k
        return k

    def factor_series(self, df: pd.DataFrame) -> np.ndarray:
        out = np.empty(len(df))
        for (yr, mo), idx in df.groupby(["year", "month"]).indices.items():
            out[idx] = self.factors(int(yr))[int(mo)]
        return out

    def predict(self, df):
        return df[self.x].to_numpy(dtype=float) * self.factor_series(df)

    def params(self):
        years = sorted(self._train["year"].unique())
        return {
            "window_years": self.window,
            "alpha": self.alpha,
            "factors": {
                str(y): {str(m): round(v, 4) for m, v in self.factors(y).items()} for y in years
            },
        }


class LogLinearModel(Model):
    """log1p(y) = a + b·log1p(x) + ay etkileri + c·yıl; Duan smearing ile geri dönüşüm."""

    method = "loglinear"

    def _X(self, df):
        X = [
            np.ones(len(df)),
            np.log1p(df[self.x].to_numpy(float)),
            df["year"].to_numpy(float) - 2018,
        ]
        X += [(df["month"].to_numpy() == m).astype(float) for m in range(2, 13)]
        return np.column_stack(X)

    def fit(self, train):
        y = np.log1p(train[self.target].to_numpy(float))
        X = self._X(train)
        self.coef_, *_ = np.linalg.lstsq(X, y, rcond=None)
        self.smear_ = float(np.mean(np.exp(y - X @ self.coef_)))
        return self

    def predict(self, df):
        p = self.smear_ * np.exp(self._X(df) @ self.coef_) - 1
        return np.where(df[self.x].to_numpy(float) > 0, np.clip(p, 0, None), 0.0)

    def params(self):
        return {"coef": [round(float(c), 5) for c in self.coef_], "smear": round(self.smear_, 5)}


class ForestModel(Model):
    """Random Forest: VIIRS olay/tespit/FRP, mevsim, yıl, uydu sayısı → MODIS olay-gün."""

    method = "random_forest"

    @staticmethod
    def _X(df):
        doy = df.index.day_of_year.to_numpy() if isinstance(df.index, pd.DatetimeIndex) else 0
        ang = 2 * np.pi * np.asarray(doy) / 365.25
        return np.column_stack(
            [
                np.log1p(df["v_evt"].to_numpy(float)),
                np.log1p(df["v_det"].to_numpy(float)),
                np.log1p(df["v_frp"].to_numpy(float)),
                np.sin(ang),
                np.cos(ang),
                df["year"].to_numpy(float),
                df["v_n"].to_numpy(float),
            ]
        )

    def fit(self, train):
        self.rf_ = RandomForestRegressor(
            n_estimators=200, min_samples_leaf=5, n_jobs=-1, random_state=0
        ).fit(self._X(train), train[self.target].to_numpy(float))
        return self

    def predict(self, df):
        p = self.rf_.predict(self._X(df))
        return np.where(df[self.x].to_numpy(float) > 0, np.clip(p, 0, None), 0.0)

    def params(self):
        names = ["log_v_evt", "log_v_det", "log_v_frp", "sin_doy", "cos_doy", "year", "v_n"]
        return {
            "n_estimators": 200,
            "min_samples_leaf": 5,
            "feature_importance": {
                n: round(float(v), 4)
                for n, v in zip(names, self.rf_.feature_importances_, strict=True)
            },
        }


CANDIDATES: dict[str, Callable[[], Model]] = {
    "viirs_raw": RawViirs,
    "ratio": RatioModel,
    "loglinear": LogLinearModel,
    "random_forest": ForestModel,
}
SELECTABLE = ("ratio", "loglinear", "random_forest")


# ---------------------------------------------------------------- doğrulama


SEASON_QUANTILES = (0.1, 0.5, 0.9)  # sezon başlangıcı, ortası, bitişi


def season_days(s: pd.Series) -> list[int]:
    """Yıllık birikimli yangın miktarının %10 / %50 / %90'a ulaştığı yılın günleri.

    Tek bir "en yoğun gün" yerine bu üç tarih kullanılır: Türkiye ve Azerbaycan'da
    ilkbahar (tarım) ve yaz (orman) olmak üzere iki tepe olduğundan en yoğun gün yıldan
    yıla iki sezon arasında atlayabilir; birikimli dağılım ise kararlıdır.
    """
    c = s.cumsum() / s.sum()
    return [int(c.index[np.searchsorted(c.to_numpy(), q)].day_of_year) for q in SEASON_QUANTILES]


def metrics_for(y: pd.Series, p: pd.Series) -> dict:
    by_year = pd.DataFrame({"y": y, "p": p}).groupby(y.index.year).sum()
    bias = ((by_year["p"] - by_year["y"]) / by_year["y"].where(by_year["y"] > 0)).dropna()
    weekly = pd.DataFrame({"y": y, "p": p}).resample("W").sum()
    shifts = []
    for yr in sorted(set(y.index.year)):
        yy, pp = y[y.index.year == yr], p[p.index.year == yr]
        if yy.sum() > 0 and pp.sum() > 0:
            shifts += [abs(a - b) for a, b in zip(season_days(yy), season_days(pp), strict=True)]
    return {
        "mean_abs_annual_bias_pct": round(float(bias.abs().mean() * 100), 2),
        "annual_bias_pct": {str(k): round(float(v * 100), 2) for k, v in bias.items()},
        "daily_r": round(float(np.corrcoef(y, p)[0, 1]), 4) if len(y) > 2 else None,
        "weekly_r": round(float(np.corrcoef(weekly["y"], weekly["p"])[0, 1]), 4)
        if len(weekly) > 2
        else None,
        "daily_mae": round(float(np.mean(np.abs(y - p))), 3),
        "mean_season_shift_days": round(float(np.mean(shifts)), 1) if shifts else None,
        "test_days": int(len(y)),
    }


def test_years(train: pd.DataFrame, min_days: int = 300) -> list[int]:
    counts = train.groupby("year").size()
    return [int(y) for y, n in counts.items() if n >= min_days]


def evaluate(series: pd.DataFrame, factory: Callable[[], Model], target: str = "m_evt") -> dict:
    """Yıl-dışı doğrulama: her test yılı için model diğer yıllarla eğitilir."""
    train = training_rows(series)
    preds = []
    for yr in test_years(train):
        model = factory().fit(train[train["year"] != yr])
        test = train[train["year"] == yr]
        preds.append(pd.Series(model.predict(test), index=test.index))
    p = pd.concat(preds).sort_index()
    return metrics_for(train.loc[p.index, target], p)


def select_best(results: dict[str, dict]) -> str:
    """En düşük ortalama |yıllık sapma|; eşitlikte en yüksek günlük r."""
    return min(
        SELECTABLE,
        key=lambda m: (results[m]["mean_abs_annual_bias_pct"], -(results[m]["daily_r"] or 0)),
    )
