import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

/**
 * TaskFlow Production Auth Client Behavior Tests
 *
 * Exercises the actual production modules (frontend/src/api/client.ts and authStore.ts)
 * with mocked browser boundaries (fetch, localStorage, BroadcastChannel, Web Locks).
 * Does NOT reimplement production algorithms in the test suite.
 */

// --- 1. Browser Environment Mock Setup ---

class MockStorage {
  constructor() {
    this.store = new Map();
  }
  getItem(key) {
    return this.store.has(key) ? this.store.get(key) : null;
  }
  setItem(key, value) {
    this.store.set(key, String(value));
  }
  removeItem(key) {
    this.store.delete(key);
  }
  clear() {
    this.store.clear();
  }
  get length() {
    return this.store.size;
  }
  key(index) {
    return Array.from(this.store.keys())[index] ?? null;
  }
  entries() {
    return Array.from(this.store.entries());
  }
}

const mockLocalStorage = new MockStorage();
const mockSessionStorage = new MockStorage();
globalThis.localStorage = mockLocalStorage;
globalThis.sessionStorage = mockSessionStorage;

// Multi-instance BroadcastChannel mock for cross-tab messaging simulation
const channelRegistry = new Map();

class MockBroadcastChannel {
  constructor(name) {
    this.name = name;
    this.onmessage = null;
    this.closed = false;
    if (!channelRegistry.has(name)) {
      channelRegistry.set(name, new Set());
    }
    channelRegistry.get(name).add(this);
  }

  postMessage(message) {
    if (this.closed) return;
    const subscribers = channelRegistry.get(this.name);
    if (!subscribers) return;
    // Broadcast to all other subscribers on this channel
    for (const sub of subscribers) {
      if (sub !== this && !sub.closed && typeof sub.onmessage === "function") {
        const cloned = JSON.parse(JSON.stringify(message));
        queueMicrotask(() => {
          if (!sub.closed && typeof sub.onmessage === "function") {
            sub.onmessage({ data: cloned });
          }
        });
      }
    }
  }

  close() {
    this.closed = true;
    const subscribers = channelRegistry.get(this.name);
    if (subscribers) {
      subscribers.delete(this);
    }
  }
}

globalThis.BroadcastChannel = MockBroadcastChannel;

// Web Locks API Mock
class MockWebLocks {
  constructor() {
    this.locks = new Map();
  }

  async request(name, callback) {
    // Basic serial queue per lock name
    const prevLock = this.locks.get(name) || Promise.resolve();
    let release;
    const nextLock = new Promise((resolve) => {
      release = resolve;
    });
    this.locks.set(name, prevLock.then(() => nextLock));

    await prevLock;
    try {
      return await callback();
    } finally {
      release();
    }
  }
}

const mockWebLocks = new MockWebLocks();
if (globalThis.navigator) {
  try {
    Object.defineProperty(globalThis.navigator, "locks", {
      value: mockWebLocks,
      configurable: true,
      writable: true,
    });
  } catch {
    Object.defineProperty(globalThis, "navigator", {
      value: { ...globalThis.navigator, locks: mockWebLocks },
      configurable: true,
      writable: true,
    });
  }
} else {
  Object.defineProperty(globalThis, "navigator", {
    value: { locks: mockWebLocks },
    configurable: true,
    writable: true,
  });
}

// --- 2. Production Code Transpilation and Dynamic Loading ---

const tmpDir = process.env.CLAUDE_JOB_DIR
  ? path.join(process.env.CLAUDE_JOB_DIR, "tmp")
  : path.resolve(import.meta.dirname, "../node_modules/.tmp_tests");

if (!fs.existsSync(tmpDir)) {
  fs.mkdirSync(tmpDir, { recursive: true });
}

const clientTsPath = path.resolve(import.meta.dirname, "../src/api/client.ts");
const authStoreTsPath = path.resolve(import.meta.dirname, "../src/store/authStore.ts");

const clientTsSource = fs.readFileSync(clientTsPath, "utf-8");
const authStoreTsSource = fs.readFileSync(authStoreTsPath, "utf-8");

// Transpile client.ts
const transpiledClient = ts.transpileModule(clientTsSource, {
  compilerOptions: {
    module: ts.ModuleKind.ESNext,
    target: ts.ScriptTarget.ES2022,
  },
});

const clientJsPath = path.join(tmpDir, "client.js");
fs.writeFileSync(clientJsPath, transpiledClient.outputText, "utf-8");

// Transpile authStore.ts, rewriting import "../api/client" to "./client.js"
const rewrittenAuthStoreSource = authStoreTsSource.replace(
  /from\s+["']\.\.\/api\/client["']/g,
  'from "./client.js"'
);

const transpiledAuthStore = ts.transpileModule(rewrittenAuthStoreSource, {
  compilerOptions: {
    module: ts.ModuleKind.ESNext,
    target: ts.ScriptTarget.ES2022,
  },
});

const authStoreJsPath = path.join(tmpDir, "authStore.js");
fs.writeFileSync(authStoreJsPath, transpiledAuthStore.outputText, "utf-8");

// Import the transpiled production modules
const client = await import(`file://${clientJsPath}`);
const { useAuthStore } = await import(`file://${authStoreJsPath}`);

// Helper to reset mocks between tests
function resetTestState() {
  mockLocalStorage.clear();
  mockSessionStorage.clear();
  client.clearPendingOperation();
  useAuthStore.getState().reset();
}

// --- 3. Production Behavior Tests ---

test("Production Test 1: Stale-token 401 path - refreshAccessTokenCoordinated refreshes when current token matches failedToken", async () => {
  resetTestState();
  let refreshFetchCount = 0;
  let receivedOpId = null;

  useAuthStore.getState().setAccessToken("stale_token_abc");

  globalThis.fetch = async (url, options = {}) => {
    if (url.includes("/api/v1/auth/refresh")) {
      refreshFetchCount++;
      receivedOpId = options.headers?.["X-Refresh-Operation-Id"];
      return new Response(
        JSON.stringify({ access_token: "fresh_token_xyz", token_type: "bearer" }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    return new Response(JSON.stringify({ error: "Not Found" }), { status: 404 });
  };

  // Calling refresh with the failed token
  const result = await client.refreshAccessTokenCoordinated("stale_token_abc");

  assert.equal(result, "fresh_token_xyz");
  assert.equal(refreshFetchCount, 1);
  assert.ok(receivedOpId, "Must include X-Refresh-Operation-Id header");
  assert.equal(useAuthStore.getState().accessToken, "fresh_token_xyz");
});

test("Production Test 2: Already-refreshed token reuse - skips refresh when in-memory token is newer than failedToken", async () => {
  resetTestState();
  let refreshFetchCount = 0;

  useAuthStore.getState().setAccessToken("already_renewed_token_999");

  globalThis.fetch = async () => {
    refreshFetchCount++;
    throw new Error("Network fetch should not be called!");
  };

  // Request failed with an older token
  const result = await client.refreshAccessTokenCoordinated("older_expired_token_111");

  assert.equal(result, "already_renewed_token_999");
  assert.equal(refreshFetchCount, 0); // Reused without network call
});

test("Production Test 3: Same-tab coalescing - concurrent 401s coalesce into a single refresh execution", async () => {
  resetTestState();
  let refreshFetchCount = 0;

  useAuthStore.getState().setAccessToken("stale_concurrent_token");

  globalThis.fetch = async (url) => {
    if (url.includes("/api/v1/auth/refresh")) {
      refreshFetchCount++;
      await new Promise((r) => setTimeout(r, 20));
      return new Response(
        JSON.stringify({ access_token: "coalesced_token_555" }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    return new Response("{}", { status: 404 });
  };

  // Dispatch 4 concurrent refresh calls with the same failed token
  const results = await Promise.all([
    client.refreshAccessTokenCoordinated("stale_concurrent_token"),
    client.refreshAccessTokenCoordinated("stale_concurrent_token"),
    client.refreshAccessTokenCoordinated("stale_concurrent_token"),
    client.refreshAccessTokenCoordinated("stale_concurrent_token"),
  ]);

  assert.equal(refreshFetchCount, 1, "Must perform exactly one network fetch");
  for (const res of results) {
    assert.equal(res, "coalesced_token_555");
  }
});

test("Production Test 4: Operation-ID lifecycle - cleared immediately on HTTP 200 OK so independent refreshes use distinct IDs", async () => {
  resetTestState();
  const capturedOpIds = [];

  globalThis.fetch = async (url, options = {}) => {
    if (url.includes("/api/v1/auth/refresh")) {
      capturedOpIds.push(options.headers?.["X-Refresh-Operation-Id"]);
      return new Response(
        JSON.stringify({ access_token: `token_${capturedOpIds.length}` }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    return new Response("{}", { status: 404 });
  };

  // First refresh operation
  const token1 = await client.refreshAccessTokenCoordinated();
  assert.equal(token1, "token_1");

  // Verify PENDING_OP_KEY was cleared on success
  const pendingAfterSuccess = mockLocalStorage.getItem("taskflow_pending_refresh_op");
  assert.equal(pendingAfterSuccess, null, "Pending op ID must be cleared immediately upon 200 OK");

  // Subsequent independent refresh
  const token2 = await client.refreshAccessTokenCoordinated(token1);
  assert.equal(token2, "token_2");

  assert.equal(capturedOpIds.length, 2);
  assert.notEqual(
    capturedOpIds[0],
    capturedOpIds[1],
    "Independent refresh operations must NOT reuse operation IDs"
  );
});

test("Production Test 5: Operation-ID lifecycle - preserved on network failure for idempotent retry", async () => {
  resetTestState();
  let attempt = 0;
  const capturedOpIds = [];

  globalThis.fetch = async (url, options = {}) => {
    if (url.includes("/api/v1/auth/refresh")) {
      attempt++;
      capturedOpIds.push(options.headers?.["X-Refresh-Operation-Id"]);
      if (attempt === 1) {
        throw new TypeError("Network connection failed");
      }
      return new Response(
        JSON.stringify({ access_token: "recovered_token" }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    return new Response("{}", { status: 404 });
  };

  // Attempt 1 fails due to network error
  await assert.rejects(
    () => client.refreshAccessTokenCoordinated(),
    /Network connection failed/
  );

  // Verify PENDING_OP_KEY is retained for retry
  const pendingAfterNetErr = mockLocalStorage.getItem("taskflow_pending_refresh_op");
  assert.ok(pendingAfterNetErr, "Pending op ID must be retained after network error for retry");

  // Attempt 2 succeeds
  const recoveredToken = await client.refreshAccessTokenCoordinated();
  assert.equal(recoveredToken, "recovered_token");

  assert.equal(capturedOpIds.length, 2);
  assert.equal(
    capturedOpIds[0],
    capturedOpIds[1],
    "Retry of failed operation must reuse same operation ID for idempotent recovery"
  );
  assert.equal(
    mockLocalStorage.getItem("taskflow_pending_refresh_op"),
    null,
    "Pending op ID must be cleared after retry succeeds"
  );
});

test("Production Test 6: Bounded 401 retries - apiClient retries protected request at most once without wiping valid session", async () => {
  resetTestState();
  let protectedEndpointCalls = 0;
  let refreshCalls = 0;

  useAuthStore.getState().setAccessToken("expired_client_token");

  globalThis.fetch = async (url) => {
    if (url.includes("/api/v1/auth/refresh")) {
      refreshCalls++;
      return new Response(
        JSON.stringify({ access_token: "replacement_still_rejected" }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    if (url.includes("/api/v1/protected-resource")) {
      protectedEndpointCalls++;
      // Always returns 401
      return new Response(
        JSON.stringify({ error: { code: "UNAUTHORIZED", message: "Invalid credentials" } }),
        { status: 401, headers: { "Content-Type": "application/json" } }
      );
    }
    return new Response("{}", { status: 404 });
  };

  await assert.rejects(
    () => client.apiClient("/protected-resource"),
    (err) => err instanceof client.ApiError && err.status === 401
  );

  // Initial call (401) + refresh (200) + retry call (401) = 2 protected calls, 1 refresh call
  assert.equal(protectedEndpointCalls, 2, "Must retry protected request at most once");
  assert.equal(refreshCalls, 1, "Must invoke refresh at most once");
  // Finding 3: An arbitrary protected endpoint returning 401 after a successful refresh
  // must NOT log out the user or wipe the newly issued access token without evidence of session termination
  assert.equal(
    useAuthStore.getState().accessToken,
    "replacement_still_rejected",
    "Must preserve active session when arbitrary protected endpoint fails without session revocation evidence"
  );
});

test("Production Test 7: Post-logout resurrection prevention - late refresh response discarded when logout occurred in flight", async () => {
  resetTestState();

  useAuthStore.getState().setAccessToken("initial_active_token");

  let resolveRefreshFetch;
  const refreshFetchPromise = new Promise((resolve) => {
    resolveRefreshFetch = resolve;
  });

  globalThis.fetch = async (url) => {
    if (url.includes("/api/v1/auth/refresh")) {
      await refreshFetchPromise;
      return new Response(
        JSON.stringify({ access_token: "late_resurrected_token" }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    if (url.includes("/api/v1/auth/logout")) {
      return new Response("{}", { status: 200 });
    }
    return new Response("{}", { status: 404 });
  };

  // Start refresh in-flight
  const refreshPromise = client.refreshAccessTokenCoordinated("initial_active_token");

  // User logs out while refresh request is in flight
  await useAuthStore.getState().logout();
  assert.equal(useAuthStore.getState().accessToken, null);
  assert.equal(useAuthStore.getState().isAuthenticated, false);

  // Late refresh response arrives from backend
  resolveRefreshFetch();

  // The in-flight refresh promise must reject with SESSION_EXPIRED
  await assert.rejects(refreshPromise, (err) => {
    return err instanceof client.ApiError && err.code === "SESSION_EXPIRED";
  });

  // Access token must NOT be resurrected in the store
  assert.equal(
    useAuthStore.getState().accessToken,
    null,
    "Access token must NOT be restored after logout"
  );
  assert.equal(
    useAuthStore.getState().isAuthenticated,
    false,
    "User must remain logged out"
  );
});

test("Production Test 8: Cross-tab message validation - stale AUTH_REFRESH_SUCCESS broadcast with mismatched epoch is ignored", async () => {
  resetTestState();

  useAuthStore.getState().setAccessToken(null);

  // Establish a current epoch after logout
  const currentEpoch = client.bumpAuthEpoch();

  // Create an external channel to simulate a message from another tab
  const remoteTabChannel = new MockBroadcastChannel("taskflow_auth_channel");

  // Send a stale broadcast from an older epoch
  remoteTabChannel.postMessage({
    type: "AUTH_REFRESH_SUCCESS",
    accessToken: "stale_broadcasted_token",
    epoch: currentEpoch - 100, // Stale epoch!
  });

  // Give microtasks time to run
  await new Promise((r) => setTimeout(r, 10));

  // The stale token must be rejected
  assert.equal(
    useAuthStore.getState().accessToken,
    null,
    "Must discard AUTH_REFRESH_SUCCESS from stale epoch"
  );

  remoteTabChannel.close();
});

test("Production Test 9: Cross-tab logout - AUTH_LOGOUT broadcast clears token and resets store", async () => {
  resetTestState();

  useAuthStore.getState().setAccessToken("valid_tab_token");
  assert.equal(useAuthStore.getState().accessToken, "valid_tab_token");

  const remoteTabChannel = new MockBroadcastChannel("taskflow_auth_channel");
  const newEpoch = client.bumpAuthEpoch();

  remoteTabChannel.postMessage({
    type: "AUTH_LOGOUT",
    epoch: newEpoch,
  });

  await new Promise((r) => setTimeout(r, 10));

  assert.equal(
    useAuthStore.getState().accessToken,
    null,
    "Cross-tab AUTH_LOGOUT must clear access token"
  );
  assert.equal(
    useAuthStore.getState().isAuthenticated,
    false,
    "Cross-tab AUTH_LOGOUT must set isAuthenticated to false"
  );

  remoteTabChannel.close();
});

test("Production Test 10: Invariant check - Access tokens are NEVER written to localStorage or sessionStorage", async () => {
  resetTestState();

  useAuthStore.getState().setAccessToken("sensitive_jwt_token_12345");
  client.bumpAuthEpoch();

  globalThis.fetch = async (url) => {
    if (url.includes("/api/v1/auth/refresh")) {
      return new Response(
        JSON.stringify({ access_token: "sensitive_jwt_token_67890" }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    return new Response("{}", { status: 200 });
  };

  await client.refreshAccessTokenCoordinated();

  // Inspect every item in localStorage
  for (const [key, value] of mockLocalStorage.entries()) {
    assert.doesNotMatch(
      key,
      /token/i,
      `Storage key '${key}' must not contain tokens`
    );
    assert.doesNotMatch(
      value,
      /sensitive_jwt_token/i,
      `Storage value at key '${key}' must never contain access token`
    );
  }

  // Inspect sessionStorage
  for (const [key, value] of mockSessionStorage.entries()) {
    assert.doesNotMatch(
      key,
      /token/i,
      `SessionStorage key '${key}' must not contain tokens`
    );
    assert.doesNotMatch(
      value,
      /sensitive_jwt_token/i,
      `SessionStorage value at key '${key}' must never contain access token`
    );
  }
});

test("Production Test 11 (Scenario 2): User A refresh in flight -> User B logs in -> old refresh succeeds -> User B authentication preserved", async () => {
  resetTestState();

  // User A logs in
  useAuthStore.getState().setAuth(
    { id: "user-a", email: "a@example.com", full_name: "User A" },
    "token_user_a"
  );
  assert.equal(useAuthStore.getState().user.id, "user-a");

  let resolveRefreshFetch;
  const refreshFetchPromise = new Promise((resolve) => {
    resolveRefreshFetch = resolve;
  });

  globalThis.fetch = async (url) => {
    if (url.includes("/api/v1/auth/refresh")) {
      await refreshFetchPromise;
      return new Response(
        JSON.stringify({ access_token: "resurrected_token_user_a" }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    return new Response("{}", { status: 404 });
  };

  // User A triggers refresh
  const refreshPromise = client.refreshAccessTokenCoordinated("token_user_a");

  // User B logs in before User A's refresh completes
  useAuthStore.getState().setAuth(
    { id: "user-b", email: "b@example.com", full_name: "User B" },
    "token_user_b"
  );
  assert.equal(useAuthStore.getState().user.id, "user-b");
  assert.equal(useAuthStore.getState().accessToken, "token_user_b");

  // User A's refresh finishes
  resolveRefreshFetch();

  // The refresh initiated by User A must reject with SESSION_EXPIRED
  await assert.rejects(refreshPromise, (err) => {
    return err instanceof client.ApiError && err.code === "SESSION_EXPIRED";
  });

  // User B's state must be completely untouched
  assert.equal(useAuthStore.getState().user.id, "user-b");
  assert.equal(useAuthStore.getState().accessToken, "token_user_b");
  assert.equal(useAuthStore.getState().isAuthenticated, true);
});

test("Production Test 12 (Scenario 3): User A logs out -> delayed AUTH_LOGOUT broadcast arrives after User B logs in -> User B remains active", async () => {
  resetTestState();

  // User A logged in
  useAuthStore.getState().setAuth(
    { id: "user-a", email: "a@example.com", full_name: "User A" },
    "token_user_a"
  );
  const userASessionId = client.getSessionId();
  const userAEpoch = client.getAuthEpoch();

  // User A logs out
  client.notifyLogout();

  // User B logs in
  useAuthStore.getState().setAuth(
    { id: "user-b", email: "b@example.com", full_name: "User B" },
    "token_user_b"
  );
  assert.equal(useAuthStore.getState().accessToken, "token_user_b");
  assert.equal(useAuthStore.getState().isAuthenticated, true);

  // Stale/delayed logout message from User A arrives via BroadcastChannel
  const remoteTabChannel = new MockBroadcastChannel("taskflow_auth_channel");
  remoteTabChannel.postMessage({
    type: "AUTH_LOGOUT",
    epoch: userAEpoch,
    sessionId: userASessionId,
  });

  // Let microtasks run
  await new Promise((r) => setTimeout(r, 10));

  // User B must still be authenticated!
  assert.equal(
    useAuthStore.getState().accessToken,
    "token_user_b",
    "Stale logout broadcast must not clear User B's token"
  );
  assert.equal(
    useAuthStore.getState().isAuthenticated,
    true,
    "Stale logout broadcast must not log out User B"
  );

  remoteTabChannel.close();
});

test("Production Test 13 (Scenario 5): HTTP 502 Bad Gateway preserves operation ID for idempotent recovery", async () => {
  resetTestState();
  let attempt = 0;
  const capturedOpIds = [];

  globalThis.fetch = async (url, options = {}) => {
    if (url.includes("/api/v1/auth/refresh")) {
      attempt++;
      capturedOpIds.push(options.headers?.["X-Refresh-Operation-Id"]);
      if (attempt === 1) {
        return new Response(
          JSON.stringify({ error: { code: "BAD_GATEWAY", message: "Gateway error" } }),
          { status: 502, headers: { "Content-Type": "application/json" } }
        );
      }
      return new Response(
        JSON.stringify({ access_token: "recovered_token_after_502" }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    return new Response("{}", { status: 404 });
  };

  // Attempt 1 fails with 502
  await assert.rejects(
    () => client.refreshAccessTokenCoordinated(),
    (err) => err instanceof client.ApiError && err.status === 502
  );

  // Operation ID must NOT be cleared on 502
  const pendingOp = mockLocalStorage.getItem("taskflow_pending_refresh_op");
  assert.ok(pendingOp, "Pending op ID must be retained after HTTP 502 for recovery");

  // Attempt 2 succeeds
  const token = await client.refreshAccessTokenCoordinated();
  assert.equal(token, "recovered_token_after_502");

  assert.equal(capturedOpIds.length, 2);
  assert.equal(
    capturedOpIds[0],
    capturedOpIds[1],
    "Retry after 502 must reuse the same operation ID for idempotent backend recovery"
  );
});

test("Production Test 14 (Scenario 6): Transient refresh error (HTTP 503) does not log out active session in apiClient", async () => {
  resetTestState();

  useAuthStore.getState().setAuth(
    { id: "active-user", email: "user@example.com", full_name: "Active User" },
    "token_before_503"
  );

  globalThis.fetch = async (url) => {
    if (url.includes("/api/v1/protected-resource")) {
      return new Response(
        JSON.stringify({ error: { code: "TOKEN_EXPIRED", message: "Expired" } }),
        { status: 401, headers: { "Content-Type": "application/json" } }
      );
    }
    if (url.includes("/api/v1/auth/refresh")) {
      return new Response(
        JSON.stringify({ error: { code: "SERVICE_UNAVAILABLE", message: "Down" } }),
        { status: 503, headers: { "Content-Type": "application/json" } }
      );
    }
    return new Response("{}", { status: 404 });
  };

  await assert.rejects(
    () => client.apiClient("/protected-resource"),
    (err) => err instanceof client.ApiError && err.status === 503
  );

  // User must still be authenticated! Active session is NOT cleared on 503
  assert.equal(
    useAuthStore.getState().accessToken,
    "token_before_503",
    "Transient 503 must not wipe access token"
  );
  assert.equal(
    useAuthStore.getState().isAuthenticated,
    true,
    "Transient 503 must not log out active user"
  );
});

test("Production Test 15 (Scenario 7): New login does not inherit an unresolved operation ID from previous session", async () => {
  resetTestState();

  // User A logs in
  useAuthStore.getState().setAuth(
    { id: "user-a", email: "a@example.com", full_name: "User A" },
    "token_user_a"
  );

  // Simulate User A having an unresolved refresh operation (e.g. network failure)
  let userAOpId = null;
  globalThis.fetch = async (url, options = {}) => {
    if (url.includes("/api/v1/auth/refresh")) {
      userAOpId = options.headers?.["X-Refresh-Operation-Id"];
      throw new TypeError("Failed to fetch");
    }
    return new Response("{}", { status: 404 });
  };

  await assert.rejects(() => client.refreshAccessTokenCoordinated("token_user_a"));
  assert.ok(userAOpId);
  assert.ok(mockLocalStorage.getItem("taskflow_pending_refresh_op"));

  // Now User B logs in (new session)
  useAuthStore.getState().setAuth(
    { id: "user-b", email: "b@example.com", full_name: "User B" },
    "token_user_b"
  );

  // Verify pending operation from User A was cleared on login
  assert.equal(
    mockLocalStorage.getItem("taskflow_pending_refresh_op"),
    null,
    "New login must clear previous session pending operation"
  );

  // User B triggers refresh
  let userBOpId = null;
  globalThis.fetch = async (url, options = {}) => {
    if (url.includes("/api/v1/auth/refresh")) {
      userBOpId = options.headers?.["X-Refresh-Operation-Id"];
      return new Response(
        JSON.stringify({ access_token: "token_user_b_refreshed" }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    return new Response("{}", { status: 404 });
  };

  const refreshedB = await client.refreshAccessTokenCoordinated("token_user_b");
  assert.equal(refreshedB, "token_user_b_refreshed");
  assert.notEqual(
    userBOpId,
    userAOpId,
    "User B must NEVER reuse User A's unresolved operation ID"
  );
});

test("Production Test 16 (Scenario 8): Stale refresh response must not clear a newer pending operation", async () => {
  resetTestState();

  // Manually set a newer pending operation ID in storage
  const newerOpId = "newer-op-id-999";
  mockLocalStorage.setItem(
    "taskflow_pending_refresh_op",
    JSON.stringify({ operation_id: newerOpId, created_at: Date.now() })
  );

  // An older operation (older-op-id-111) completes and tries to clear storage
  client.clearPendingOperation("older-op-id-111");

  // The newer operation ID must remain intact
  const stored = JSON.parse(mockLocalStorage.getItem("taskflow_pending_refresh_op"));
  assert.equal(
    stored.operation_id,
    newerOpId,
    "clearPendingOperation must NOT remove a newer operation ID"
  );

  // Clearing with matching ID clears it
  client.clearPendingOperation(newerOpId);
  assert.equal(
    mockLocalStorage.getItem("taskflow_pending_refresh_op"),
    null,
    "clearPendingOperation with matching ID clears storage"
  );
});

test("Production Test 17: DOMException AbortError does not log out user and preserves pending operation ID", async () => {
  resetTestState();

  useAuthStore.getState().setAuth(
    { id: "active-user", email: "user@example.com", full_name: "Active User" },
    "token_before_abort"
  );

  let capturedOpId = null;
  globalThis.fetch = async (url, options = {}) => {
    if (url.includes("/api/v1/protected-resource")) {
      return new Response(
        JSON.stringify({ error: { code: "TOKEN_EXPIRED", message: "Token expired" } }),
        { status: 401, headers: { "Content-Type": "application/json" } }
      );
    }
    if (url.includes("/api/v1/auth/refresh")) {
      capturedOpId = options.headers?.["X-Refresh-Operation-Id"];
      // Simulate DOMException / fetch AbortError
      const abortErr = new Error("The operation was aborted");
      abortErr.name = "AbortError";
      throw abortErr;
    }
    return new Response("{}", { status: 404 });
  };

  await assert.rejects(
    () => client.apiClient("/protected-resource"),
    (err) => client.isCancellationError(err)
  );

  // Finding 1: An aborted refresh MUST NOT destroy the active user session
  assert.equal(
    useAuthStore.getState().accessToken,
    "token_before_abort",
    "Cancellation error must preserve active access token"
  );
  assert.equal(
    useAuthStore.getState().isAuthenticated,
    true,
    "Cancellation error must preserve isAuthenticated state"
  );

  // Operation ID must be preserved for unresolved in-flight recovery
  const pendingOpRaw = mockLocalStorage.getItem("taskflow_pending_refresh_op");
  assert.ok(pendingOpRaw, "taskflow_pending_refresh_op must be preserved on cancellation");
  const parsed = JSON.parse(pendingOpRaw);
  assert.equal(parsed.operation_id, capturedOpId);
});

test("Production Test 18: Terminal refresh failure (401 on /auth/refresh) cleanly logs out user and clears credentials", async () => {
  resetTestState();

  useAuthStore.getState().setAuth(
    { id: "active-user", email: "user@example.com", full_name: "Active User" },
    "token_before_terminal_failure"
  );

  globalThis.fetch = async (url) => {
    if (url.includes("/api/v1/protected-resource")) {
      return new Response(
        JSON.stringify({ error: { code: "TOKEN_EXPIRED", message: "Token expired" } }),
        { status: 401, headers: { "Content-Type": "application/json" } }
      );
    }
    if (url.includes("/api/v1/auth/refresh")) {
      return new Response(
        JSON.stringify({ error: { code: "INVALID_REFRESH_TOKEN", message: "Token revoked" } }),
        { status: 401, headers: { "Content-Type": "application/json" } }
      );
    }
    return new Response("{}", { status: 404 });
  };

  await assert.rejects(
    () => client.apiClient("/protected-resource"),
    (err) => err instanceof client.ApiError && err.status === 401
  );

  // Terminal failure must cleanly log out the user and clear credentials
  assert.equal(
    useAuthStore.getState().accessToken,
    null,
    "Terminal 401 on /auth/refresh must wipe access token"
  );
  assert.equal(
    useAuthStore.getState().isAuthenticated,
    false,
    "Terminal 401 on /auth/refresh must set isAuthenticated to false"
  );
  assert.equal(
    mockLocalStorage.getItem("taskflow_pending_refresh_op"),
    null,
    "Terminal 401 must clear pending operation ID"
  );
});

test("Production Test 19: Cancelled old refresh completing after a new login preserves new login", async () => {
  resetTestState();

  // User A logs in
  useAuthStore.getState().setAuth(
    { id: "user-a", email: "a@example.com", full_name: "User A" },
    "token_user_a"
  );

  let finishOldRefresh;
  const oldRefreshPromise = new Promise((resolve) => {
    finishOldRefresh = resolve;
  });

  globalThis.fetch = async (url) => {
    if (url.includes("/api/v1/auth/refresh")) {
      await oldRefreshPromise;
      return new Response(
        JSON.stringify({ access_token: "resurrected_token_from_old_refresh" }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    return new Response("{}", { status: 404 });
  };

  // User A initiates refresh
  const refreshPromise = client.refreshAccessTokenCoordinated("token_user_a");

  // User A's request is aborted/abandoned client-side and User B logs in
  useAuthStore.getState().setAuth(
    { id: "user-b", email: "b@example.com", full_name: "User B" },
    "token_user_b"
  );
  assert.equal(useAuthStore.getState().accessToken, "token_user_b");

  // The old server refresh response finally completes
  finishOldRefresh();

  // Old refresh must fail due to session switch
  await assert.rejects(refreshPromise, (err) => {
    return err instanceof client.ApiError && err.code === "SESSION_EXPIRED";
  });

  // User B's active session is completely preserved and not overwritten
  assert.equal(
    useAuthStore.getState().accessToken,
    "token_user_b",
    "Old completed refresh must not overwrite User B's token"
  );
  assert.equal(
    useAuthStore.getState().user.id,
    "user-b",
    "Old completed refresh must not overwrite User B's profile"
  );
  assert.equal(
    useAuthStore.getState().isAuthenticated,
    true,
    "User B must remain authenticated"
  );
});

test("Production Test 20: Genuinely invalid active session (/auth/me returning 401, or ACCOUNT_INACTIVE) logs out active user", async () => {
  resetTestState();

  // Scenario 20a: Core profile endpoint (/auth/me) returning 401 on retry logs out
  useAuthStore.getState().setAuth(
    { id: "active-user", email: "user@example.com", full_name: "Active User" },
    "token_before_me_retry"
  );

  let meCalls = 0;
  globalThis.fetch = async (url) => {
    if (url.includes("/api/v1/auth/me")) {
      meCalls++;
      return new Response(
        JSON.stringify({ error: { code: "UNAUTHORIZED", message: "User not recognized" } }),
        { status: 401, headers: { "Content-Type": "application/json" } }
      );
    }
    if (url.includes("/api/v1/auth/refresh")) {
      return new Response(
        JSON.stringify({ access_token: "refreshed_token_for_me" }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    return new Response("{}", { status: 404 });
  };

  await assert.rejects(
    () => client.apiClient("/auth/me"),
    (err) => err instanceof client.ApiError && err.status === 401
  );

  assert.equal(meCalls, 2, "Must retry /auth/me once");
  assert.equal(
    useAuthStore.getState().accessToken,
    null,
    "/auth/me returning 401 on retry must log out active user"
  );
  assert.equal(
    useAuthStore.getState().isAuthenticated,
    false,
    "/auth/me returning 401 on retry must set isAuthenticated to false"
  );

  // Scenario 20b: Protected endpoint returning ACCOUNT_INACTIVE logs out
  resetTestState();
  useAuthStore.getState().setAuth(
    { id: "active-user", email: "user@example.com", full_name: "Active User" },
    "token_before_inactive"
  );

  globalThis.fetch = async (url) => {
    if (url.includes("/api/v1/protected-resource")) {
      return new Response(
        JSON.stringify({ error: { code: "ACCOUNT_INACTIVE", message: "Account has been deactivated" } }),
        { status: 401, headers: { "Content-Type": "application/json" } }
      );
    }
    if (url.includes("/api/v1/auth/refresh")) {
      return new Response(
        JSON.stringify({ access_token: "refreshed_token_inactive" }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    return new Response("{}", { status: 404 });
  };

  await assert.rejects(
    () => client.apiClient("/protected-resource"),
    (err) => err instanceof client.ApiError && err.code === "ACCOUNT_INACTIVE"
  );

  assert.equal(
    useAuthStore.getState().accessToken,
    null,
    "ACCOUNT_INACTIVE on retry must log out active user"
  );
  assert.equal(
    useAuthStore.getState().isAuthenticated,
    false,
    "ACCOUNT_INACTIVE on retry must set isAuthenticated to false"
  );
});

test("Production Test 21: Stale request from previous session cannot invalidate newer login on retry", async () => {
  resetTestState();

  // User A logs in
  useAuthStore.getState().setAuth(
    { id: "user-a", email: "a@example.com", full_name: "User A" },
    "token_user_a"
  );

  let finishProtectedCall;
  const protectedCallPromise = new Promise((resolve) => {
    finishProtectedCall = resolve;
  });

  globalThis.fetch = async (url) => {
    if (url.includes("/api/v1/protected-resource")) {
      await protectedCallPromise;
      return new Response(
        JSON.stringify({ error: { code: "UNAUTHORIZED", message: "Invalid credentials" } }),
        { status: 401, headers: { "Content-Type": "application/json" } }
      );
    }
    if (url.includes("/api/v1/auth/refresh")) {
      return new Response(
        JSON.stringify({ access_token: "refreshed_token_user_a" }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    return new Response("{}", { status: 404 });
  };

  // User A starts protected request
  const reqPromise = client.apiClient("/protected-resource");

  // User A logs out and User B logs in
  useAuthStore.getState().setAuth(
    { id: "user-b", email: "b@example.com", full_name: "User B" },
    "token_user_b"
  );

  // Allow protected call to return 401
  finishProtectedCall();

  // Protected call should fail with SESSION_EXPIRED or refresh failure, without logging out User B
  await assert.rejects(reqPromise);

  assert.equal(
    useAuthStore.getState().accessToken,
    "token_user_b",
    "User B's token must not be cleared by stale request from User A"
  );
  assert.equal(
    useAuthStore.getState().user.id,
    "user-b",
    "User B must remain logged in"
  );
});

test("Production Test 22: Network TypeError during refresh preserves active session and operation ID", async () => {
  resetTestState();

  useAuthStore.getState().setAuth(
    { id: "active-user", email: "user@example.com", full_name: "Active User" },
    "token_before_type_error"
  );

  let capturedOpId = null;
  globalThis.fetch = async (url, options = {}) => {
    if (url.includes("/api/v1/protected-resource")) {
      return new Response(
        JSON.stringify({ error: { code: "TOKEN_EXPIRED", message: "Token expired" } }),
        { status: 401, headers: { "Content-Type": "application/json" } }
      );
    }
    if (url.includes("/api/v1/auth/refresh")) {
      capturedOpId = options.headers?.["X-Refresh-Operation-Id"];
      throw new TypeError("Failed to fetch");
    }
    return new Response("{}", { status: 404 });
  };

  await assert.rejects(
    () => client.apiClient("/protected-resource"),
    (err) => err instanceof TypeError
  );

  // Network TypeError must not destroy active session
  assert.equal(
    useAuthStore.getState().accessToken,
    "token_before_type_error",
    "Network TypeError must preserve access token"
  );
  assert.equal(
    useAuthStore.getState().isAuthenticated,
    true,
    "Network TypeError must preserve isAuthenticated"
  );

  // Operation ID must be preserved for Scenario A recovery
  const pendingOpRaw = mockLocalStorage.getItem("taskflow_pending_refresh_op");
  assert.ok(pendingOpRaw, "taskflow_pending_refresh_op must be preserved on network TypeError");
  const parsed = JSON.parse(pendingOpRaw);
  assert.equal(parsed.operation_id, capturedOpId);
});
