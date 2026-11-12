// Tarihler "YYYY-MM-DD" (UTC) dizgeleri olarak tutulur; FIRMS tarihleri de UTC'dir.

export function addDays(isoDate: string, days: number): string {
  const d = new Date(`${isoDate}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export function todayUtc(now: Date = new Date()): string {
  return now.toISOString().slice(0, 10);
}

/** `endDate` dahil, geriye doğru `days` günlük aralık. */
export function rangeEndingOn(endDate: string, days: number): { dateFrom: string; dateTo: string } {
  return { dateFrom: addDays(endDate, -(days - 1)), dateTo: endDate };
}

export const RANGE_OPTIONS = [1, 7, 30] as const;
export type RangeDays = (typeof RANGE_OPTIONS)[number];
