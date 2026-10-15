import { test, expect } from "@playwright/test";

test.describe("Authentication and Route Protection", () => {
  const timestamp = Date.now();
  const validEmail = `auth_test_${timestamp}@taskflow.dev`;
  const validPassword = "SecurePassword123!";

  test.beforeAll(async ({ request }) => {
    // Seed a valid user for authentication tests via real API
    const res = await request.post("/api/v1/auth/register", {
      data: {
        email: validEmail,
        full_name: "Auth E2E User",
        password: validPassword,
      },
    });
    expect(res.status()).toBe(201);
  });

  test("Unauthenticated user accessing protected routes is redirected to /login", async ({
    page,
  }) => {
    // Access /projects unauthenticated
    await page.goto("/projects");
    await page.waitForURL("/login");
    await expect(page.getByRole("heading", { name: /Sign in to TaskFlow/i })).toBeVisible();

    // Access /organizations/select unauthenticated
    await page.goto("/organizations/select");
    await page.waitForURL("/login");
    await expect(page.getByRole("heading", { name: /Sign in to TaskFlow/i })).toBeVisible();

    // Access /boards unauthenticated
    await page.goto("/boards");
    await page.waitForURL("/login");
    await expect(page.getByRole("heading", { name: /Sign in to TaskFlow/i })).toBeVisible();
  });

  test("Login with invalid credentials displays an error message", async ({ page }) => {
    await page.goto("/login");
    await page.fill('input[type="email"]', "nonexistent_user@taskflow.dev");
    await page.fill('input[type="password"]', "WrongPassword123!");
    await page.click('button[type="submit"]');

    const errorAlert = page.locator(".bg-red-50, [class*='text-red']");
    await expect(errorAlert).toBeVisible();
    await expect(errorAlert).toContainText(/invalid email or password/i);
    expect(page.url()).toContain("/login");
  });

  test("Login with valid credentials successfully navigates to workspace", async ({
    page,
  }) => {
    await page.goto("/login");
    await page.fill('input[type="email"]', validEmail);
    await page.fill('input[type="password"]', validPassword);
    await page.click('button[type="submit"]');

    // User has no organizations initially, so should navigate to /organizations/select
    await page.waitForURL(/\/organizations\/select/);
    await expect(page.getByRole("heading", { name: "Workspaces" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Create Organization" })).toBeVisible();
  });

  test("Logout clears authenticated state and redirects to login", async ({ page }) => {
    // 1. Log in
    await page.goto("/login");
    await page.fill('input[type="email"]', validEmail);
    await page.fill('input[type="password"]', validPassword);
    await page.click('button[type="submit"]');
    await page.waitForURL(/\/organizations\/select/);

    // 2. Click sign out
    const signOutBtn = page.getByRole("button", { name: /Sign out/i });
    await expect(signOutBtn).toBeVisible();
    await signOutBtn.click();

    // 3. Must be back on /login
    await page.waitForURL("/login");
    await expect(page.getByRole("heading", { name: /Sign in to TaskFlow/i })).toBeVisible();

    // 4. Verify accessing protected route redirects to /login
    await page.goto("/projects");
    await page.waitForURL("/login");
    await expect(page.getByRole("heading", { name: /Sign in to TaskFlow/i })).toBeVisible();
  });
});
