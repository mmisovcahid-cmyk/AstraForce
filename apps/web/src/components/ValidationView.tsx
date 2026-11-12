"use client";

import { useEffect, useRef, useState } from "react";
import { fetchValidation, type Validation } from "@/lib/api";
import type { MessageKey } from "@/lib/i18n";
import { REGIONS, type RegionId } from "@/lib/regions";
import { useLocale } from "@/lib/useLocale";
import { AppHeader } from "./AppHeader";

type State = { kind: "loading" } | { kind: "missing" } | { kind: "ready"; data: Validation };

const COLORS = { modis: "#f97316", viirs: "#60a5fa", hfi: "#f43f5e" };

export function ValidationView() {
  const { locale, setLocale, t } = useLocale();
  const [country, setCountry] = useState<RegionId>("TR");
  const [target, setTarget] = useState<"det" | "evt">("det");
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    const ctrl = new AbortController();
    setState({ kind: "loading" });
    fetchValidation(country, target, ctrl.signal)
      .then((data) => setState({ kind: "ready", data }))
      .catch(() => {
        if (!ctrl.signal.aborted) setState({ kind: "missing" });
      });
    return () => ctrl.abort();
  }, [country, target]);

  return (
    <div className="min-h-screen">
      <AppHeader active="/validation" t={t} locale={locale} setLocale={setLocale}>
        <select
          value={country}
          onChange={(e) => setCountry(e.target.value as RegionId)}
          className="rounded bg-white/10 px-2 py-1"
        >
          {REGIONS.map((r) => (
            <option key={r.id} value={r.id} className="bg-gray-900">
              {t(`region.${r.id}`)}
            </option>
          ))}
        </select>
      </AppHeader>
      <div className="mx-auto max-w-5xl space-y-6 px-4 py-6">
      <h1 className="text-xl font-semibold text-fire-200">{t("validationTitle")}</h1>
      <p className="text-sm text-gray-400">{t("validationIntro")}</p>
      <div className="flex gap-1 text-xs" role="group">
        {(["det", "evt"] as const).map((k) => (
          <button
            key={k}
            type="button"
            aria-pressed={target === k}
            onClick={() => setTarget(k)}
            className={`rounded px-2 py-1 ${target === k ? "bg-white/20" : "bg-white/5 text-gray-400"}`}
          >
            {t(`target.${k}`)}
          </button>
        ))}
      </div>

      {state.kind === "loading" && <p className="text-gray-400">{t("loading")}</p>}
      {state.kind === "missing" && <p className="text-amber-300">{t("noHarmonization")}</p>}
      {state.kind === "ready" && (
        <>
          <YearChart data={state.data} t={t} />
          <ModelTable data={state.data} t={t} />
          <p className="text-xs text-gray-500">{state.data.model_version}</p>
        </>
      )}
      </div>
    </div>
  );
}

function YearChart({ data, t }: { data: Validation; t: (k: MessageKey) => string }) {
  const el = useRef<HTMLDivElement>(null);
  // `t` her render'da yeniden oluşur; grafiği yalnızca veri veya dil değişince yeniden kur.
  const labelsKey = [t("series.modis"), t("series.viirs"), t("series.hfi")].join("|");

  useEffect(() => {
    if (!el.current) return;
    const [modisLabel, viirsLabel, hfiLabel] = labelsKey.split("|");
    const det = data.target === "det";
    let disposed = false;
    let chart: import("echarts").ECharts | undefined;
    const onResize = () => chart?.resize();
    import("echarts").then((echarts) => {
      if (disposed || !el.current) return;
      chart = echarts.init(el.current, "dark", { renderer: "svg" });
      const years = data.years.map((y) => String(y.year));
      const line = (name: string, color: string, values: (number | null)[], dashed = false) => ({
        name,
        type: "line" as const,
        data: values.map((v) => (v == null ? null : Math.round(v))),
        symbolSize: 5,
        lineStyle: { color, width: 2, type: dashed ? ("dashed" as const) : ("solid" as const) },
        itemStyle: { color },
        connectNulls: false,
      });
      chart.setOption({
        backgroundColor: "transparent",
        tooltip: { trigger: "axis" },
        legend: { top: 0, textStyle: { color: "#d1d5db" } },
        grid: { left: 50, right: 20, top: 40, bottom: 30 },
        xAxis: { type: "category", data: years },
        yAxis: { type: "value", splitLine: { lineStyle: { color: "#1f2937" } } },
        series: [
          line(modisLabel, COLORS.modis, data.years.map((y) => (det ? y.modis_det : y.modis_evt))),
          line(viirsLabel, COLORS.viirs, data.years.map((y) => (det ? y.viirs_det : y.viirs_evt)), true),
          line(hfiLabel, COLORS.hfi, data.years.map((y) => (det ? y.hfi_det : y.hfi))),
        ],
      });
      window.addEventListener("resize", onResize);
    });
    return () => {
      disposed = true;
      window.removeEventListener("resize", onResize);
      chart?.dispose();
    };
  }, [data, labelsKey]);

  return <div ref={el} className="h-80 w-full rounded-lg bg-gray-950/60 p-2" />;
}

function ModelTable({ data, t }: { data: Validation; t: (k: MessageKey) => string }) {
  const fmt = (v: number | null | undefined, suffix = "") => (v == null ? "–" : `${v}${suffix}`);
  return (
    <section>
      <h2 className="mb-2 text-sm font-medium text-gray-200">{t("candidates")}</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="text-gray-400">
            <tr>
              <th className="py-1 pr-3">{t("method")}</th>
              <th className="py-1 pr-3 text-right">{t("annualBias")}</th>
              <th className="py-1 pr-3 text-right">{t("dailyR")}</th>
              <th className="py-1 pr-3 text-right">{t("weeklyR")}</th>
              <th className="py-1 text-right">{t("seasonShift")}</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {data.candidates.map(({ method, selected, metrics: m }) => (
              <tr key={method} className={selected ? "text-fire-200" : "text-gray-300"}>
                <td className="py-1 pr-3">
                  {t(`method.${method}` as MessageKey)}
                  {selected && <span className="ml-2 rounded bg-fire-600/30 px-1">{t("selected")}</span>}
                </td>
                <td className="py-1 pr-3 text-right">{fmt(m.mean_abs_annual_bias_pct, "%")}</td>
                <td className="py-1 pr-3 text-right">{fmt(m.daily_r)}</td>
                <td className="py-1 pr-3 text-right">{fmt(m.weekly_r)}</td>
                <td className="py-1 text-right">{fmt(m.mean_season_shift_days, ` ${t("days")}`)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
