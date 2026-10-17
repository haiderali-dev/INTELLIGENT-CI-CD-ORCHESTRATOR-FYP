import { expect, test } from "@playwright/test";

import { rankingWithHighAboveLow, reset, setRanking, signIn } from "./support";

test.beforeEach(async ({ request }) => {
  await reset(request);
});

test.describe("the queue", () => {
  test("shows a HIGH job above a LOW job, in the plugin's order", async ({ page, request }) => {
    await setRanking(request, rankingWithHighAboveLow());
    await signIn(page, "developer", "/queue");

    const table = page.getByRole("table", { name: "Waiting jobs, ranked by score, highest first" });
    const rows = table.getByRole("row");
    await expect(rows).toHaveCount(4);
    await expect(rows.nth(1).getByRole("rowheader")).toHaveText("it-revision-freestyle");
    await expect(rows.nth(1)).toContainText("HIGH");
    await expect(rows.nth(3).getByRole("rowheader")).toHaveText("it-failure-payment-service-test-unit");
    await expect(rows.nth(3)).toContainText("LOW");
    await expect(rows.nth(3).getByRole("img", { name: /^Score 0\.150: urgency 0\.150/ })).toBeVisible();
    await expect(page.getByRole("list", { name: "Queue status" })).toContainText("3 waiting");
  });

  test("says the ranking is unavailable, and why, when the plugin cannot be read", async ({
    page,
    request,
  }) => {
    await setRanking(request, { unavailable_reason: "the plugin is not installed on this controller" });
    await signIn(page, "developer", "/queue");

    await expect(page.getByRole("heading", { name: "Ranking unavailable" })).toBeVisible();
    await expect(
      page.getByText(
        "The backend could not read the queue optimizer plugin: the plugin is not installed on this controller.",
      ),
    ).toBeVisible();
  });
});
