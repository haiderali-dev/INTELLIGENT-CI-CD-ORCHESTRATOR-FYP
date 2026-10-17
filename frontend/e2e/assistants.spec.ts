import { expect, test, type Page } from "@playwright/test";

import { newest, reset, signIn, switchModel, tabTo, toast } from "./support";

test.beforeEach(async ({ request }) => {
  // Each approval takes its service's chain lock (4.6.4); a clean start gives every flow its own.
  await reset(request);
});

const composer = (page: Page, assistant: "Freestyle" | "Pipeline") =>
  page.getByRole("textbox", { name: `Message the ${assistant} Assistant` });

const preview = (page: Page) => page.getByRole("complementary", { name: "Preview" });

test.describe("the assistants", () => {
  test("a freestyle deploy, with a clarification, through to Run started", async ({ page }) => {
    await signIn(page, "developer");
    await page.goto("/assistants/freestyle");

    await composer(page, "Freestyle").fill("Deploy to staging");
    await composer(page, "Freestyle").press("Enter");

    // The service was missing, so the assistant asks, with the catalog's services to click.
    const question = newest(page, "Freestyle");
    await expect(question).toContainText("Which service should I deploy?");
    await question.getByRole("button", { name: "payment-service" }).click();

    const card = newest(page, "Freestyle");
    await expect(card.getByRole("region", { name: "Intent" })).toContainText("payment-service");
    await card.getByRole("button", { name: "Generate" }).click();

    await preview(page).getByRole("tab", { name: "Checks" }).click();
    await expect(preview(page).getByRole("list", { name: "Progress" })).toContainText("Validated");
    await preview(page).getByRole("button", { name: "Approve and run" }).click();

    // A deploy on its own is one job, and the dialog says exactly what will happen (4.7.4): it
    // "Creates" the job the first time and "Updates" it once an earlier flow has made it.
    const dialog = page.getByRole("alertdialog", { name: "Approve and run" });
    await expect(dialog).toContainText(
      /(Creates|Updates) 1 job and starts fs-payment-service-deploy-staging on main at MEDIUM priority/,
    );
    await dialog.getByRole("button", { name: "Approve and run" }).click();

    await expect(toast(page, "Run started")).toBeVisible();
    await expect(
      page.getByRole("region", { name: "Run of fs-payment-service-deploy-staging" }),
    ).toBeVisible();
  });

  test("a Pipeline deploy, with its Jenkinsfile", async ({ page }) => {
    await signIn(page, "developer");
    await page.goto("/assistants/pipeline");

    await composer(page, "Pipeline").fill(
      "Build, test and deploy the latest commit of auth-service to staging",
    );
    await composer(page, "Pipeline").press("Enter");
    await newest(page, "Pipeline").getByRole("button", { name: "Generate" }).click();

    await preview(page).getByRole("tab", { name: "Jenkinsfile" }).click();
    await expect(preview(page).getByText("pipeline {")).toBeVisible();
    await preview(page).getByRole("tab", { name: "Checks" }).click();
    await expect(preview(page).getByRole("list", { name: "Progress" })).toContainText("Validated");

    await preview(page).getByRole("button", { name: "Approve and run" }).click();
    await page
      .getByRole("alertdialog", { name: "Approve and run" })
      .getByRole("button", { name: "Approve and run" })
      .click();

    await expect(toast(page, "Run started")).toBeVisible();
  });

  test("refuses a production deploy and says why", async ({ page }) => {
    await signIn(page, "developer");
    await page.goto("/assistants/freestyle");

    await composer(page, "Freestyle").fill("Deploy payment-service to production");
    await composer(page, "Freestyle").press("Enter");

    const refusal = newest(page, "Freestyle");
    await expect(refusal).toContainText(/production/i);
    await expect(refusal).toContainText(/staging/i);
    await expect(refusal.getByRole("button", { name: "Generate" })).toHaveCount(0);
  });

  test("says when the rule parser answered instead of the model", async ({ page, request }) => {
    await signIn(page, "developer");
    await page.goto("/assistants/freestyle");
    await switchModel(request, false);

    await composer(page, "Freestyle").fill("Build auth-service from main");
    await composer(page, "Freestyle").press("Enter");

    const reply = newest(page, "Freestyle");
    await expect(reply).toContainText(
      "The rule parser answered this, because the AI model was not available.",
    );
    // It still understood the request.
    await expect(reply.getByRole("button", { name: "Generate" })).toBeVisible();
  });

  test("approves and runs with the keyboard alone", async ({ page }) => {
    await signIn(page, "developer");
    await page.goto("/assistants/freestyle");

    // From here on, every action is a key press.
    const input = composer(page, "Freestyle");
    await tabTo(page, input);
    await page.keyboard.type("Build payment-service from main");
    await page.keyboard.press("Enter");

    const generate = newest(page, "Freestyle").getByRole("button", { name: "Generate" });
    await expect(generate).toBeVisible();
    await tabTo(page, generate);
    await page.keyboard.press("Enter");

    const approve = preview(page).getByRole("button", { name: "Approve and run" });
    await expect(approve).toBeVisible();
    await tabTo(page, approve);
    await page.keyboard.press("Enter");

    const dialog = page.getByRole("alertdialog", { name: "Approve and run" });
    await expect(dialog).toBeVisible();
    await tabTo(page, dialog.getByRole("button", { name: "Approve and run" }));
    await page.keyboard.press("Enter");

    await expect(toast(page, "Run started")).toBeVisible();
    await expect(dialog).toBeHidden();
  });
});
