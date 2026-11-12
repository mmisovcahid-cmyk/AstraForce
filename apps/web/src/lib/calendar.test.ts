import { describe, expect, it } from "vitest";
import {
  doyToIso,
  formatDate,
  isLeapYear,
  LEVEL_COLORS,
  monthNames,
  movingAverage,
  weekdayNames,
} from "./calendar";
import { parseIntParam } from "./url";

describe("calendar helpers", () => {
  it("has one colour per level 0..4", () => {
    expect(LEVEL_COLORS).toHaveLength(5);
  });

  it("localises month and weekday names (weekdays start on Sunday)", () => {
    expect(monthNames("en")[0]).toBe("Jan");
    expect(monthNames("az")[6]).toBe("İyl");
    expect(monthNames("az", "long")[6]).toBe("İyul");
    expect(weekdayNames("az")).toHaveLength(7);
    expect(weekdayNames("en")[0]).toBe("Sun");
    expect(weekdayNames("en")[1]).toBe("Mon");
  });

  it("maps day-of-year to dates in leap and normal years", () => {
    expect(doyToIso(2024, 60)).toBe("2024-02-29");
    expect(doyToIso(2025, 60)).toBe("2025-03-01");
    expect(doyToIso(2024, 366)).toBe("2024-12-31");
    expect(isLeapYear(2000)).toBe(true);
    expect(isLeapYear(2100)).toBe(false);
  });

  it("smooths with a centred window and keeps gaps", () => {
    expect(movingAverage([0, 0, 7, 0, 0], 7)).toEqual([1.75, 1.4, 7 / 5, 1.4, 1.75]);
    expect(movingAverage([1, null, 3], 3)).toEqual([1, null, 3]);
  });

  it("formats dates in UTC", () => {
    expect(formatDate("2021-07-29", "en")).toBe("29 July 2021");
    expect(formatDate("2021-07-29", "en", false)).toBe("29 July");
    expect(formatDate("2021-07-29", "az")).toBe("29 İyul 2021");
  });

  it("parses only in-range integer URL params", () => {
    expect(parseIntParam("2021", 2000, 2026)).toBe(2021);
    expect(parseIntParam("1999", 2000, 2026)).toBeNull();
    expect(parseIntParam("20x1", 2000, 2026)).toBeNull();
    expect(parseIntParam(null, 2000, 2026)).toBeNull();
  });
});
