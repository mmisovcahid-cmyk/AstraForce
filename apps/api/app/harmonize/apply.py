"""Seçilen modellerle harmonizasyon katsayılarını ve hücre-gün HFI'sini üretir.

İki hedef ayrı ayrı kalibre edilir ve her biri için en iyi model yıl-dışı doğrulamayla seçilir:
  - evt: olay-gün (ST-DBSCAN olayları)
  - det: sıcak nokta sayısı (görevin "number of hotspots"u), MODIS eşdeğeri
FRP her zaman oran modeliyle (ikincil gösterge).

Sonuç, ülke × gün katsayısı olarak saklanır (harmonized_factor):
  VIIRS günü:  değer = katsayı × VIIRS uydu ortalaması   (katsayı = tahmin / ülke VIIRS değeri)
  MODIS günü:  değer = katsayı × MODIS değeri            (katsayı = Terra ölçeği ya da 1)
Aynı katsayılar hem H3 hücrelerine hem de kullanıcı bölgelerine (ROI) uygulanır; böylece
bir bölgenin toplamı, onu oluşturan hücrelerin toplamıyla tutarlıdır.
"""

import json

import numpy as np
import pandas as pd
import psycopg

from app.harmonize.calibrate import (
    CANDIDATES,
    Model,
    RatioModel,
    build_series,
    evaluate,
    load_country_daily,
    load_coverage,
    select_best,
    terra_factor,
    training_rows,
)
from app.harmonize.settings import AQUA_FIRST_DAY, HFI_VERSION, MODIS, VIIRS_FIRST_DAY

TARGETS = ("evt", "det")


def make_model(name: str, target: str) -> Model:
    m = CANDIDATES[name]()
    m.target, m.x = f"m_{target}", f"v_{target}"
    return m


def compute_factors(
    series: pd.DataFrame, preds: dict[str, pd.Series], k_frp: pd.Series, t_factor: float
) -> pd.DataFrame:
    """Ülke × gün katsayıları. preds: hedef → VIIRS günleri için ülke tahmini."""
    idx = series.index
    viirs_day = (series["v_n"] > 0) & (idx >= pd.Timestamp(VIIRS_FIRST_DAY))
    terra_only = idx < pd.Timestamp(AQUA_FIRST_DAY)
    modis_scale = np.where(terra_only, t_factor, 1.0)
    out = pd.DataFrame(index=idx)
    out["basis"] = np.where(
        viirs_day, "viirs_calibrated", np.where(terra_only, "modis_terra_scaled", "modis")
    )
    out["v_n"] = series["v_n"].astype(int)
    for t in TARGETS:
        v = series[f"v_{t}"].to_numpy(float)
        p = preds[t].reindex(idx).to_numpy(float)
        with np.errstate(divide="ignore", invalid="ignore"):
            f_viirs = np.where(v > 0, p / v, 0.0)
        out[f"f_{t}"] = np.where(viirs_day, np.nan_to_num(f_viirs), modis_scale)
    out["f_frp"] = np.where(viirs_day, k_frp.reindex(idx).fillna(0).to_numpy(), modis_scale)
    out["provisional"] = series["nrt"].astype(bool)
    # Hiçbir uydunun veri vermediği günler (ör. 2000-11 öncesi) katsayı tablosuna girmez
    return out[viirs_day | series["m_avail"]]


def load_cells(conn: psycopg.Connection, country: str) -> pd.DataFrame:
    rows = conn.execute(
        """
        SELECT day, h3_r5::text, source, n_evt, n_det, frp_sum, has_nrt
        FROM daily_cell_stats WHERE country = %s
        """,
        (country,),
    ).fetchall()
    df = pd.DataFrame(rows, columns=["day", "h3", "source", "n_evt", "n_det", "frp", "nrt"])
    df["day"] = pd.to_datetime(df["day"])
    return df


def harmonize_cells(cells: pd.DataFrame, factors: pd.DataFrame) -> pd.DataFrame:
    """Katsayıları H3 hücrelerine uygular (VIIRS günleri: uydu ortalaması; diğerleri: MODIS)."""
    f = factors
    viirs_days = f.index[f["basis"] == "viirs_calibrated"]
    is_viirs_day = cells["day"].isin(viirs_days)

    v = cells[is_viirs_day & (cells["source"] != MODIS)]
    v = v.groupby(["day", "h3"], as_index=False).agg(
        n_evt=("n_evt", "sum"), n_det=("n_det", "sum"), frp=("frp", "sum"), nrt=("nrt", "max")
    )
    fv = f.reindex(v["day"])
    v_n = fv["v_n"].to_numpy(float)
    v_out = pd.DataFrame(
        {
            "day": v["day"],
            "h3": v["h3"],
            "hfi": v["n_evt"].to_numpy() / v_n * fv["f_evt"].to_numpy(),
            "hfi_det": v["n_det"].to_numpy() / v_n * fv["f_det"].to_numpy(),
            "hfi_frp": v["frp"].to_numpy() / v_n * fv["f_frp"].to_numpy(),
            "basis": "viirs_calibrated",
            "nrt": v["nrt"].to_numpy(),
        }
    )

    m = cells[~is_viirs_day & (cells["source"] == MODIS) & cells["day"].isin(f.index)]
    fm = f.reindex(m["day"])
    m_out = pd.DataFrame(
        {
            "day": m["day"].to_numpy(),
            "h3": m["h3"].to_numpy(),
            "hfi": m["n_evt"].to_numpy() * fm["f_evt"].to_numpy(),
            "hfi_det": m["n_det"].to_numpy() * fm["f_det"].to_numpy(),
            "hfi_frp": m["frp"].to_numpy() * fm["f_frp"].to_numpy(),
            "basis": fm["basis"].to_numpy(),
            "nrt": m["nrt"].to_numpy(),
        }
    )
    out = pd.concat([v_out, m_out], ignore_index=True)
    return out[(out["hfi"] > 0) | (out["hfi_det"] > 0)]


def run_calibration(conn: psycopg.Connection, country: str) -> dict:
    coverage = load_coverage(conn, country)
    t_factor = terra_factor(conn, country)
    series = build_series(load_country_daily(conn, country), coverage, t_factor)
    train = training_rows(series)
    if len(train) < 365:
        raise RuntimeError(f"{country}: kalibrasyon için yeterli örtüşen gün yok ({len(train)})")

    pred_days = series[(series["v_n"] > 0) & (series.index >= pd.Timestamp(VIIRS_FIRST_DAY))]
    results: dict[str, dict] = {}
    selected: dict[str, str] = {}
    params: dict[str, dict] = {}
    preds: dict[str, pd.Series] = {}
    for t in TARGETS:
        results[t] = {
            name: evaluate(series, lambda name=name, t=t: make_model(name, t), target=f"m_{t}")
            for name in CANDIDATES
        }
        selected[t] = select_best(results[t])
        # Son model: tüm örtüşme verisiyle
        model = make_model(selected[t], t).fit(train)
        params[t] = model.params()
        preds[t] = pd.Series(model.predict(pred_days), index=pred_days.index)

    frp_model = RatioModel(target="m_frp", x="v_frp").fit(train)
    k_frp = pd.Series(frp_model.factor_series(pred_days), index=pred_days.index)
    factors = compute_factors(series, preds, k_frp, t_factor)
    cells = harmonize_cells(load_cells(conn, country), factors)
    version = f"{HFI_VERSION}:evt={selected['evt']},det={selected['det']}"

    _write(conn, country, version, selected, results, params, t_factor, factors, cells, series)
    return {
        "selected": selected,
        "version": version,
        "terra_factor": round(t_factor, 3),
        "metrics": results,
        "cell_days": len(cells),
    }


def _write(conn, country, version, selected, results, params, t_factor, factors, cells, series):
    with conn.transaction():
        conn.execute("DELETE FROM calibration_model WHERE country = %s", (country,))
        for t, by_method in results.items():
            for name, met in by_method.items():
                p = dict(params[t]) if name == selected[t] else {}
                p["terra_factor"] = t_factor
                conn.execute(
                    """
                    INSERT INTO calibration_model
                        (version, country, method, target, selected, params, metrics)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        version,
                        country,
                        name,
                        t,
                        name == selected[t],
                        json.dumps(p),
                        json.dumps(met),
                    ),
                )

        conn.execute("DELETE FROM harmonized_factor WHERE country = %s", (country,))
        block = pd.DataFrame(
            {
                "country": country,
                "day": factors.index.date,
                "basis": factors["basis"].to_numpy(),
                "v_n": factors["v_n"].to_numpy(),
                "f_evt": factors["f_evt"].round(6).to_numpy(),
                "f_det": factors["f_det"].round(6).to_numpy(),
                "f_frp": factors["f_frp"].round(6).to_numpy(),
                "provisional": factors["provisional"].to_numpy(),
            }
        ).to_csv(index=False, header=False)
        with (
            conn.cursor() as cur,
            cur.copy(
                "COPY harmonized_factor (country, day, basis, v_n, f_evt, f_det, f_frp,"
                " provisional) FROM STDIN WITH (FORMAT csv)"
            ) as copy,
        ):
            copy.write(block)

        conn.execute("DELETE FROM harmonized_daily WHERE country = %s", (country,))
        block = pd.DataFrame(
            {
                "country": country,
                "h3": cells["h3"].to_numpy(),
                "day": cells["day"].dt.date.to_numpy(),
                "hfi": cells["hfi"].round(5).to_numpy(),
                "hfi_det": cells["hfi_det"].round(5).to_numpy(),
                "hfi_frp": cells["hfi_frp"].round(3).to_numpy(),
                "basis": cells["basis"].to_numpy(),
                "provisional": cells["nrt"].astype(bool).to_numpy(),
                "model_version": version,
            }
        ).to_csv(index=False, header=False)
        with (
            conn.cursor() as cur,
            cur.copy(
                "COPY harmonized_daily (country, h3_r5, day, hfi, hfi_det, hfi_frp, basis,"
                " provisional, model_version) FROM STDIN WITH (FORMAT csv)"
            ) as copy,
        ):
            copy.write(block)

        conn.execute("DELETE FROM harmonized_validation WHERE country = %s", (country,))
        yearly = series.groupby("year")[["m_det", "v_det", "m_evt", "v_evt"]].sum(min_count=1)
        by_year = cells.groupby(cells["day"].dt.year)[["hfi", "hfi_det"]].sum()
        for yr, r in yearly.iterrows():
            h = by_year.loc[yr] if yr in by_year.index else None
            conn.execute(
                """
                INSERT INTO harmonized_validation (model_version, country, year, modis_det,
                    viirs_det, modis_evt, viirs_evt, hfi, hfi_det)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    version,
                    country,
                    int(yr),
                    _num(r["m_det"], int),
                    _num(r["v_det"]),
                    _num(r["m_evt"]),
                    _num(r["v_evt"]),
                    _num(h["hfi"] if h is not None else None),
                    _num(h["hfi_det"] if h is not None else None),
                ),
            )
        # Harmonizasyon değişti: bölge önbellekleri eskidi, yeniden hesaplanmalı
        conn.execute(
            "UPDATE roi SET status = 'pending', progress = 0 WHERE %s = ANY(countries)", (country,)
        )


def _num(v, cast=float):
    return None if v is None or pd.isna(v) else cast(v)
