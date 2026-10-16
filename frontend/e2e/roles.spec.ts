import { randomBytes } from "node:crypto";

import { expect, test } from "@playwright/test";

import { ACCOUNTS, signIn, toast } from "./support";

test.describe("what each role is offered", () => {
  test("a Developer is not offered Admin, and the page says why it is closed", async ({ page }) => {
    await signIn(page, "developer");

    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav.getByRole("link", { name: "Service catalog" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Admin" })).toHaveCount(0);

    await page.goto("/admin");
    await expect(page.getByText("Only Admins can use this page.")).toBeVisible();
    await expect(page.getByText(/^Your role is Developer\./)).toBeVisible();

    await page.goto("/catalog");
    await expect(page.getByRole("heading", { level: 2, name: "payment-service" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Resync the catalog" })).toHaveCount(0);
  });

  test("an Admin sees every user, and adds one", async ({ page }) => {
    await signIn(page, "admin");
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Admin" }).click();

    const users = page.getByRole("table", { name: "Users" });
    await expect(users.getByRole("rowheader", { name: new RegExp(`^${ACCOUNTS.admin.email}`) })).toBeVisible();
    await expect(users.getByRole("rowheader", { name: ACCOUNTS.developer.email })).toBeVisible();

    // A new address each run, so a rerun against the same backend never collides.
    const email = `e2e-${randomBytes(4).toString("hex")}@example.com`;
    const form = page.getByRole("form", { name: "Add a user" });
    await form.getByLabel("Email").fill(email);
    await form.getByLabel("First password").fill(`first-${randomBytes(9).toString("base64url")}`);
    await form.getByLabel("Role").selectOption("DEVOPS");
    await form.getByRole("button", { name: "Add user" }).click();

    await expect(toast(page, `${email} was added as DevOps`)).toBeVisible();
    await expect(users.getByRole("rowheader", { name: email })).toBeVisible();
    await expect(page.getByRole("table", { name: "Audit log, newest first" })).toContainText(
      "admin.user.created",
    );
  });
});
