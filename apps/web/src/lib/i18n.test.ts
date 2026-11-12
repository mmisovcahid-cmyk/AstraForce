import { describe, expect, it } from "vitest";
import { isLocale, LOCALES, messages, translate } from "./i18n";
import { REGIONS } from "./regions";

describe("i18n", () => {
  it("every locale has the same keys and no empty strings", () => {
    const azKeys = Object.keys(messages.az).sort();
    for (const l of LOCALES) {
      expect(Object.keys(messages[l]).sort()).toEqual(azKeys);
      for (const v of Object.values(messages[l])) expect(v.trim()).not.toBe("");
    }
  });

  it("has a translated name for every region", () => {
    for (const r of REGIONS) {
      expect(translate("az", `region.${r.id}`)).toBeTruthy();
      expect(translate("en", `region.${r.id}`)).toBeTruthy();
    }
  });

  it("recognises only supported locales", () => {
    expect(isLocale("az")).toBe(true);
    expect(isLocale("tr")).toBe(false);
    expect(isLocale(null)).toBe(false);
  });
});

describe("regions", () => {
  it("bboxes are valid [west, south, east, north]", () => {
    for (const { bbox } of REGIONS) {
      const [w, s, e, n] = bbox;
      expect(w).toBeLessThan(e);
      expect(s).toBeLessThan(n);
      expect(Math.abs(s)).toBeLessThanOrEqual(90);
      expect(Math.abs(w)).toBeLessThanOrEqual(180);
    }
  });
});
