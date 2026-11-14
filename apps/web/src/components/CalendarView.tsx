"use client";

import type { EChartsOption } from "echarts";
import { useEffect, useMemo, useState } from "react";
import {
  type CalendarData,
  exportUrls,
  fetchCalendar,
  fetchMatrix,
  fetchRange,
  fetchRoi,
  retryRoi,
  fetchSeason,
  fetchStatus,
  type MatrixData,
  NotReadyError,
  type RangeData,
  type RoiInfo,
  type SeasonData,
  type StatusData,
} from "@/lib/api";
import {
  ANOMALY_COLORS,
  doyToIso,
  formatDate,
  formatNumber,
  type Metric,
  METRICS,
  monthNames,
  movingAverage,
  NO_DATA_COLOR,
  type RampName,
  weekdayNames,
} from "@/lib/calendar";
import { addDays, todayUtc } from "@/lib/dates";
import type { Locale, MessageKey } from "@/lib/i18n";
import { type AreaCode, isRoi, parseAreaCode, roiId } from "@/lib/regions";
import { parseIntParam, readParams, writeParams } from "@/lib/url";
import { useLocale } from "@/lib/useLocale";
import { useRamp } from "@/lib/useRamp";
import { AppHeader } from "./AppHeader";
import { AreaPicker } from "./AreaPicker";
import { EChart } from "./EChart";

const FIRST_YEAR = 2000;
const CURRENT_YEAR = new Date().getUTCFullYear();
const DEFAULT_YEAR = CURRENT_YEAR - 1; // son tamamlanmış yıl
const MEAN_DISPLAY_YEAR = 2024;
const ROI_POLL_MS = 1200;
const ROI_POLL_MAX_FAILURES = 5; // ~1,2 + 2,4 + 4,8 + 9,6 sn geçici kesintiye dayanır
type T = (k: MessageKey) => string;

const unitOf = (m: Metric) => (m === "frp" ? " MW" : "");
const signed = (v: number, locale: Locale) => `${v > 0 ? "+" : ""}${formatNumber(v, locale, 1)}%`;

export function CalendarView() {
  const { locale, setLocale, t } = useLocale();
  const { ramp, colors, setRamp } = useRamp();
  const [area, setArea] = useState<AreaCode>("AZ");
  const [year, setYear] = useState(DEFAULT_YEAR);
  const [mean, setMean] = useState(false);
  const [metric, setMetric] = useState<Metric>("hotspots");
  const [compareYear, setCompareYear] = useState(DEFAULT_YEAR - 1);
  const [rangeTo, setRangeTo] = useState(() => addDays(todayUtc(), -1));
  const [rangeFrom, setRangeFrom] = useState(() => addDays(todayUtc(), -30));
  const [ready, setReady] = useState(false);

  const [roi, setRoi] = useState<RoiInfo | null>(null);
  const [areaReady, setAreaReady] = useState(false);
  const [cal, setCal] = useState<CalendarData | null>(null);
  const [season, setSeason] = useState<SeasonData | null>(null);
  const [matrix, setMatrix] = useState<MatrixData | null>(null);
  const [status, setStatus] = useState<StatusData | null>(null);
  const [range, setRange] = useState<RangeData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [roiFailed, setRoiFailed] = useState(false);
  const [pollKey, setPollKey] = useState(0);

  // Adres çubuğundan ilk durum
  useEffect(() => {
    const p = readParams();
    const a = parseAreaCode(p.get("area") ?? p.get("region"));
    if (a) setArea(a);
    const y = parseIntParam(p.get("year"), FIRST_YEAR, CURRENT_YEAR);
    if (y) setYear(y);
    if (p.get("mode") === "mean") setMean(true);
    const m = p.get("metric");
    if (m === "events" || m === "frp") setMetric(m);
    const c = parseIntParam(p.get("compare"), FIRST_YEAR, CURRENT_YEAR);
    if (c) setCompareYear(c);
    const f = p.get("from");
    const to = p.get("to");
    if (f && /^\d{4}-\d{2}-\d{2}$/.test(f)) setRangeFrom(f);
    if (to && /^\d{4}-\d{2}-\d{2}$/.test(to)) setRangeTo(to);
    setReady(true);
  }, []);

  useEffect(() => {
    if (!ready) return;
    writeParams({
      area,
      region: null,
      year: mean ? null : year,
      mode: mean ? "mean" : null,
      metric: metric === "hotspots" ? null : metric,
      compare: compareYear,
      from: rangeFrom,
      to: rangeTo,
    });
  }, [ready, area, year, mean, metric, compareYear, rangeFrom, rangeTo]);

  // ROI: hazır olana kadar ilerlemeyi yokla
  useEffect(() => {
    if (!ready) return;
    setError(null);
    const id = roiId(area);
    if (!id) {
      setRoi(null);
      setAreaReady(true);
      return;
    }
    setAreaReady(false);
    setRoiFailed(false);
    let stop = false;
    const ctrl = new AbortController();
    const poll = async () => {
      let failures = 0;
      while (!stop) {
        try {
          const info = await fetchRoi(id, ctrl.signal);
          failures = 0;
          setError(null);
          setRoi(info);
          if (info.status === "ready") {
            setAreaReady(true);
            return;
          }
          if (info.status === "error") {
            setError(`${t("roiError")}: ${info.error ?? ""}`);
            setRoiFailed(true);
            return;
          }
        } catch (e) {
          if (stop) return;
          // Geçici ağ / API kesintisi: artan aralıklarla yeniden dene, sonra vazgeç
          failures += 1;
          if (failures >= ROI_POLL_MAX_FAILURES) {
            setError(e instanceof Error ? e.message : String(e));
            setRoiFailed(true);
            return;
          }
        }
        await new Promise((r) => setTimeout(r, ROI_POLL_MS * 2 ** failures));
      }
    };
    void poll();
    return () => {
      stop = true;
      ctrl.abort();
    };
  }, [ready, area, t, pollKey]);

  const retry = async () => {
    const id = roiId(area);
    if (!id) return;
    setError(null);
    try {
      await retryRoi(id);
    } catch {
      // Yine de yoklamayı yeniden başlat: API geri geldiyse durum oradan okunur
    }
    setPollKey((k) => k + 1);
  };

  const load = <D,>(
    fn: (signal: AbortSignal) => Promise<D>,
    set: (d: D | null) => void,
    deps: unknown[],
  ) => [
    () => {
      if (!ready || !areaReady) return;
      const ctrl = new AbortController();
      set(null);
      fn(ctrl.signal)
        .then(set)
        .catch((e) => {
          if (ctrl.signal.aborted || e instanceof NotReadyError) return;
          setError(e instanceof Error ? e.message : String(e));
        });
      return () => ctrl.abort();
    },
    [ready, areaReady, ...deps],
  ] as const;

  const calEff = load((s) => fetchCalendar(area, mean ? { mode: "mean" } : { mode: "year", year }, s), setCal, [area, year, mean]);
  useEffect(calEff[0], calEff[1]);
  const seasonEff = load((s) => fetchSeason(area, metric, s), setSeason, [area, metric]);
  useEffect(seasonEff[0], seasonEff[1]);
  const matrixEff = load((s) => fetchMatrix(area, metric, s), setMatrix, [area, metric]);
  useEffect(matrixEff[0], matrixEff[1]);
  const statusEff = load((s) => fetchStatus(area, metric, s), setStatus, [area, metric]);
  useEffect(statusEff[0], statusEff[1]);
  const rangeEff = load((s) => fetchRange(area, metric, rangeFrom, rangeTo, s), setRange, [area, metric, rangeFrom, rangeTo]);
  useEffect(rangeEff[0], rangeEff[1]);

  const years = useMemo(
    () => Array.from({ length: CURRENT_YEAR - FIRST_YEAR + 1 }, (_, i) => CURRENT_YEAR - i),
    [],
  );
  const seasonYear = season?.years.find((y) => y.year === year) ?? null;
  const fileBase = `astraforce_${area.replace(":", "-")}_${metric}`;
  const areaLabel = isRoi(area) ? roi?.name || t("roiLabel") : t(`region.${area}` as MessageKey);

  return (
    <div className="min-h-screen">
      <AppHeader active="/" t={t} locale={locale} setLocale={setLocale}>
        <label className="flex items-center gap-1.5 print:hidden">
          <span className="text-gray-400">{t("colorRamp")}</span>
          <select
            value={ramp}
            onChange={(e) => setRamp(e.target.value as RampName)}
            className="rounded bg-white/10 px-2 py-1"
          >
            {(["fire", "cividis"] as const).map((r) => (
              <option key={r} value={r} className="bg-gray-900">
                {t(`ramp.${r}`)}
              </option>
            ))}
          </select>
        </label>
      </AppHeader>

      <main className="mx-auto max-w-6xl space-y-5 px-4 py-5">
        <section className="flex flex-wrap items-end gap-3 text-xs print:hidden">
          <AreaPicker area={area} roi={roi} onChange={setArea} t={t} />
          <div className="ml-auto flex flex-col gap-1">
            <span className="text-gray-400">{t("metric")}</span>
            <div className="flex gap-1" role="group" aria-label={t("metric")}>
              {METRICS.map((m) => (
                <button
                  key={m}
                  type="button"
                  aria-pressed={m === metric}
                  title={t(`metric.${m}.help` as MessageKey)}
                  onClick={() => setMetric(m)}
                  className={`rounded px-2 py-1.5 ${
                    m === metric ? "bg-white/20 text-white" : "bg-white/5 text-gray-400 hover:bg-white/10"
                  }`}
                >
                  {t(`metric.${m}` as MessageKey)}
                </button>
              ))}
            </div>
          </div>
        </section>

        <p className="text-xs text-gray-400">
          <b className="text-gray-200">{areaLabel}</b>
          {roi && ` · ${formatNumber(roi.area_km2, locale)} km²`} · {t(`metric.${metric}.help` as MessageKey)}
        </p>
        {roi && roi.covered_pct < 99 && (
          <p className="text-xs text-amber-300">
            ⚠ {t("partialCoverage").replace("{p}", formatNumber(roi.covered_pct, locale))}
          </p>
        )}
        {error && (
          <p className="text-sm text-red-400">
            {error}
            {roiFailed && (
              <button type="button" onClick={retry} className="ml-3 rounded bg-white/10 px-2 py-0.5 text-gray-200 hover:bg-white/20 print:hidden">
                {t("retry")}
              </button>
            )}
          </p>
        )}

        {!areaReady && roi && !error && (
          <div className="rounded-lg bg-gray-950/60 p-4" role="status">
            <p className="mb-2 text-sm text-gray-300">
              {t("computing").replace("{p}", formatNumber(roi.progress, locale))}
            </p>
            <div className="h-2 overflow-hidden rounded bg-white/10">
              <div className="h-full bg-fire-600 transition-all" style={{ width: `${roi.progress}%` }} />
            </div>
          </div>
        )}

        {areaReady && (
          <>
            {status && <StatusCard status={status} metric={metric} locale={locale} t={t} />}

            <section className="rounded-lg bg-gray-950/60 p-3">
              <div className="mb-1 flex flex-wrap items-center gap-3 text-xs print:hidden">
                <h2 className="text-sm font-medium text-gray-200">
                  {t("calendarTitle")} · {mean ? t("meanMode") : year}
                </h2>
                <select
                  value={year}
                  disabled={mean}
                  aria-label={t("year")}
                  onChange={(e) => setYear(Number(e.target.value))}
                  className="rounded bg-white/10 px-2 py-1 disabled:opacity-40"
                >
                  {years.map((y) => (
                    <option key={y} value={y} className="bg-gray-900">
                      {y}
                    </option>
                  ))}
                </select>
                <input
                  type="range"
                  aria-label={t("year")}
                  min={FIRST_YEAR}
                  max={CURRENT_YEAR}
                  value={year}
                  disabled={mean}
                  onChange={(e) => setYear(Number(e.target.value))}
                  className="w-48 accent-orange-500 disabled:opacity-40"
                />
                <label className="flex items-center gap-1.5 rounded bg-white/5 px-2 py-1">
                  <input type="checkbox" checked={mean} onChange={(e) => setMean(e.target.checked)} />
                  {t("meanMode")}
                </label>
              </div>
              {cal ? (
                <FireCalendar data={cal} metric={metric} area={area} colors={colors} locale={locale} t={t} />
              ) : (
                <p className="h-40 text-xs text-gray-500">{t("loading")}</p>
              )}
              <Legend colors={colors} t={t} />
            </section>

            {season && (
              <Kpis season={season} seasonYear={mean ? null : seasonYear} metric={metric} locale={locale} t={t} />
            )}

            <RangePanel
              area={area}
              metric={metric}
              from={rangeFrom}
              to={rangeTo}
              setFrom={setRangeFrom}
              setTo={setRangeTo}
              range={range}
              locale={locale}
              t={t}
            />

            <section className="rounded-lg bg-gray-950/60 p-3">
              <h2 className="text-sm font-medium text-gray-200">{t("matrixTitle")}</h2>
              {matrix ? (
                <MatrixChart matrix={matrix} metric={metric} colors={colors} locale={locale} t={t} pngName={`${fileBase}_matrix`} />
              ) : (
                <p className="h-40 text-xs text-gray-500">{t("loading")}</p>
              )}
            </section>

            <div className="grid gap-5 lg:grid-cols-2">
              <section className="rounded-lg bg-gray-950/60 p-3">
                <h2 className="text-sm font-medium text-gray-200">{t("seasonalityTitle")}</h2>
                {season && (
                  <SeasonalityChart season={season} cal={mean ? null : cal} metric={metric} year={year} locale={locale} t={t} pngName={`${fileBase}_seasonality`} />
                )}
              </section>
              <section className="rounded-lg bg-gray-950/60 p-3">
                <h2 className="text-sm font-medium text-gray-200">{t("trendTitle")}</h2>
                {season && <TrendChart season={season} year={mean ? null : year} locale={locale} t={t} pngName={`${fileBase}_trend`} />}
              </section>
            </div>

            <section className="rounded-lg bg-gray-950/60 p-3">
              <div className="flex flex-wrap items-center gap-3">
                <h2 className="text-sm font-medium text-gray-200">{t("monthlyTitle")}</h2>
                <label className="ml-auto flex items-center gap-1.5 text-xs print:hidden">
                  <span className="text-gray-400">{t("compareWith")}</span>
                  <select
                    value={compareYear}
                    onChange={(e) => setCompareYear(Number(e.target.value))}
                    className="rounded bg-white/10 px-2 py-1"
                  >
                    {years.map((y) => (
                      <option key={y} value={y} className="bg-gray-900">
                        {y}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              {matrix && (
                <MonthlyChart matrix={matrix} year={mean ? null : year} compareYear={compareYear} locale={locale} t={t} pngName={`${fileBase}_monthly`} />
              )}
            </section>
          </>
        )}
      </main>
    </div>
  );
}

function StatusCard({ status, metric, locale, t }: { status: StatusData; metric: Metric; locale: Locale; t: T }) {
  const tile = (label: string, value: number, median: number, pct: number | null, cls?: string) => (
    <div className="flex-1 rounded-lg bg-gray-950/60 p-3">
      <div className="text-[11px] text-gray-400">{label}</div>
      <div className="mt-0.5 flex items-baseline gap-2">
        <span className="text-2xl font-semibold tabular-nums">{formatNumber(value, locale, 1)}{unitOf(metric)}</span>
        {pct !== null && <span className="text-sm tabular-nums" style={{ color: pct > 0 ? ANOMALY_COLORS.above : ANOMALY_COLORS.below }}>{signed(pct, locale)}</span>}
      </div>
      <div className="text-[11px] text-gray-500">
        {t("medianShort")} {status.base_years[0]}–{status.base_years[1]}: {formatNumber(median, locale, 1)}
        {cls && <> · <span style={{ color: ANOMALY_COLORS[cls as keyof typeof ANOMALY_COLORS] }}>{t(`anomaly.${cls}` as MessageKey)}</span></>}
      </div>
    </div>
  );
  return (
    <section aria-label={t("statusTitle")}>
      <h2 className="mb-2 text-sm font-medium text-gray-200">
        {t("statusTitle")} · {formatDate(status.as_of, locale)}
        {status.latest_data_day && status.latest_data_day !== status.as_of && (
          <span className="ml-2 text-xs font-normal text-gray-500">({t("latestData")}: {formatDate(status.latest_data_day, locale)})</span>
        )}
      </h2>
      <div className="flex flex-col gap-2 sm:flex-row">
        {tile(t("thisMonth"), status.month_to_date, status.month_to_date_median, status.month_anomaly_pct, status.month_anomaly_class)}
        {tile(t("last7"), status.last7, status.last7_median, status.last7_anomaly_pct)}
      </div>
    </section>
  );
}

function RangePanel({
  area, metric, from, to, setFrom, setTo, range, locale, t,
}: {
  area: AreaCode; metric: Metric; from: string; to: string;
  setFrom: (v: string) => void; setTo: (v: string) => void;
  range: RangeData | null; locale: Locale; t: T;
}) {
  const country = isRoi(area) ? null : area;
  const link = "rounded bg-white/10 px-3 py-1.5 hover:bg-white/20";
  return (
    <section className="grid gap-3 rounded-lg bg-gray-950/60 p-3 text-xs md:grid-cols-[auto_1fr_auto]">
      <div className="flex items-end gap-2">
        <label className="flex flex-col gap-1">
          <span className="text-gray-400">{t("from")}</span>
          <input type="date" value={from} min="2000-11-01" max={to} onChange={(e) => e.target.value && setFrom(e.target.value)} className="rounded bg-white/10 px-2 py-1 [color-scheme:dark]" />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-gray-400">{t("to")}</span>
          <input type="date" value={to} min={from} max={todayUtc()} onChange={(e) => e.target.value && setTo(e.target.value)} className="rounded bg-white/10 px-2 py-1 [color-scheme:dark]" />
        </label>
      </div>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-1">
        <span className="text-sm font-medium text-gray-200">{t("rangeTitle")}</span>
        {range && range.total === null ? (
          <span className="text-gray-500">{t("noDataYet")}</span>
        ) : range && range.median !== null ? (
          <>
            <span>{t("rangeTotal")}: <b className="tabular-nums">{formatNumber(range.total ?? 0, locale, 1)}{unitOf(metric)}</b></span>
            <span>{t("medianShort")}: <span className="tabular-nums">{formatNumber(range.median, locale, 1)}</span>
              {range.anomaly_pct !== null && <span className="ml-1" style={{ color: range.anomaly_pct > 0 ? ANOMALY_COLORS.above : ANOMALY_COLORS.below }}>({signed(range.anomaly_pct, locale)})</span>}
            </span>
            <span>{t("fireDays")}: <b>{range.fire_days}</b></span>
            {range.effective_date_to && range.effective_date_to < range.date_to && (
              <span className="text-gray-500">{t("dataUntil")} {formatDate(range.effective_date_to, locale)}</span>
            )}
          </>
        ) : (
          <span className="text-gray-500">{t("loading")}</span>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2 print:hidden">
        <span className="text-gray-400">{t("downloads")}:</span>
        <a className={link} href={exportUrls.hotspots(area, from, to)}>{t("dlHotspots")}</a>
        <a className={link} href={exportUrls.daily(area, from, to)}>{t("dlDaily")}</a>
        <a className={link} href={exportUrls.matrix(area, metric)}>{t("dlMatrix")}</a>
        <button type="button" className={link} onClick={() => window.print()}>{t("printReport")}</button>
        {country && (
          <a className={link} href={`/map?region=${country}&date=${to}&range=30`}>{t("openMap")}</a>
        )}
      </div>
    </section>
  );
}

function Legend({ colors, t }: { colors: readonly string[]; t: T }) {
  return (
    <div className="mt-1 flex flex-wrap items-center justify-end gap-1.5 text-[11px] text-gray-400">
      <span>{t("noFire")}</span>
      <span className="h-3 w-3 rounded-sm" style={{ background: colors[0] }} />
      <span className="ml-3">{t("less")}</span>
      {colors.slice(1).map((c) => (
        <span key={c} className="h-3 w-3 rounded-sm" style={{ background: c }} />
      ))}
      <span>{t("more")}</span>
      <span className="ml-3 h-3 w-3 rounded-sm border border-dashed border-gray-200" />
      <span>{t("provisional")}</span>
    </div>
  );
}

function FireCalendar({
  data, metric, area, colors, locale, t,
}: {
  data: CalendarData; metric: Metric; area: AreaCode; colors: readonly string[]; locale: Locale; t: T;
}) {
  const option = useMemo<EChartsOption>(() => {
    const byDate = new Map(data.days.map((d) => [d.date, d]));
    const isMean = data.mode === "mean";
    const year = isMean ? MEAN_DISPLAY_YEAR : (data.year ?? MEAN_DISPLAY_YEAR);
    const levelKey = `level_${metric}` as const;
    const points = data.days
      .filter((d) => d[levelKey] !== null)
      .map((d) => {
        const level = d[levelKey] ?? 0;
        return d.provisional
          ? { value: [d.date, level], itemStyle: { borderColor: "#e5e7eb", borderType: "dashed" as const, borderWidth: 1 } }
          : { value: [d.date, level] };
      });
    return {
      backgroundColor: "transparent",
      tooltip: {
        formatter: (p: unknown) => {
          const v = (p as { value: [string, number] }).value;
          const d = byDate.get(v[0]);
          if (!d) return "";
          const lines = [
            `<b>${formatDate(d.date, locale, !isMean)}</b>${isMean ? ` · ${t("meanMode")}` : ""}`,
            `${t("metric.hotspots")}: <b>${formatNumber(d.hotspots ?? 0, locale, 1)}</b>`,
            `${t("metric.events")}: ${formatNumber(d.events ?? 0, locale, 1)}`,
            `${t("metric.frp")}: ${formatNumber(d.frp ?? 0, locale)} MW`,
          ];
          if (!isMean) {
            lines.push(`<span style="color:#9ca3af">MODIS ${d.modis_det ?? 0} · VIIRS SNPP ${d.viirs_snpp_det ?? 0} · NOAA-20 ${d.viirs_noaa20_det ?? 0} · NOAA-21 ${d.viirs_noaa21_det ?? 0}</span>`);
            if (d.provisional) lines.push(`<i>${t("provisional")}</i>`);
            if (!isRoi(area)) lines.push(`<span style="color:#9ca3af">${t("clickForMap")}</span>`);
          }
          return lines.join("<br/>");
        },
      },
      visualMap: { show: false, type: "piecewise", dimension: 1, pieces: colors.map((color, value) => ({ value, color })) },
      calendar: {
        range: String(year),
        top: 28, left: 36, right: 8,
        cellSize: ["auto", 15],
        splitLine: { show: false },
        itemStyle: { color: NO_DATA_COLOR, borderColor: "#030712", borderWidth: 2 },
        yearLabel: { show: false },
        dayLabel: { firstDay: 1, nameMap: weekdayNames(locale), color: "#9ca3af", fontSize: 10 },
        monthLabel: { nameMap: monthNames(locale), color: "#9ca3af", fontSize: 11 },
      },
      series: [{ type: "heatmap", coordinateSystem: "calendar", data: points }],
    };
  }, [data, metric, area, colors, locale, t]);

  const onClick = (p: { value?: unknown }) => {
    const v = p.value as [string, number] | undefined;
    if (!v || data.mode === "mean" || isRoi(area)) return;
    window.location.href = `/map?region=${area}&date=${v[0]}&range=1`;
  };
  // Telefonda 53 hafta sığmaz: en az 720 px genişlik, yatay kaydırma
  return (
    <div className="-mx-1 overflow-x-auto px-1">
      <EChart option={option} onClick={onClick} className="h-44 w-full min-w-[720px]" />
    </div>
  );
}

function Kpis({
  season, seasonYear, metric, locale, t,
}: {
  season: SeasonData; seasonYear: SeasonData["years"][number] | null; metric: Metric; locale: Locale; t: T;
}) {
  const unit = unitOf(metric);
  const meanDate = (k: keyof SeasonData["mean_season_doy"]) => {
    const doy = season.mean_season_doy[k];
    return doy === null ? "–" : formatDate(doyToIso(2025, doy), locale, false);
  };
  const nYears = season.base_years[1] - season.base_years[0] + 1;
  const seasonTiles = (
    [["seasonStart", "start"], ["seasonMid", "mid"], ["seasonEnd", "end"], ["peakWeek", "peak_week_start"]] as const
  );
  const tiles: { label: string; value: string; sub?: string }[] = seasonYear
    ? [
        { label: t("annualTotal"), value: formatNumber(seasonYear.total, locale) + unit, sub: seasonYear.complete ? undefined : t("incompleteYear") },
        {
          label: t("vsMedianShort"),
          value: seasonYear.vs_median_pct === null ? "–" : signed(seasonYear.vs_median_pct, locale),
          sub: `${t("medianShort")}: ${formatNumber(season.median_total, locale)}${unit}`,
        },
        { label: t("rank"), value: seasonYear.rank ? `${seasonYear.rank}` : "–", sub: t("rankOf").replace("{n}", String(nYears)) },
        ...seasonTiles.map(([label, k]) => ({
          label: t(label),
          value: seasonYear[k] ? formatDate(seasonYear[k] as string, locale, false) : "–",
          sub: `${t("meanShort")}: ${meanDate(k)}`,
        })),
      ]
    : [
        { label: `${t("annualTotal")} (${t("medianShort")})`, value: formatNumber(season.median_total, locale) + unit, sub: `${season.base_years[0]}–${season.base_years[1]}` },
        ...seasonTiles.map(([label, k]) => ({ label: t(label), value: meanDate(k) })),
      ];
  return (
    <section className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
      {tiles.map((tile) => (
        <div key={tile.label} className="rounded-lg bg-gray-950/60 p-3">
          <div className="text-[11px] text-gray-400">{tile.label}</div>
          <div className="mt-0.5 text-lg font-semibold tabular-nums text-gray-100">{tile.value}</div>
          {tile.sub && <div className="text-[11px] text-gray-500">{tile.sub}</div>}
        </div>
      ))}
    </section>
  );
}

function MatrixChart({
  matrix, metric, colors, locale, t, pngName,
}: {
  matrix: MatrixData; metric: Metric; colors: readonly string[]; locale: Locale; t: T; pngName: string;
}) {
  const [view, setView] = useState<"value" | "anomaly">("value");
  const option = useMemo<EChartsOption>(() => {
    const years = [...new Set(matrix.cells.map((c) => c.year))].sort((a, b) => b - a);
    const months = monthNames(locale);
    const anomalyIndex = { much_below: 0, below: 1, normal: 2, above: 3, much_above: 4 } as const;
    const anomalyColors = [ANOMALY_COLORS.much_below, ANOMALY_COLORS.below, ANOMALY_COLORS.normal, ANOMALY_COLORS.above, ANOMALY_COLORS.much_above];
    const byKey = new Map(matrix.cells.map((c) => [`${c.year}-${c.month}`, c]));
    const data = matrix.cells.map((c) => {
      const v = view === "value" ? c.level : anomalyIndex[c.anomaly_class];
      const item = { value: [c.month - 1, years.indexOf(c.year), v] };
      return c.partial ? { ...item, itemStyle: { borderColor: "#e5e7eb", borderType: "dashed" as const, borderWidth: 1 } } : item;
    });
    return {
      backgroundColor: "transparent",
      tooltip: {
        formatter: (p: unknown) => {
          const [mi, yi] = (p as { value: [number, number, number] }).value;
          const c = byKey.get(`${years[yi]}-${mi + 1}`);
          if (!c) return "";
          return [
            `<b>${monthNames(locale, "long")[c.month - 1]} ${c.year}</b>${c.partial ? ` (${t("partialMonth")})` : ""}`,
            `${t(`metric.${metric}` as MessageKey)}: <b>${formatNumber(c.value, locale, 1)}${unitOf(metric)}</b>`,
            `${t("medianShort")} ${matrix.base_years[0]}–${matrix.base_years[1]}: ${formatNumber(c.median, locale, 1)}`,
            c.anomaly_pct === null ? "" : `${signed(c.anomaly_pct, locale)} · ${t(`anomaly.${c.anomaly_class}` as MessageKey)}`,
          ].filter(Boolean).join("<br/>");
        },
      },
      grid: { left: 44, right: 12, top: 24, bottom: 24 },
      xAxis: { type: "category", data: months, position: "top", splitArea: { show: false }, axisLabel: { color: "#9ca3af" } },
      yAxis: { type: "category", data: years.map(String), axisLabel: { color: "#9ca3af", fontSize: 10 } },
      visualMap: {
        show: false, type: "piecewise", dimension: 2,
        pieces: (view === "value" ? colors : anomalyColors).map((color, value) => ({ value, color })),
      },
      series: [{ type: "heatmap", data, itemStyle: { borderColor: "#030712", borderWidth: 1 } }],
    };
  }, [matrix, metric, colors, locale, t, view]);

  const rows = new Set(matrix.cells.map((c) => c.year)).size;
  return (
    <div>
      <div className="mb-1 flex items-center gap-1 text-xs print:hidden">
        {(["value", "anomaly"] as const).map((v) => (
          <button key={v} type="button" aria-pressed={view === v} onClick={() => setView(v)}
            className={`rounded px-2 py-1 ${view === v ? "bg-white/20" : "bg-white/5 text-gray-400 hover:bg-white/10"}`}>
            {t(v === "value" ? "matrixValue" : "matrixAnomaly")}
          </button>
        ))}
        {view === "anomaly" && (
          <span className="ml-3 flex flex-wrap items-center gap-2 text-[11px] text-gray-400">
            {(Object.keys(ANOMALY_COLORS) as (keyof typeof ANOMALY_COLORS)[]).map((k) => (
              <span key={k} className="flex items-center gap-1">
                <span className="h-3 w-3 rounded-sm" style={{ background: ANOMALY_COLORS[k] }} />
                {t(`anomaly.${k}` as MessageKey)}
              </span>
            ))}
          </span>
        )}
      </div>
      <div className="overflow-x-auto">
        <EChart
          option={option}
          pngName={pngName}
          pngTitle={t("downloadPng")}
          className="w-full min-w-[560px]"
          style={{ height: 40 + rows * 16 }}
        />
      </div>
    </div>
  );
}

function SeasonalityChart({
  season, cal, metric, year, locale, t, pngName,
}: {
  season: SeasonData; cal: CalendarData | null; metric: Metric; year: number; locale: Locale; t: T; pngName: string;
}) {
  const option = useMemo<EChartsOption>(() => {
    const clim = season.climatology;
    const x = clim.map((c) => doyToIso(MEAN_DISPLAY_YEAR, c.doy).slice(5));
    const months = monthNames(locale);
    const series: EChartsOption["series"] = [
      { name: "p10", type: "line", data: clim.map((c) => c.p10), stack: "band", symbol: "none", lineStyle: { opacity: 0 } },
      { name: t("climBand"), type: "line", data: clim.map((c) => c.p90 - c.p10), stack: "band", symbol: "none", lineStyle: { opacity: 0 }, areaStyle: { color: "rgba(156,163,175,0.25)" }, itemStyle: { color: "rgba(156,163,175,0.5)" } },
      { name: t("medianShort"), type: "line", data: clim.map((c) => c.median), symbol: "none", lineStyle: { color: "#9ca3af", width: 1.5 }, itemStyle: { color: "#9ca3af" } },
    ];
    if (cal) {
      const vals = cal.days.map((d) => (d[`level_${metric}`] === null ? null : ((d[metric] as number | undefined) ?? 0)));
      const smooth = movingAverage(vals, 7);
      const byMd = new Map(cal.days.map((d, i) => [d.date.slice(5), smooth[i]]));
      series.push({ name: String(year), type: "line", data: x.map((md) => byMd.get(md) ?? null), symbol: "none", lineStyle: { color: "#f43f5e", width: 2 }, itemStyle: { color: "#f43f5e" } });
    }
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis", valueFormatter: (v) => (typeof v === "number" ? formatNumber(v, locale, 1) : "–") },
      legend: { top: 0, left: 0, textStyle: { color: "#d1d5db" }, data: [t("medianShort"), t("climBand"), ...(cal ? [String(year)] : [])] },
      grid: { left: 48, right: 12, top: 32, bottom: 28 },
      xAxis: { type: "category", data: x, axisLabel: { interval: (i: number) => x[i].endsWith("-01"), formatter: (v: string) => months[Number(v.slice(0, 2)) - 1] } },
      yAxis: { type: "value", splitLine: { lineStyle: { color: "#1f2937" } }, axisLabel: { formatter: (v: number) => formatNumber(v, locale) } },
      series,
    };
  }, [season, cal, metric, year, locale, t]);
  return <EChart option={option} pngName={pngName} pngTitle={t("downloadPng")} className="h-64 w-full" />;
}

function TrendChart({
  season, year, locale, t, pngName,
}: {
  season: SeasonData; year: number | null; locale: Locale; t: T; pngName: string;
}) {
  const option = useMemo<EChartsOption>(() => {
    const complete = season.years.filter((y) => y.complete);
    const tr = season.trend;
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis", valueFormatter: (v) => (typeof v === "number" ? formatNumber(v, locale) : "–") },
      grid: { left: 56, right: 12, top: 36, bottom: 28 },
      title: tr
        ? {
            text: `${t("trendText").replace("{pct}", `${tr.pct_per_decade && tr.pct_per_decade > 0 ? "+" : ""}${tr.pct_per_decade ?? "–"}`).replace("{p}", String(tr.p_value))} · ${tr.p_value < 0.05 ? t("trendSignificant") : t("trendNotSignificant")}`,
            textStyle: { color: "#d1d5db", fontSize: 11, fontWeight: "normal" },
            top: 0, left: 0,
          }
        : undefined,
      xAxis: { type: "category", data: complete.map((y) => String(y.year)) },
      yAxis: { type: "value", splitLine: { lineStyle: { color: "#1f2937" } }, axisLabel: { formatter: (v: number) => formatNumber(v, locale) } },
      series: [
        { name: t("annualTotal"), type: "bar", data: complete.map((y) => ({ value: Math.round(y.total), itemStyle: { color: y.year === year ? "#f43f5e" : "#fb923c" } })) },
        ...(tr
          ? [{ name: "Theil–Sen", type: "line" as const, data: complete.map((y) => Math.round(tr.intercept + tr.slope_per_year * y.year)), symbol: "none", lineStyle: { color: "#e5e7eb", type: "dashed" as const } }]
          : []),
      ],
    };
  }, [season, year, locale, t]);
  return <EChart option={option} pngName={pngName} pngTitle={t("downloadPng")} className="h-64 w-full" />;
}

function MonthlyChart({
  matrix, year, compareYear, locale, t, pngName,
}: {
  matrix: MatrixData; year: number | null; compareYear: number; locale: Locale; t: T; pngName: string;
}) {
  const option = useMemo<EChartsOption>(() => {
    const valuesOf = (y: number) =>
      Array.from({ length: 12 }, (_, m) => matrix.cells.find((c) => c.year === y && c.month === m + 1)?.value ?? null);
    const series: EChartsOption["series"] = [];
    if (year !== null) series.push({ name: String(year), type: "bar", data: valuesOf(year), itemStyle: { color: "#f43f5e" } });
    if (compareYear !== year) series.push({ name: String(compareYear), type: "bar", data: valuesOf(compareYear), itemStyle: { color: "#60a5fa" } });
    series.push({
      name: `${t("medianShort")} (${matrix.base_years[0]}–${matrix.base_years[1]})`,
      type: "line", data: matrix.monthly_median, lineStyle: { color: "#9ca3af" }, itemStyle: { color: "#9ca3af" },
    });
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis", valueFormatter: (v) => (typeof v === "number" ? formatNumber(v, locale, 1) : "–") },
      legend: { top: 0, left: 0, textStyle: { color: "#d1d5db" } },
      grid: { left: 56, right: 12, top: 32, bottom: 28 },
      xAxis: { type: "category", data: monthNames(locale) },
      yAxis: { type: "value", splitLine: { lineStyle: { color: "#1f2937" } }, axisLabel: { formatter: (v: number) => formatNumber(v, locale) } },
      series,
    };
  }, [matrix, year, compareYear, locale, t]);
  return <EChart option={option} pngName={pngName} pngTitle={t("downloadPng")} className="h-64 w-full" />;
}
