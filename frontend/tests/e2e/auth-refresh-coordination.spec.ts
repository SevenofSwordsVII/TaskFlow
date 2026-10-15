import { test, expect } from "@playwright/test";

/**
 * Regression test suite for cross-tab token refresh coordination and 401 interceptor.
 *
 * Targets:
 * 1. Stale in-memory token retry defect: 401 interceptor returning stale token
 *    instead of refreshing, retrying with expired token, and failing without refresh.
 * 2. Cross-tab refresh race: Two tabs hitting 401 simultaneously; Tab A refreshes and
 *    clears pending operation; Tab B acquires lock but lacks fresh token in memory,
 *    submitting uncoordinated operation ID or failing to recover authenticated state.
 */

test.describe("Cross-Tab Refresh-Token Coordination Regressions", () => {
  test("401 with stale access token must invoke /refresh and retry with fresh token", async ({
    page,
  }) => {
    let refreshCallCount = 0;
    const initialStaleToken = "stale-access-token-initial";
    const freshRefreshedToken = "fresh-access-token-refreshed";
    const requestedAuthTokens: string[] = [];

    let isUserLoggedIn = false;

    // Intercept /auth/refresh to count calls and return a fresh token
    await page.route("**/api/v1/auth/refresh", async (route) => {
      if (!isUserLoggedIn) {
        await route.fulfill({
          status: 401,
          contentType: "application/json",
          body: JSON.stringify({
            error: { code: "NO_ACTIVE_SESSION", message: "No active session" },
          }),
        });
        return;
      }
      refreshCallCount++;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          access_token: freshRefreshedToken,
          token_type: "bearer",
          expires_in: 900,
        }),
      });
    });

    // Intercept protected API endpoint (projects list)
    await page.route("**/api/v1/organizations/*/projects", async (route) => {
      const authHeader = route.request().headers()["authorization"] || "";
      const token = authHeader.replace(/^Bearer\s+/i, "");
      requestedAuthTokens.push(token);

      if (token === freshRefreshedToken) {
        // Fresh token accepted
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              id: "proj-1",
              name: "Demo Project",
              key: "DEMO",
              visibility: "ORG_PUBLIC",
            },
          ]),
        });
      } else {
        // Initial / stale token rejected with 401
        await route.fulfill({
          status: 401,
          contentType: "application/json",
          body: JSON.stringify({
            error: {
              code: "TOKEN_EXPIRED",
              message: "Access token has expired",
            },
          }),
        });
      }
    });

    // Intercept /auth/me for user profile
    await page.route("**/api/v1/auth/me", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "user-1",
          email: "test@example.com",
          full_name: "Test User",
          organizations: [
            {
              id: "org-1",
              name: "Test Org",
              slug: "test-org",
              role: "MEMBER",
            },
          ],
        }),
      });
    });

    // Navigate to login page
    await page.goto("/login");

    // Intercept login to inject the initial token
    await page.route("**/api/v1/auth/token", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          access_token: initialStaleToken,
          token_type: "bearer",
          expires_in: 900,
          user: {
            id: "user-1",
            email: "test@example.com",
            full_name: "Test User",
          },
        }),
      });
    });

    // Perform login through UI
    await page.fill('input[type="email"]', "test@example.com");
    await page.fill('input[type="password"]', "Password123!");
    isUserLoggedIn = true;
    await page.click('button[type="submit"]');

    // Wait for navigation to workspace and project data to load via retry
    await page.waitForURL(/\/(projects)?$/);
    await expect(page.locator("h1")).toContainText("Projects");
    await expect(page.getByText("Demo Project")).toBeVisible();

    // Expectation:
    // 1. Initial request to /projects sent with initialStaleToken (returns 401)
    // 2. Refresh endpoint /auth/refresh MUST be called exactly once
    // 3. Retry to /projects MUST be sent with freshRefreshedToken
    // 4. Projects page displays project data successfully
    expect(refreshCallCount).toBe(1);
    expect(requestedAuthTokens).toContain(freshRefreshedToken);
  });

  test("Two tabs hitting 401 concurrently must coordinate without session family revocation", async ({
    context,
  }) => {
    const pageA = await context.newPage();
    const pageB = await context.newPage();

    let refreshCallCount = 0;
    const refreshOperationIds: string[] = [];
    const initialToken = "initial-jwt-token";
    const renewedTokenA = "renewed-jwt-token-a";

    let isUserLoggedIn = false;

    // Request barrier to hold Tab A's refresh in-flight while Tab B attempts refresh
    let releaseRefreshPromise: () => void = () => {};
    const refreshBarrier = new Promise<void>((resolve) => {
      releaseRefreshPromise = resolve;
    });

    // Intercept /auth/refresh across all pages in this browser context
    await context.route("**/api/v1/auth/refresh", async (route) => {
      if (!isUserLoggedIn) {
        await route.fulfill({
          status: 401,
          contentType: "application/json",
          body: JSON.stringify({
            error: { code: "NO_ACTIVE_SESSION", message: "No active session" },
          }),
        });
        return;
      }
      refreshCallCount++;
      const opId = route.request().headers()["x-refresh-operation-id"] || "";
      refreshOperationIds.push(opId);

      // Wait for barrier on the first refresh call to guarantee overlap
      if (refreshCallCount === 1) {
        await refreshBarrier;
      }

      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          access_token: renewedTokenA,
          token_type: "bearer",
          expires_in: 900,
        }),
      });
    });

    // Intercept /auth/token for login
    await context.route("**/api/v1/auth/token", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          access_token: initialToken,
          token_type: "bearer",
          expires_in: 900,
          user: {
            id: "user-1",
            email: "test@example.com",
            full_name: "Test User",
          },
        }),
      });
    });

    // Intercept /auth/me
    await context.route("**/api/v1/auth/me", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "user-1",
          email: "test@example.com",
          full_name: "Test User",
          organizations: [
            {
              id: "org-1",
              name: "Test Org",
              slug: "test-org",
              role: "MEMBER",
            },
          ],
        }),
      });
    });

    // Intercept protected /projects endpoint: 401 on initialToken, 200 on renewedToken
    await context.route("**/api/v1/organizations/*/projects", async (route) => {
      const auth = route.request().headers()["authorization"] || "";
      if (auth.includes(renewedTokenA)) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([{ id: "p1", name: "Alpha", key: "ALP", visibility: "ORG_PUBLIC" }]),
        });
      } else {
        await route.fulfill({
          status: 401,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "TOKEN_EXPIRED", message: "Token expired" } }),
        });
      }
    });

    // Log in on Page A
    await pageA.goto("/login");
    await pageA.fill('input[type="email"]', "test@example.com");
    await pageA.fill('input[type="password"]', "Password123!");
    isUserLoggedIn = true;
    await pageA.click('button[type="submit"]');
    await pageA.waitForURL(/\/(projects)?$/);

    // Open Page B on / (shares browser context cookies)
    await pageB.goto("/");

    // Release the refresh barrier
    releaseRefreshPromise();

    // Both tabs must successfully display projects without unexpected logout or session destruction
    await expect(pageA.locator("h1")).toContainText("Projects");
    await expect(pageB.locator("h1")).toContainText("Projects");

    // In a correct coordinated multi-tab design:
    // Tab A refreshes and shares the renewed token or operation ID.
    // Tab B must NOT execute an uncoordinated refresh with a conflicting operation ID.
    expect(refreshCallCount).toBeLessThanOrEqual(1);
    if (refreshOperationIds.length > 1) {
      // If Tab B also refreshed, it must have reused the identical operation ID within the recovery window
      expect(refreshOperationIds[0]).toBe(refreshOperationIds[1]);
    }
  });

  test("401 response when refresh fails must terminate cleanly without infinite retry loop", async ({
    page,
  }) => {
    let projectsCallCount = 0;

    // Reject refresh with 401 (e.g. revoked session)
    await page.route("**/api/v1/auth/refresh", async (route) => {
      await route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({
          error: {
            code: "SESSION_REVOKED",
            message: "Session revoked",
          },
        }),
      });
    });

    await page.route("**/api/v1/organizations/*/projects", async (route) => {
      projectsCallCount++;
      await route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({
          error: {
            code: "TOKEN_EXPIRED",
            message: "Token expired",
          },
        }),
      });
    });

    await page.route("**/api/v1/auth/me", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "user-1",
          email: "test@example.com",
          full_name: "Test User",
          organizations: [{ id: "org-1", name: "Org", slug: "org", role: "MEMBER" }],
        }),
      });
    });

    await page.route("**/api/v1/auth/token", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          access_token: "expired-token",
          token_type: "bearer",
          expires_in: 900,
          user: { id: "user-1", email: "test@example.com", full_name: "Test User" },
        }),
      });
    });

    await page.goto("/login");
    await page.fill('input[type="email"]', "test@example.com");
    await page.fill('input[type="password"]', "Password123!");
    await page.click('button[type="submit"]');

    // Since refresh failed, the user should be logged out and redirected to /login
    await page.waitForURL("/login");
    // Verify projects was called at most twice (initial + 1 retry attempt before failure), never looping infinitely
    expect(projectsCallCount).toBeLessThanOrEqual(2);
  });
});
