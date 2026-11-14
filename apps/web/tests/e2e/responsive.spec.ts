import { test, expect } from "@playwright/test";

const VIEWPORTS = [
  { name: "mobile", width: 375, height: 667 },
  { name: "mobile-large", width: 414, height: 896 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "desktop", width: 1280, height: 800 },
];

test.describe("Responsive layout", () => {
  for (const vp of VIEWPORTS) {
    test(`renders on ${vp.name} (${vp.width}x${vp.height})`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto("/");

      // Harita konteyneri her viewport'ta mevcut olmalı
      const map = page.locator('[data-testid="fire-map"]');
      await expect(map).toBeVisible();

      // Ülke seçici her viewport'ta görünür
      const countrySelect = page.locator("select").first();
      await expect(countrySelect).toBeVisible();

      // Sayfa hata ile bozulmamalı (basit bir içerik kontrolü)
      await expect(page.locator("main")).toBeVisible();
    });
  }

  test("map layer toggle buttons are accessible on mobile", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto("/");

    // Panel toggle butonu mobilde görünür
    const toggle = page.locator("button[aria-controls='map-panel']");
    await expect(toggle).toBeVisible();

    // Panel açıldığında layer butonları görünür
    await toggle.click();
    await expect(page.getByRole("button", { name: /Points/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /Density/i })).toBeVisible();
  });

  test("land cover toggle works on mobile", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto("/");

    const toggle = page.locator("button[aria-controls='map-panel']");
    await toggle.click();

    const landCoverLabel = page.getByText(/Land cover|Torpaq örtüy/);
    await expect(landCoverLabel).toBeVisible();
  });
});
