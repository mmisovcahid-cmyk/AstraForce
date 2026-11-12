import { describe, expect, it } from "vitest";
import { addDays, rangeEndingOn, todayUtc } from "./dates";

describe("dates", () => {
  it("adds days across month and leap-year boundaries", () => {
    expect(addDays("2024-02-28", 1)).toBe("2024-02-29");
    expect(addDays("2024-03-01", -1)).toBe("2024-02-29");
    expect(addDays("2025-12-31", 1)).toBe("2026-01-01");
  });

  it("builds an inclusive range ending on the given day", () => {
    expect(rangeEndingOn("2026-08-07", 7)).toEqual({ dateFrom: "2026-08-01", dateTo: "2026-08-07" });
    expect(rangeEndingOn("2026-08-07", 1)).toEqual({ dateFrom: "2026-08-07", dateTo: "2026-08-07" });
  });

  it("formats today in UTC", () => {
    expect(todayUtc(new Date("2026-11-12T23:30:00-05:00"))).toBe("2026-11-13");
  });
});
