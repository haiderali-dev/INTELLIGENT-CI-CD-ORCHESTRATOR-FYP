import { expect, test } from "@playwright/test";

import { ACCOUNTS, signIn, submitCredentials, submitSignIn } from "./support";

test.describe("signing in", () => {
  test("says exactly what is wrong, lets the person in, and lets them out", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveURL(/\/sign-in$/);

    // Through the real limit of five sign-ins a minute that every flow shares: a 429 is waited out
    // for as long as the backend asks, so what is judged here is the answer to the wrong password.
    await submitCredentials(page, ACCOUNTS.developer.email, "not the password");
    await expect(page.getByRole("alert")).toContainText("That email or password is not correct.");
    await expect(page.getByRole("alert")).toContainText("Check both and try again.");

    // The right password now, through the same limit, waited out the same way.
    await submitSignIn(page, "developer");
    await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
    await expect(page.getByText(ACCOUNTS.developer.email)).toBeVisible();

    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/sign-in/);
    await expect(page.getByText("You signed out.")).toBeVisible();
  });

  test("returns to the page that was asked for", async ({ page }) => {
    await page.goto("/queue");
    await expect(page).toHaveURL(/\/sign-in\?next=%2Fqueue$/);

    await signIn(page, "developer", "/queue");

    await expect(page).toHaveURL(/\/queue$/);
    await expect(page.getByRole("heading", { level: 1, name: "Queue" })).toBeVisible();
  });
});
