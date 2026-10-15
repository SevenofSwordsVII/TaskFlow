import { test, expect } from "@playwright/test";

test.describe("TaskFlow End-to-End User Journey", () => {
  const timestamp = Date.now();
  const testEmail = `journey_${timestamp}@taskflow.dev`;
  const testPassword = "Password123!Secure";
  const orgName = `Acme Workspace ${timestamp}`;
  const projectName = `Core Project ${timestamp}`;
  const projectKey = `COR${timestamp.toString().slice(-3)}`;
  const taskTitle = `E2E Feature Card ${timestamp}`;
  const commentText = `E2E Comment verified at ${timestamp}`;

  test("Complete journey: registration, workspace creation, project setup, Kanban task, and comments", async ({
    page,
  }) => {
    // 1. User Registration
    await page.goto("/register");
    await page.getByLabel(/Full Name/i).fill("E2E Tester");
    await page.getByLabel(/Email address/i).fill(testEmail);
    await page.locator('input#password').fill(testPassword);
    await page.locator('input#confirm-password').fill(testPassword);
    await page.getByRole("button", { name: /Create account/i }).click();

    // 2. Organization Creation
    await page.waitForURL(/\/organizations\/select/);
    await expect(page.getByRole("heading", { name: "Create Organization" })).toBeVisible();

    await page.getByLabel(/Organization Name/i).fill(orgName);
    // Slug is auto-derived in input#org-slug
    await page.getByRole("button", { name: /Create Organization/i }).click();

    // 3. Project Creation
    await page.waitForURL(/\/(projects)?$/);
    await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();

    // Open project creation modal
    const createProjectBtn = page.getByRole("button", { name: /New Project|Create Project/i }).first();
    await createProjectBtn.click();

    await page.getByPlaceholder("e.g. Core Platform", { exact: true }).fill(projectName);
    await page.getByPlaceholder("e.g. CORE", { exact: true }).fill(projectKey);
    await page.locator("form").getByRole("button", { name: "Create Project" }).click();

    // Verify project appears in workspace grid
    await expect(page.getByText(projectName)).toBeVisible();
    await expect(page.getByText(projectKey)).toBeVisible();

    // 4. Navigate to Kanban Board
    const openBoardLink = page.getByRole("link", { name: /Open Board/i }).first();
    await expect(openBoardLink).toBeVisible();
    await openBoardLink.click();

    await page.waitForURL(/\/boards\//);
    await expect(page.getByText(/Workspace|Acme/i)).toBeVisible();

    // 5. Kanban Task Creation
    const addCardBtn = page.getByRole("button", { name: /\+ Add a card/i }).first();
    await expect(addCardBtn).toBeVisible();
    await addCardBtn.click();

    const cardInput = page.getByPlaceholder(/Enter a title for this card/i);
    await expect(cardInput).toBeVisible();
    await cardInput.fill(taskTitle);
    await page.getByRole("button", { name: /Add card/i }).click();

    // Verify task card renders in the column
    const taskCard = page.getByText(taskTitle);
    await expect(taskCard).toBeVisible();

    // 6. Task Discussion & Comments
    await taskCard.click();

    // Verify Task Discussion modal is open
    await expect(page.locator(".fixed").getByRole("heading", { name: taskTitle })).toBeVisible();
    await expect(page.getByText(/Task Discussion/i)).toBeVisible();

    // Post a comment
    const commentInput = page.getByPlaceholder(/Write a comment/i);
    await expect(commentInput).toBeVisible();
    await commentInput.fill(commentText);
    await page.getByRole("button", { name: /Send/i }).click();

    // Verify comment appears in thread
    await expect(page.getByText(commentText)).toBeVisible();
    await expect(page.locator(".fixed").getByText("E2E Tester").first()).toBeVisible();

    // Close comment modal
    const closeBtn = page.locator(".fixed").getByRole("button", { name: "✕" });
    await closeBtn.click();
    await expect(page.getByText(/Task Discussion/i)).not.toBeVisible();

    // 7. Verify Data Persistence on Page Reload
    await page.reload();
    await expect(page.getByText(taskTitle)).toBeVisible();
  });
});
