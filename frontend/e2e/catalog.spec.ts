import { resolve } from "node:path";

import { expect, test } from "@playwright/test";

import { signIn } from "./support";

for (const [name, width, height, theme] of [
  ["desktop", 1440, 900, "light"],
  ["mobile", 390, 844, "dark"],
] as const) {
  test(`an Admin adds a persistent service on ${name}`, async ({ page, request }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => { errors.push(error.message); });
    try {
      await signIn(page, "admin", "/catalog");
      await page.setViewportSize({ width, height });
      await page.evaluate((mode) => {
        document.documentElement.dataset.theme = mode;
      }, theme);
      await page.getByRole("button", { name: "Add Service", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "Add Service" });
      await expect(dialog.getByLabel("Service name")).toBeFocused();
      if (process.env.CATALOG_SCREENSHOTS) {
        await page.screenshot({ path: resolve(`../.tmp/catalog-add-${name}.png`) });
      }
      for (const [label, value] of [
        ["Service name", "orders-service"],
        ["Repository URL", "https://github.com/haiderali-dev/payment-service.git"],
        ["Build command", "./scripts/build.sh"],
        ["Suite 1 command", "./scripts/test.sh unit"],
        ["Deploy command", "./deploy.sh staging"],
        ["Staging URL", "http://localhost:9003"],
      ] as const) {
        await dialog.getByLabel(label, { exact: true }).fill(value);
      }
      await dialog.getByRole("button", { name: "Add service", exact: true }).click();
      await expect(dialog).not.toBeVisible();
      await expect(page.getByRole("heading", { name: "orders-service", exact: true })).toBeVisible();
      await page.reload();
      await expect(page.getByRole("heading", { name: "orders-service", exact: true })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      expect(errors).toEqual([]);
    } finally {
      const reset = await request.post(`${process.env.E2E_BACKEND_URL}/__e2e/catalog/reset`);
      expect(reset.ok()).toBe(true);
    }
  });
}
