import type { Locale } from "./i18n";

// Düzey 0 = yangın yok, 1..4 = alanın 20 yıllık yangınlı günlerine göre p50/p80/p95 dilimleri.
// İki rampa: "fire" (sarı→koyu kırmızı) ve "cividis" (renk körlüğüne uygun, mavi→sarı).
// İkisinde de açıklık düzeyle tekdüze değişir; renk ayırt edilemese bile sıra okunur.
export type RampName = "fire" | "cividis";
export const RAMPS: Record<RampName, readonly string[]> = {
  fire: ["#1f2937", "#fde68a", "#fb923c", "#dc2626", "#7f1d1d"],
  cividis: ["#1f2937", "#3b4f8a", "#7c7b78", "#bcaf6f", "#fee838"],
};
/** Geriye uyumluluk: varsayılan rampa. */
export const LEVEL_COLORS = RAMPS.fire;
export const NO_DATA_COLOR = "#111827";

// Tarihsel medyana göre anomali: ıraksak, renk körlüğüne uygun (mavi = az, kırmızı = çok)
export const ANOMALY_COLORS = {
  much_below: "#2166ac",
  below: "#67a9cf",
  normal: "#d1d5db",
  above: "#ef8a62",
  much_above: "#b2182b",
} as const;

export type Metric = "hotspots" | "events" | "frp";
export const METRICS: Metric[] = ["hotspots", "events", "frp"];

// Azerbaycanca adlar sabit: tarayıcıların çoğunda (ör. Chromium) Intl'de "az" ay/gün
// verisi yok ve "M01", "Mon" gibi yedeklere düşüyor.
const AZ_MONTHS_LONG = [
  "Yanvar", "Fevral", "Mart", "Aprel", "May", "İyun",
  "İyul", "Avqust", "Sentyabr", "Oktyabr", "Noyabr", "Dekabr",
];
const AZ_MONTHS_SHORT = [
  "Yan", "Fev", "Mar", "Apr", "May", "İyn", "İyl", "Avq", "Sen", "Okt", "Noy", "Dek",
];
// Bazar, Bazar ertəsi, Çərşənbə axşamı, Çərşənbə, Cümə axşamı, Cümə, Şənbə
const AZ_WEEKDAYS = ["B.", "B.e.", "Ç.a.", "Ç.", "C.a.", "C.", "Ş."];

export function monthNames(locale: Locale, style: "short" | "long" = "short"): string[] {
  if (locale === "az") return style === "long" ? AZ_MONTHS_LONG : AZ_MONTHS_SHORT;
  const f = new Intl.DateTimeFormat("en-GB", { month: style, timeZone: "UTC" });
  return Array.from({ length: 12 }, (_, m) => f.format(new Date(Date.UTC(2024, m, 15))));
}

/** Pazar'dan başlayan kısa gün adları (ECharts calendar nameMap bu sırayı ister). */
export function weekdayNames(locale: Locale): string[] {
  if (locale === "az") return AZ_WEEKDAYS;
  const f = new Intl.DateTimeFormat("en-GB", { weekday: "short", timeZone: "UTC" });
  // 2024-01-07 bir Pazar
  return Array.from({ length: 7 }, (_, i) => f.format(new Date(Date.UTC(2024, 0, 7 + i))));
}

export function formatDate(iso: string, locale: Locale, withYear = true): string {
  const [y, m, d] = iso.split("-").map(Number);
  const month = monthNames(locale, "long")[m - 1];
  return withYear ? `${d} ${month} ${y}` : `${d} ${month}`;
}

export function formatNumber(v: number, locale: Locale, digits = 0): string {
  // az: binlik ayırıcı boşluk, ondalık virgül (Azərbaycan yazımı)
  return v.toLocaleString(locale === "az" ? "ru-RU" : "en-US", { maximumFractionDigits: digits });
}

/** Yılın günü (1..366) → o yılın tarihi. */
export function doyToIso(year: number, doy: number): string {
  const d = new Date(Date.UTC(year, 0, 1));
  d.setUTCDate(d.getUTCDate() + Math.round(doy) - 1);
  return d.toISOString().slice(0, 10);
}

/** Merkezli kayan ortalama (kenarlarda mevcut değerlerle). null değerler atlanır. */
export function movingAverage(values: (number | null)[], window = 7): (number | null)[] {
  const half = Math.floor(window / 2);
  return values.map((_, i) => {
    let sum = 0;
    let n = 0;
    for (let j = i - half; j <= i + half; j++) {
      const v = values[j];
      if (v !== null && v !== undefined) {
        sum += v;
        n++;
      }
    }
    return n && values[i] !== null ? sum / n : null;
  });
}

export function isLeapYear(y: number): boolean {
  return (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
}
