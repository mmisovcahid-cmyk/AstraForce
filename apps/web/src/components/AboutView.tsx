"use client";

import { useEffect, useState } from "react";
import { API_URL } from "@/lib/api";
import { formatNumber } from "@/lib/calendar";
import type { Locale, MessageKey } from "@/lib/i18n";
import { useLocale } from "@/lib/useLocale";
import { AppHeader } from "./AppHeader";

type TargetMetrics = {
  method: string;
  mean_abs_annual_bias_pct: number;
  daily_r: number | null;
  weekly_r: number | null;
  mean_season_shift_days: number | null;
  uncalibrated_bias_pct: number | null;
};
type Summary = {
  countries: Record<string, { version: string; det?: TargetMetrics; evt?: TargetMetrics }>;
  detections: number;
};

// Uzun metin: sözlük yerine burada, iki dilde.
const CONTENT: Record<
  Locale,
  {
    title: string;
    lead: string;
    problemTitle: string;
    problem: string[];
    dataTitle: string;
    data: string[];
    methodTitle: string;
    method: [string, string][];
    validationTitle: string;
    validationIntro: string;
    cols: string[];
    metricsTitle: string;
    metrics: [string, string][];
    limitsTitle: string;
    limits: string[];
    creditsTitle: string;
    credits: string;
  }
> = {
  en: {
    title: "How AstraForce harmonizes MODIS and VIIRS",
    lead: "A burning activity calendar is only useful if 2005 can be compared with 2025. AstraForce turns 25 years of NASA FIRMS hotspots from two sensor families into one consistent series, so the sensor of origin no longer matters.",
    problemTitle: "The problem",
    problem: [
      "MODIS (Terra 2000–, Aqua 2002–) sees 1 km pixels; VIIRS (S-NPP 2012–, NOAA-20 2018–, NOAA-21 2023–) sees 375 m pixels and many small fires MODIS misses: about 2–3× more hotspots for the same fires.",
      "Simply joining the two records creates a false increase after 2012. MODIS is near the end of its life and its orbits are drifting (Aqua now passes ~2 h later than in 2019), so a single fixed conversion factor is not enough.",
    ],
    dataTitle: "Data",
    data: [
      "NASA FIRMS active fire hotspots: MODIS C6.1 and VIIRS 375 m (S-NPP, NOAA-20, NOAA-21), standard processing (SP) plus near-real-time (NRT) for the latest days.",
      "Yearly country archives for 2000 → last year; the FIRMS API for the current year (SP where available, NRT after). NRT days are marked provisional and replaced when SP is published.",
      "Updated daily by an automatic job.",
    ],
    methodTitle: "Method",
    method: [
      ["Cleaning", "Keep nominal/high confidence. Remove static thermal sources (gas flares, industry): NASA type=2 cells plus cells hot on >100 days in ≥5 years, dilated by one H3 ring. In Türkiye ~25 % of VIIRS hotspots are static sources (MODIS ~3 %)."],
      ["Satellite-aware averaging", "A day's VIIRS value is the mean of the VIIRS satellites that delivered data that day, so a satellite outage or a newly launched satellite does not create jumps. MODIS before Aqua (2000–2002) is scaled by the regional (Terra+Aqua)/Terra ratio."],
      ["Fire events", "ST-DBSCAN (1.5 km, 1 day) merges neighbouring pixels into fire events, giving a second, pixel-size-independent metric."],
      ["Calibration", "On the 2012–2025 overlap, four candidate models per country and metric compete: no calibration, monthly ratio over a rolling ±2-year window (tracks orbit drift), log-linear regression and Random Forest."],
      ["Model selection", "Leave-one-year-out validation: each year is predicted by a model that never saw it. The lowest mean |annual bias| wins."],
      ["Any area", "The winning model yields a country × day factor (harmonized ÷ VIIRS). The same factor is applied to every H3 cell and every user-drawn area, so an area's total equals the sum of its parts."],
    ],
    validationTitle: "Validation (live, harmonized hotspot count)",
    validationIntro: "Leave-one-year-out results of the selected model. The last column shows the error if VIIRS were used without calibration.",
    cols: ["Country", "Model", "Mean |annual bias|", "Daily r", "Weekly r", "Season shift", "Uncalibrated"],
    metricsTitle: "Metrics in the app",
    metrics: [
      ["Hotspots", "Harmonized hotspot count (MODIS-equivalent). The default; answers \"how much burning was detected\"."],
      ["Fire events", "Neighbouring pixels count as one fire (event-days); highlights many small fires such as agricultural burns."],
      ["Fire power (FRP)", "Fire radiative power in MW; highlights a few large, intense fires such as forest fires."],
      ["Anomaly", "Difference from the 2001–last year median of the same month (or the same days of the month so far)."],
    ],
    limitsTitle: "Limitations",
    limits: [
      "Areas must lie inside the loaded countries; any other country can be added with one ingest + harmonize command.",
      "Calibration is per country; small areas inherit their country's daily factors. Daily values are noisier than weekly ones (weekly r ≈ 0.95–0.99).",
      "Satellite hotspots are not burned area: thick smoke, clouds and overpass timing can hide fires.",
    ],
    creditsTitle: "Credits",
    credits: "Hotspots: NASA FIRMS (MODIS C6.1, VIIRS 375 m). Land cover overlay: NASA GIBS (MODIS MCD12Q1). Boundaries: Natural Earth. Base map: OpenFreeMap © OpenStreetMap contributors. Built for the NASA Space Apps Challenge 2026.",
  },
  az: {
    title: "AstraForce MODIS və VIIRS-i necə harmonizə edir",
    lead: "Yanğın təqvimi yalnız 2005-i 2025 ilə müqayisə etmək mümkün olduqda faydalıdır. AstraForce NASA FIRMS-in iki sensor ailəsinin 25 illik isti nöqtələrini vahid seriyaya çevirir: mənbə sensorun artıq əhəmiyyəti yoxdur.",
    problemTitle: "Problem",
    problem: [
      "MODIS (Terra 2000–, Aqua 2002–) 1 km piksellə, VIIRS (S-NPP 2012–, NOAA-20 2018–, NOAA-21 2023–) 375 m piksellə görür və MODIS-in görmədiyi çoxlu kiçik yanğını aşkarlayır: eyni yanğınlar üçün təxminən 2–3 dəfə çox isti nöqtə.",
      "İki seriyanı sadəcə birləşdirmək 2012-dən sonra yalançı artım yaradır. MODIS ömrünün sonundadır və orbitləri sürüşür (Aqua indi 2019-a nisbətən ~2 saat gec keçir), ona görə tək sabit əmsal kifayət deyil.",
    ],
    dataTitle: "Məlumat",
    data: [
      "NASA FIRMS aktiv yanğın isti nöqtələri: MODIS C6.1 və VIIRS 375 m (S-NPP, NOAA-20, NOAA-21), standart emal (SP) və son günlər üçün real vaxta yaxın (NRT).",
      "2000 → keçən il üçün illik ölkə arxivləri; cari il üçün FIRMS API. NRT günləri müvəqqəti işarələnir və SP dərc olunanda əvəzlənir.",
      "Avtomatik iş ilə hər gün yenilənir.",
    ],
    methodTitle: "Metod",
    method: [
      ["Təmizləmə", "Nominal/yüksək etibarlılıq saxlanılır. Sabit istilik mənbələri (qaz məşəlləri, sənaye) çıxarılır: NASA type=2 hüceyrələri və ≥5 ildə >100 gün isti olan hüceyrələr, bir H3 halqası ilə genişləndirilmiş. Türkiyədə VIIRS nöqtələrinin ~25 %-i sabit mənbədir (MODIS ~3 %)."],
      ["Peyk ortalaması", "Günün VIIRS dəyəri həmin gün məlumat verən VIIRS peyklərinin ortalamasıdır; peyk fasiləsi və ya yeni peyk sıçrayış yaratmır. Aqua-dan əvvəlki MODIS (2000–2002) regional (Terra+Aqua)/Terra nisbəti ilə miqyaslanır."],
      ["Yanğın hadisələri", "ST-DBSCAN (1,5 km, 1 gün) qonşu pikselləri yanğın hadisəsinə birləşdirir: piksel ölçüsündən asılı olmayan ikinci göstərici."],
      ["Kalibrasiya", "2012–2025 üst-üstə düşən dövrdə hər ölkə və göstərici üçün dörd model yarışır: kalibrasiyasız, sürüşən ±2 illik pəncərədə aylıq nisbət (orbit sürüşməsini izləyir), log-xətti reqressiya və Random Forest."],
      ["Modelin seçilməsi", "İldən-kənar yoxlama: hər il onu görməmiş modellə proqnozlaşdırılır. Ən kiçik orta |illik sapma| qalib gəlir."],
      ["İstənilən ərazi", "Qalib model ölkə × gün əmsalı verir (harmonizə ÷ VIIRS). Eyni əmsal bütün H3 hüceyrələrinə və istifadəçinin çəkdiyi ərazilərə tətbiq olunur: ərazinin cəmi hissələrinin cəminə bərabərdir."],
    ],
    validationTitle: "Yoxlama (canlı, harmonizə isti nöqtə sayı)",
    validationIntro: "Seçilmiş modelin ildən-kənar nəticələri. Son sütun VIIRS kalibrasiyasız istifadə edilsəydi xətanı göstərir.",
    cols: ["Ölkə", "Model", "Orta |illik sapma|", "Günlük r", "Həftəlik r", "Mövsüm sürüşməsi", "Kalibrasiyasız"],
    metricsTitle: "Tətbiqdəki göstəricilər",
    metrics: [
      ["İsti nöqtələr", "Harmonizə isti nöqtə sayı (MODIS ekvivalenti). Əsas göstərici."],
      ["Yanğın hadisələri", "Qonşu piksellər bir yanğın sayılır (hadisə-gün); kənd təsərrüfatı kimi çoxlu kiçik yanğınları önə çıxarır."],
      ["Yanğın gücü (FRP)", "MVt ilə radiasiya gücü; meşə yanğınları kimi az sayda böyük yanğınları önə çıxarır."],
      ["Anomaliya", "Eyni ayın 2001–keçən il medianından fərq (və ya ayın indiyədək olan eyni günlərinin)."],
    ],
    limitsTitle: "Məhdudiyyətlər",
    limits: [
      "Ərazilər yüklənmiş ölkələrin daxilində olmalıdır; istənilən ölkə bir əmrlə əlavə edilə bilər.",
      "Kalibrasiya ölkə səviyyəsindədir; kiçik ərazilər ölkənin gündəlik əmsallarını alır. Gündəlik dəyərlər həftəliklərdən daha səs-küylüdür (həftəlik r ≈ 0,95–0,99).",
      "Peyk isti nöqtələri yanmış sahə deyil: qalın tüstü, bulud və keçid vaxtı yanğınları gizlədə bilər.",
    ],
    creditsTitle: "Mənbələr",
    credits: "İsti nöqtələr: NASA FIRMS (MODIS C6.1, VIIRS 375 m). Torpaq örtüyü qatı: NASA GIBS (MODIS MCD12Q1). Sərhədlər: Natural Earth. Xəritə: OpenFreeMap © OpenStreetMap. NASA Space Apps Challenge 2026 üçün hazırlanıb.",
  },
};

const METHOD_LABEL: Record<string, string> = {
  ratio: "Monthly ratio",
  loglinear: "Log-linear",
  random_forest: "Random Forest",
};

export function AboutView() {
  const { locale, setLocale, t } = useLocale();
  const [summary, setSummary] = useState<Summary | null>(null);
  const c = CONTENT[locale];

  useEffect(() => {
    const ctrl = new AbortController();
    fetch(`${API_URL}/harmonized/summary`, { signal: ctrl.signal })
      .then((r) => (r.ok ? r.json() : null))
      .then(setSummary)
      .catch(() => {});
    return () => ctrl.abort();
  }, []);

  const pct = (v: number | null | undefined) => (v == null ? "–" : `${formatNumber(v, locale, 1)} %`);
  return (
    <div className="min-h-screen">
      <AppHeader active="/about" t={t} locale={locale} setLocale={setLocale} />
      <main className="mx-auto max-w-3xl space-y-8 px-4 py-8 text-sm leading-relaxed text-gray-300">
        <header className="space-y-3">
          <h1 className="text-2xl font-semibold text-fire-200">{c.title}</h1>
          <p className="text-base text-gray-200">{c.lead}</p>
          {summary && (
            <p className="text-xs text-gray-500">
              {t("hotspotsN").replace("{n}", formatNumber(summary.detections, locale))} ·{" "}
              {t("countriesN").replace("{n}", String(Object.keys(summary.countries).length))} ·{" "}
              {Object.values(summary.countries)[0]?.version.split(":")[0]}
            </p>
          )}
        </header>

        <Section title={c.problemTitle}>
          {c.problem.map((p) => <p key={p}>{p}</p>)}
        </Section>

        <Section title={c.dataTitle}>
          <ul className="list-disc space-y-1 pl-5">{c.data.map((d) => <li key={d}>{d}</li>)}</ul>
        </Section>

        <Section title={c.methodTitle}>
          <ol className="space-y-3">
            {c.method.map(([h, body], i) => (
              <li key={h} className="flex gap-3">
                <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-fire-600 text-xs font-semibold text-white">
                  {i + 1}
                </span>
                <div>
                  <b className="text-gray-100">{h}.</b> {body}
                </div>
              </li>
            ))}
          </ol>
        </Section>

        <Section title={c.validationTitle}>
          <p>{c.validationIntro}</p>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-left text-xs">
              <thead className="text-gray-400">
                <tr>{c.cols.map((h) => <th key={h} className="py-1 pr-3 font-normal">{h}</th>)}</tr>
              </thead>
              <tbody className="tabular-nums">
                {summary
                  ? Object.entries(summary.countries).map(([cc, v]) => (
                      <tr key={cc} className="border-t border-white/5">
                        <td className="py-1 pr-3">{t(`region.${cc}` as MessageKey)}</td>
                        <td className="py-1 pr-3">{v.det ? (METHOD_LABEL[v.det.method] ?? v.det.method) : "–"}</td>
                        <td className="py-1 pr-3 font-semibold text-gray-100">{pct(v.det?.mean_abs_annual_bias_pct)}</td>
                        <td className="py-1 pr-3">{v.det?.daily_r ?? "–"}</td>
                        <td className="py-1 pr-3">{v.det?.weekly_r ?? "–"}</td>
                        <td className="py-1 pr-3">{v.det?.mean_season_shift_days ?? "–"} {t("days")}</td>
                        <td className="py-1 pr-3 text-gray-500">{pct(v.det?.uncalibrated_bias_pct)}</td>
                      </tr>
                    ))
                  : (
                    <tr><td className="py-2 text-gray-500">{t("loading")}</td></tr>
                  )}
              </tbody>
            </table>
          </div>
          <a href="/validation" className="inline-block text-fire-200 underline">{t("nav.validation")} →</a>
        </Section>

        <Section title={c.metricsTitle}>
          <dl className="space-y-2">
            {c.metrics.map(([k, v]) => (
              <div key={k}>
                <dt className="font-semibold text-gray-100">{k}</dt>
                <dd>{v}</dd>
              </div>
            ))}
          </dl>
        </Section>

        <Section title={c.limitsTitle}>
          <ul className="list-disc space-y-1 pl-5">{c.limits.map((d) => <li key={d}>{d}</li>)}</ul>
        </Section>

        <Section title={c.creditsTitle}>
          <p className="text-xs text-gray-400">{c.credits}</p>
        </Section>
      </main>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold text-gray-100">{title}</h2>
      {children}
    </section>
  );
}
