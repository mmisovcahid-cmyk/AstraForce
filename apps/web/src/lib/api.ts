import type { FeatureCollection, MultiPolygon, Point, Polygon } from "geojson";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Health = {
  status: "ok" | "degraded";
  database: { ok: boolean; postgis?: string; h3?: string; error?: string };
  firms_key_configured: boolean;
};

export type DetectionProps = {
  source: "MODIS" | "VIIRS_SNPP" | "VIIRS_NOAA20" | string;
  product: "SP" | "NRT";
  acq_ts: string;
  frp: number | null;
  confidence: 0 | 1 | 2;
  daynight: "D" | "N" | null;
};

export type Detections = FeatureCollection<Point, DetectionProps> & {
  meta: { total: number; returned: number; truncated: boolean; by_source: Record<string, number> };
};

export async function fetchDetections(
  params: { country: string; dateFrom: string; dateTo: string },
  signal?: AbortSignal,
): Promise<Detections> {
  const q = new URLSearchParams({
    country: params.country,
    date_from: params.dateFrom,
    date_to: params.dateTo,
  });
  const res = await fetch(`${API_URL}/detections?${q}`, { signal, cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export type ModelMetrics = {
  mean_abs_annual_bias_pct: number;
  annual_bias_pct: Record<string, number>;
  daily_r: number | null;
  weekly_r: number | null;
  daily_mae: number;
  mean_season_shift_days: number | null;
  test_days: number;
};

export type Validation = {
  country: string;
  target: "det" | "evt";
  model_version: string;
  candidates: { method: string; selected: boolean; metrics: ModelMetrics }[];
  years: {
    year: number;
    modis_det: number | null;
    viirs_det: number | null;
    modis_evt: number | null;
    viirs_evt: number | null;
    hfi: number | null;
    hfi_det: number | null;
  }[];
};

export async function fetchValidation(
  country: string,
  target: "det" | "evt",
  signal?: AbortSignal,
): Promise<Validation> {
  return getJson(`/harmonized/validation?country=${country}&target=${target}`, signal);
}

/** Bölge hâlâ hesaplanıyorsa API 202 + {status, progress} döner. */
export class NotReadyError extends Error {
  constructor(
    public status: string,
    public progress: number,
  ) {
    super(`not ready: ${status}`);
  }
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { signal, cache: "no-store" });
  if (res.status === 202) {
    const b = await res.json();
    throw new NotReadyError(b.status, b.progress);
  }
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json();
}

export type Metric = "hotspots" | "events" | "frp";

export type CalendarDay = {
  date: string;
  hotspots: number | null;
  events?: number;
  frp?: number;
  level_hotspots: number | null;
  level_events: number | null;
  level_frp: number | null;
  provisional: boolean;
  modis_det?: number;
  viirs_snpp_det?: number;
  viirs_noaa20_det?: number;
  viirs_noaa21_det?: number;
};

export type CalendarData = {
  area: string;
  mode: "year" | "mean";
  year?: number;
  years?: [number, number];
  thresholds: Record<Metric, number[]>;
  totals?: Record<Metric, number>;
  days: CalendarDay[];
};

export function fetchCalendar(
  area: string,
  sel: { mode: "year"; year: number } | { mode: "mean" },
  signal?: AbortSignal,
): Promise<CalendarData> {
  const q = sel.mode === "year" ? `year=${sel.year}` : "mode=mean";
  return getJson(`/analytics/calendar?area=${area}&${q}`, signal);
}

export type SeasonYear = {
  year: number;
  complete: boolean;
  total: number;
  start: string | null;
  mid: string | null;
  end: string | null;
  peak_week_start: string | null;
  rank: number | null;
  vs_median_pct: number | null;
};

export type SeasonData = {
  area: string;
  metric: Metric;
  base_years: [number, number];
  mean_total: number;
  median_total: number;
  mean_season_doy: Record<"start" | "mid" | "end" | "peak_week_start", number | null>;
  years: SeasonYear[];
  climatology: { doy: number; mean: number; median: number; p10: number; p90: number }[];
  trend: {
    slope_per_year: number;
    intercept: number;
    pct_per_decade: number | null;
    p_value: number;
    years: [number, number];
  } | null;
};

export function fetchSeason(area: string, metric: Metric, signal?: AbortSignal) {
  return getJson<SeasonData>(`/analytics/season?area=${area}&metric=${metric}`, signal);
}

export type AnomalyClass = "much_below" | "below" | "normal" | "above" | "much_above";

export type MatrixCell = {
  year: number;
  month: number;
  value: number;
  median: number;
  anomaly_pct: number | null;
  anomaly_class: AnomalyClass;
  partial: boolean;
  level: number;
};

export type MatrixData = {
  area: string;
  metric: Metric;
  base_years: [number, number];
  monthly_median: number[];
  thresholds: number[];
  cells: MatrixCell[];
};

export function fetchMatrix(area: string, metric: Metric, signal?: AbortSignal) {
  return getJson<MatrixData>(`/analytics/matrix?area=${area}&metric=${metric}`, signal);
}

export type StatusData = {
  as_of: string;
  month: number;
  month_to_date: number;
  month_to_date_median: number;
  month_anomaly_pct: number | null;
  month_anomaly_class: AnomalyClass;
  last7: number;
  last7_median: number;
  last7_anomaly_pct: number | null;
  base_years: [number, number];
  latest_data_day: string | null;
};

export function fetchStatus(area: string, metric: Metric, signal?: AbortSignal) {
  return getJson<StatusData>(`/analytics/status?area=${area}&metric=${metric}`, signal);
}

export type RangeData = {
  /** null: aralığın hiçbir gününün verisi henüz gelmedi */
  total: number | null;
  median: number | null;
  anomaly_pct: number | null;
  fire_days: number;
  date_from: string;
  date_to: string;
  /** Verinin bulunduğu son gün (date_to'dan önceyse aralık oraya kadar hesaplandı) */
  effective_date_to: string | null;
};

export function fetchRange(
  area: string,
  metric: Metric,
  dateFrom: string,
  dateTo: string,
  signal?: AbortSignal,
) {
  return getJson<RangeData>(
    `/analytics/range?area=${area}&metric=${metric}&date_from=${dateFrom}&date_to=${dateTo}`,
    signal,
  );
}

export type CellCollection = FeatureCollection<
  Polygon,
  { h3: string; hotspots: number; hfi: number; frp: number; days: number }
> & { meta: { cells: number; total: number; max: number } };

export function fetchCells(
  params: { area: string; dateFrom: string; dateTo: string },
  signal?: AbortSignal,
) {
  return getJson<CellCollection>(
    `/analytics/cells?area=${params.area}&date_from=${params.dateFrom}&date_to=${params.dateTo}`,
    signal,
  );
}

export type RoiInfo = {
  id: string;
  area: `roi:${string}`;
  name: string | null;
  area_km2: number;
  countries: string[];
  covered_pct: number;
  status: "pending" | "running" | "ready" | "error";
  progress: number;
  error: string | null;
  geometry: MultiPolygon;
  center_lat: number;
  center_lon: number;
  bbox: [number, number, number, number];
};

export async function createRoi(body: {
  geojson?: unknown;
  circle?: { lat: number; lon: number; radius_km: number };
  name?: string;
}): Promise<RoiInfo> {
  const res = await fetch(`${API_URL}/roi`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
  return data;
}

export function fetchRoi(id: string, signal?: AbortSignal) {
  return getJson<RoiInfo>(`/roi/${id}`, signal);
}

/** Hata vermiş bölgenin hesaplamasını yeniden başlatır (hata otomatik yeniden denenmez). */
export async function retryRoi(id: string): Promise<RoiInfo> {
  const res = await fetch(`${API_URL}/roi/${id}/retry`, { method: "POST" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/** İndirme bağlantıları (tarayıcı doğrudan indirir; CSV akış olarak gelir). */
export const exportUrls = {
  hotspots: (area: string, from: string, to: string) =>
    `${API_URL}/export/hotspots.csv?area=${area}&date_from=${from}&date_to=${to}`,
  daily: (area: string, from: string, to: string) =>
    `${API_URL}/export/daily.csv?area=${area}&date_from=${from}&date_to=${to}`,
  matrix: (area: string, metric: Metric) =>
    `${API_URL}/export/matrix.csv?area=${area}&metric=${metric}`,
};

export async function fetchHealth(signal?: AbortSignal): Promise<Health> {
  const res = await fetch(`${API_URL}/health`, { signal, cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
