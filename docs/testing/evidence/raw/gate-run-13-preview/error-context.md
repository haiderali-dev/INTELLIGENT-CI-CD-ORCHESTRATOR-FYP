# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: stack.spec.ts >> a Pipeline build is linted and run by the real Jenkins, its stages followed live
- Location: e2e\stack.spec.ts:117:1

# Error details

```
Test timeout of 480000ms exceeded.
```

```
Error: locator.click: Test timeout of 480000ms exceeded.
Call log:
  - waiting for getByRole('complementary', { name: 'Preview' }).getByRole('tab', { name: 'Jenkinsfile' })

```

# Page snapshot

```yaml
- generic [ref=f1e2]:
  - generic [ref=f1e3]:
    - link "Skip to content" [ref=f1e4] [cursor=pointer]:
      - /url: "#main"
    - complementary [ref=f1e5]:
      - generic [ref=f1e6]:
        - paragraph [ref=f1e7]: CI/CD Orchestrator
        - navigation "Main" [ref=f1e8]:
          - list [ref=f1e9]:
            - listitem [ref=f1e10]:
              - link "Overview" [ref=f1e11] [cursor=pointer]:
                - /url: /
            - listitem [ref=f1e17]:
              - link "Freestyle Assistant" [ref=f1e18] [cursor=pointer]:
                - /url: /assistants/freestyle
            - listitem [ref=f1e22]:
              - link "Pipeline Assistant" [ref=f1e23] [cursor=pointer]:
                - /url: /assistants/pipeline
            - listitem [ref=f1e28]:
              - link "Queue" [ref=f1e29] [cursor=pointer]:
                - /url: /queue
            - listitem [ref=f1e33]:
              - link "Jobs and runs" [ref=f1e34] [cursor=pointer]:
                - /url: /runs
            - listitem [ref=f1e39]:
              - link "Analytics" [ref=f1e40] [cursor=pointer]:
                - /url: /analytics
            - listitem [ref=f1e43]:
              - link "Service catalog" [ref=f1e44] [cursor=pointer]:
                - /url: /catalog
        - generic [ref=f1e55]:
          - paragraph [ref=f1e56]: Environment Staging
          - generic [ref=f1e57]:
            - paragraph [ref=f1e58]:
              - generic [ref=f1e59]: Signed in as
              - generic "system-test-b8378413@example.com" [ref=f1e60]
              - generic [ref=f1e61]: Developer
            - button "Sign out" [ref=f1e62]
          - group "Theme" [ref=f1e63]:
            - generic [ref=f1e65]:
              - generic [ref=f1e66]:
                - radio "Light" [checked] [ref=f1e67] [cursor=pointer]
                - generic [ref=f1e68]: Light
              - generic [ref=f1e69]:
                - radio "Dark" [ref=f1e70] [cursor=pointer]
                - generic [ref=f1e71]: Dark
              - generic [ref=f1e72]:
                - radio "System" [ref=f1e73] [cursor=pointer]
                - generic [ref=f1e74]: System
    - main [ref=f1e75]:
      - generic [ref=f1e76]:
        - generic [ref=f1e78]:
          - heading "Pipeline Assistant" [level=1] [ref=f1e79]
          - paragraph [ref=f1e80]: Creates Pipeline jobs on staging, from plain English.
        - generic [ref=f1e81]:
          - complementary [ref=f1e82]:
            - heading "Chats" [level=2] [ref=f1e83]
            - generic [ref=f1e84]:
              - list [ref=f1e85]:
                - listitem [ref=f1e86]:
                  - button "Build auth-service from main 21:46" [ref=f1e87]:
                    - generic [ref=f1e88]: Build auth-service from main
                    - generic [ref=f1e89]: 21:46
              - button "New chat" [ref=f1e91]
          - region "Conversation" [ref=f1e93]:
            - list "Conversation with the Pipeline Assistant" [ref=f1e96]:
              - listitem [ref=f1e97]:
                - paragraph [ref=f1e98]: You
                - paragraph [ref=f1e100]: Build auth-service from main
              - listitem [ref=f1e101]:
                - paragraph [ref=f1e102]: Pipeline Assistant
                - generic [ref=f1e107]:
                  - paragraph [ref=f1e108]: "Ready to generate: build auth-service on main."
                  - region "Intent" [ref=f1e110]:
                    - generic [ref=f1e111]:
                      - term [ref=f1e112]: Service
                      - definition [ref=f1e113]:
                        - generic [ref=f1e114]: auth-service
                      - term [ref=f1e115]: Branch
                      - definition [ref=f1e116]:
                        - generic [ref=f1e117]: main
                      - term [ref=f1e118]: Environment
                      - definition [ref=f1e119]:
                        - generic [ref=f1e120]: Not set
                      - term [ref=f1e121]: Urgency
                      - definition [ref=f1e122]:
                        - generic [ref=f1e123]: Not set
                    - generic [ref=f1e124]:
                      - button "Generate" [active] [ref=f1e125]
                      - button "Edit" [ref=f1e126]
            - form "Message" [ref=f1e129]:
              - generic [ref=f1e130]:
                - generic [ref=f1e131]: Message the Pipeline Assistant
                - textbox "Message the Pipeline Assistant" [ref=f1e132]
                - button "Send" [disabled] [ref=f1e133]
              - paragraph [ref=f1e137]:
                - generic [ref=f1e138]: Enter sends. Shift+Enter adds a line.
              - paragraph [ref=f1e139]
          - complementary [ref=f1e140]:
            - heading "Preview" [level=2] [ref=f1e141]
            - paragraph [ref=f1e142]: Nothing to preview yet. Ask for a build, test or deploy, then choose Generate.
  - region "Notifications (F8)":
    - list
```

# Test source

```ts
  35  |   const problems: string[] = [];
  36  |   page.on("console", (message) => {
  37  |     if (/Content Security Policy/i.test(message.text())) {
  38  |       problems.push(`CSP: ${message.text()}`);
  39  |     }
  40  |   });
  41  |   page.on("pageerror", (error) => {
  42  |     problems.push(`page error: ${error.message}`);
  43  |   });
  44  |   page.on("response", (response) => {
  45  |     if (response.url().includes("/api/") && response.status() >= 500) {
  46  |       problems.push(`${String(response.status())} from ${response.url()}`);
  47  |     }
  48  |   });
  49  |   return problems;
  50  | }
  51  | 
  52  | test("every page loads through the stack's frontend, under its policy, with no server error", async ({ page }) => {
  53  |   const problems = watch(page);
  54  |   await signInToStack(page);
  55  | 
  56  |   const pages: [string, string][] = [
  57  |     ["/", "Overview"],
  58  |     ["/assistants/freestyle", "Freestyle Assistant"],
  59  |     ["/assistants/pipeline", "Pipeline Assistant"],
  60  |     ["/queue", "Queue"],
  61  |     ["/runs", "Jobs and runs"],
  62  |     ["/analytics", "Analytics"],
  63  |     ["/catalog", "Service catalog"],
  64  |   ];
  65  |   for (const [path, heading] of pages) {
  66  |     await page.goto(path);
  67  |     await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
  68  |   }
  69  |   // The live events reached the page through nginx's /ws proxy.
  70  |   await page.goto("/queue");
  71  |   await expect(page.getByRole("list", { name: "Queue status" })).toContainText("Live");
  72  |   // The catalog's services were read from the stack's own catalog and their repositories reached.
  73  |   await page.goto("/catalog");
  74  |   await expect(page.getByText("payment-service").first()).toBeVisible();
  75  | 
  76  |   expect(problems).toEqual([]);
  77  | });
  78  | 
  79  | test("a freestyle build runs on the real Jenkins, and its run card follows it live", async ({ page }) => {
  80  |   test.setTimeout(6 * 60_000);
  81  |   const problems = watch(page);
  82  |   await signInToStack(page);
  83  |   await page.goto("/assistants/freestyle");
  84  | 
  85  |   const composer = page.getByRole("textbox", { name: "Message the Freestyle Assistant" });
  86  |   await composer.fill("Build payment-service from main");
  87  |   await composer.press("Enter");
  88  | 
  89  |   const thread = page.getByRole("list", { name: "Conversation with the Freestyle Assistant" });
  90  |   const card = thread.locator(":scope > li").last();
  91  |   await expect(card.getByRole("region", { name: "Intent" })).toContainText("payment-service", {
  92  |     timeout: 60_000,
  93  |   });
  94  |   await card.getByRole("button", { name: "Generate" }).click();
  95  | 
  96  |   const preview = page.getByRole("complementary", { name: "Preview" });
  97  |   await preview.getByRole("tab", { name: "Checks" }).click();
  98  |   // Validation includes the real controller: the job names are checked against jenkins-dev.
  99  |   await expect(preview.getByRole("list", { name: "Progress" })).toContainText("Validated", {
  100 |     timeout: 60_000,
  101 |   });
  102 |   await preview.getByRole("button", { name: "Approve and run" }).click();
  103 | 
  104 |   const dialog = page.getByRole("alertdialog", { name: "Approve and run" });
  105 |   await expect(dialog).toContainText(/(Creates|Updates) 1 job and starts fs-payment-service-build on main/);
  106 |   await dialog.getByRole("button", { name: "Approve and run" }).click();
  107 | 
  108 |   const run = page.getByRole("region", { name: "Run of fs-payment-service-build" });
  109 |   await expect(run).toBeVisible({ timeout: 30_000 });
  110 |   // Built on an agent by the real Jenkins; the card learns of it from the plugin's events and the
  111 |   // backend's tracker, over the WebSocket, without a reload.
  112 |   await expect(run).toContainText("fs-payment-service-build succeeded", { timeout: 5 * 60_000 });
  113 | 
  114 |   expect(problems).toEqual([]);
  115 | });
  116 | 
  117 | test("a Pipeline build is linted and run by the real Jenkins, its stages followed live", async ({ page }) => {
  118 |   test.setTimeout(8 * 60_000);
  119 |   const problems = watch(page);
  120 |   await signInToStack(page);
  121 |   await page.goto("/assistants/pipeline");
  122 | 
  123 |   const composer = page.getByRole("textbox", { name: "Message the Pipeline Assistant" });
  124 |   await composer.fill("Build auth-service from main");
  125 |   await composer.press("Enter");
  126 | 
  127 |   const thread = page.getByRole("list", { name: "Conversation with the Pipeline Assistant" });
  128 |   const card = thread.locator(":scope > li").last();
  129 |   await expect(card.getByRole("region", { name: "Intent" })).toContainText("auth-service", {
  130 |     timeout: 60_000,
  131 |   });
  132 |   await card.getByRole("button", { name: "Generate" }).click();
  133 | 
  134 |   const preview = page.getByRole("complementary", { name: "Preview" });
> 135 |   await preview.getByRole("tab", { name: "Jenkinsfile" }).click();
      |                                                           ^ Error: locator.click: Test timeout of 480000ms exceeded.
  136 |   await expect(preview.getByText("pipeline {")).toBeVisible({ timeout: 60_000 });
  137 |   await preview.getByRole("tab", { name: "Checks" }).click();
  138 |   // The Jenkinsfile was linted by jenkins-dev's own declarative linter on the way to Validated.
  139 |   await expect(preview.getByRole("list", { name: "Progress" })).toContainText("Validated", {
  140 |     timeout: 60_000,
  141 |   });
  142 |   await preview.getByRole("button", { name: "Approve and run" }).click();
  143 |   await page
  144 |     .getByRole("alertdialog", { name: "Approve and run" })
  145 |     .getByRole("button", { name: "Approve and run" })
  146 |     .click();
  147 | 
  148 |   const run = page.getByRole("region", { name: /^Run of pl-auth-service/ });
  149 |   await expect(run).toBeVisible({ timeout: 30_000 });
  150 |   // The stages come from Jenkins' own stage view, tracked by the backend and pushed over /ws.
  151 |   await expect(run.getByRole("list", { name: "Stages" })).toContainText("Build succeeded", {
  152 |     timeout: 6 * 60_000,
  153 |   });
  154 | 
  155 |   expect(problems).toEqual([]);
  156 | });
  157 | 
```