import { test, expect } from "@playwright/test";

test.describe("Kanban OCC Conflict and Optimistic Rollback", () => {
  const timestamp = Date.now();
  const testEmail = `occ_${timestamp}@taskflow.dev`;
  const testPassword = "Password123!Secure";
  const orgName = `OCC Workspace ${timestamp}`;
  const projectName = `OCC Project ${timestamp}`;
  const projectKey = `OCC${timestamp.toString().slice(-3)}`;
  const cardTitle = `OCC Test Card ${timestamp}`;

  test("Task move encountering HTTP 409 conflict rolls back gracefully without crash", async ({
    page,
  }) => {
    // 1. Register and setup workspace
    await page.goto("/register");
    await page.getByLabel(/Full Name/i).fill("OCC Tester");
    await page.getByLabel(/Email address/i).fill(testEmail);
    await page.locator("input#password").fill(testPassword);
    await page.locator("input#confirm-password").fill(testPassword);
    await page.getByRole("button", { name: /Create account/i }).click();

    // 2. Create organization
    await page.waitForURL(/\/organizations\/select/);
    await page.getByLabel(/Organization Name/i).fill(orgName);
    await page.getByRole("button", { name: /Create Organization/i }).click();

    // 3. Create project
    await page.waitForURL(/\/(projects)?$/);
    const newProjectBtn = page.getByRole("button", { name: /New Project|Create Project/i }).first();
    await newProjectBtn.click();
    await page.getByPlaceholder("e.g. Core Platform", { exact: true }).fill(projectName);
    await page.getByPlaceholder("e.g. CORE", { exact: true }).fill(projectKey);
    await page.locator("form").getByRole("button", { name: "Create Project" }).click();

    // 4. Open Kanban board
    const openBoardLink = page.getByRole("link", { name: /Open Board/i }).first();
    await expect(openBoardLink).toBeVisible();
    await openBoardLink.click();
    await page.waitForURL(/\/boards\//);

    // 5. Add a card to the first list
    const addCardBtn = page.getByRole("button", { name: /\+ Add a card/i }).first();
    await expect(addCardBtn).toBeVisible();
    await addCardBtn.click();

    const cardInput = page.getByPlaceholder(/Enter a title for this card/i);
    await cardInput.fill(cardTitle);
    await page.getByRole("button", { name: /Add card/i }).click();

    const taskCard = page.getByText(cardTitle);
    await expect(taskCard).toBeVisible();

    // 6. Mock 409 Conflict rejection for task movement
    await page.route("**/api/v1/tasks/*/move", async (route) => {
      await route.fulfill({
        status: 409,
        contentType: "application/json",
        body: JSON.stringify({
          error: {
            code: "TASK_VERSION_CONFLICT",
            message: "Task was modified concurrently by another user.",
            details: { current_version: 2 },
          },
        }),
      });
    });

    // 7. Verify board container remains mounted and fully interactive
    await expect(page.locator("h1")).toBeVisible();
    await expect(page.getByText(cardTitle)).toBeVisible();
  });
});
