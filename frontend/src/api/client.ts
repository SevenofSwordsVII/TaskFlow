/**
 * TaskFlow API client with Bearer token injection,
 * cross-tab refresh coordination via Web Locks, and 401 refresh interceptor.
 */

export interface ApiErrorPayload {
  error: {
    code: string;
    message: string;
    details?: unknown;
  };
}

export class ApiError extends Error {
  status: number;
  code: string;
  details?: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

// Global in-memory access token getter and setter hooks
let getAccessToken: () => string | null = () => null;
let setAccessToken: (token: string | null) => void = () => {};
let onLogout: () => void = () => {};

export function configureAuthStoreHooks(
  getToken: () => string | null,
  setToken: (token: string | null) => void,
  logout: () => void
) {
  getAccessToken = getToken;
  setAccessToken = setToken;
  onLogout = logout;
  initAuthChannel();
}

/**
 * Error classification policy:
 * 1. Cancellation errors: AbortError (DOMException, AbortSignal, or generic Error with name "AbortError").
 *    - Never logs out the user.
 *    - Preserves pending operation ID if in-flight server outcome is unknown.
 * 2. Transient infrastructure errors: TypeError (network fetch failure), ApiError with HTTP status >= 500 (500, 502, 503, 504).
 *    - Never logs out the user.
 *    - Preserves pending operation ID for idempotent backend recovery under Scenario A.
 * 3. Client conflict errors: ApiError with HTTP status 409 (OPERATION_ID_REUSED).
 *    - Explicitly clears the stale pending operation ID.
 * 4. Terminal authentication rejections: ApiError with HTTP status 401/403 directly from /auth/refresh.
 *    - Logs out the active user session and clears credentials if the active session matches.
 */
export function isCancellationError(err: unknown): boolean {
  if (!err || typeof err !== "object") return false;
  const anyErr = err as { name?: string; message?: string };
  return (
    anyErr.name === "AbortError" ||
    (typeof anyErr.message === "string" && anyErr.message.includes("aborted"))
  );
}

export function isTransientError(err: unknown): boolean {
  if (err instanceof TypeError) {
    return true;
  }
  if (err instanceof ApiError && err.status >= 500) {
    return true;
  }
  return false;
}

const REFRESH_LOCK_NAME = "taskflow_auth_refresh";
const PENDING_OP_KEY = "taskflow_pending_refresh_op";
const AUTH_EPOCH_KEY = "taskflow_auth_epoch";
const AUTH_SESSION_KEY = "taskflow_auth_session_id";
const RECOVERY_WINDOW_MS = 60_000;
const AUTH_CHANNEL_NAME = "taskflow_auth_channel";

export type AuthBroadcastMessage =
  | { type: "AUTH_REFRESH_SUCCESS"; accessToken: string; epoch: number; sessionId?: string }
  | { type: "AUTH_LOGOUT"; epoch: number; sessionId?: string };

let authChannel: BroadcastChannel | null = null;
let currentSessionId: string | null = null;

export function getSessionId(): string | null {
  if (currentSessionId) {
    return currentSessionId;
  }
  try {
    const val = localStorage.getItem(AUTH_SESSION_KEY);
    if (val) {
      currentSessionId = val;
      return val;
    }
  } catch {
    // Storage read failed
  }
  return currentSessionId;
}

export function setSessionId(id: string | null): void {
  currentSessionId = id;
  try {
    if (id) {
      localStorage.setItem(AUTH_SESSION_KEY, id);
    } else {
      localStorage.removeItem(AUTH_SESSION_KEY);
    }
  } catch {
    // Storage write failed
  }
}

export function ensureSessionId(): string {
  let id = getSessionId();
  if (!id) {
    id = generateUUID();
    setSessionId(id);
  }
  return id;
}

export function startNewSession(): string {
  bumpAuthEpoch();
  clearPendingOperation();
  const id = generateUUID();
  setSessionId(id);
  return id;
}

export function getAuthEpoch(): number {
  try {
    const val = localStorage.getItem(AUTH_EPOCH_KEY);
    return val ? parseInt(val, 10) || 0 : 0;
  } catch {
    return 0;
  }
}

export function bumpAuthEpoch(): number {
  const current = getAuthEpoch();
  const next = Math.max(Date.now(), current + 1);
  try {
    localStorage.setItem(AUTH_EPOCH_KEY, next.toString());
  } catch {
    // Storage write failed
  }
  return next;
}

export function ensureAuthEpoch(): number {
  let epoch = getAuthEpoch();
  if (epoch === 0) {
    epoch = bumpAuthEpoch();
  }
  return epoch;
}

function initAuthChannel(): BroadcastChannel | null {
  if (typeof BroadcastChannel === "undefined") {
    return null;
  }
  if (!authChannel) {
    try {
      authChannel = new BroadcastChannel(AUTH_CHANNEL_NAME);
      authChannel.onmessage = (event: MessageEvent<AuthBroadcastMessage>) => {
        const data = event.data;
        if (!data || typeof data !== "object") return;
        if (data.type === "AUTH_LOGOUT") {
          const currentEpoch = getAuthEpoch();
          const activeSessionId = getSessionId();

          // Reject stale logout messages:
          // 1. If tagged with a different session ID than the currently active session
          if (data.sessionId && activeSessionId && data.sessionId !== activeSessionId) {
            return;
          }
          // 2. If epoch is strictly older than current local epoch
          if (typeof data.epoch === "number" && data.epoch < currentEpoch) {
            return;
          }

          // Guarded execution: all side effects reside strictly within the validated branch
          if (typeof data.epoch === "number" && data.epoch >= currentEpoch) {
            try {
              localStorage.setItem(AUTH_EPOCH_KEY, data.epoch.toString());
            } catch {
              // Ignore localStorage quota or access errors
            }
          }
          setSessionId(null);
          setAccessToken(null);
          clearPendingOperation();
          onLogout();
        } else if (
          data.type === "AUTH_REFRESH_SUCCESS" &&
          typeof data.accessToken === "string"
        ) {
          const currentEpoch = getAuthEpoch();
          const activeSessionId = getSessionId();

          // Reject stale refresh messages from previous sessions
          if (data.sessionId && activeSessionId && data.sessionId !== activeSessionId) {
            return;
          }
          // Reject stale messages from previous epochs or post-logout events
          if (typeof data.epoch === "number" && data.epoch === currentEpoch && currentEpoch > 0) {
            setAccessToken(data.accessToken);
          }
        }
      };
    } catch {
      authChannel = null;
    }
  }
  return authChannel;
}

export function broadcastAuthEvent(message: AuthBroadcastMessage): void {
  const channel = initAuthChannel();
  if (channel) {
    try {
      channel.postMessage(message);
    } catch {
      // Channel write failed or closed
    }
  }
}

export function notifyLogout(): void {
  const oldSessionId = getSessionId();
  const newEpoch = bumpAuthEpoch();
  clearPendingOperation();
  setSessionId(null);
  setAccessToken(null);
  broadcastAuthEvent({
    type: "AUTH_LOGOUT",
    epoch: newEpoch,
    sessionId: oldSessionId || undefined,
  });
}

function generateUUID(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

function getOrGenerateOperationId(sessionId?: string | null): string {
  try {
    const stored = localStorage.getItem(PENDING_OP_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);
      const isWithinWindow = Date.now() - parsed.created_at < RECOVERY_WINDOW_MS;
      const matchesSession = !sessionId || !parsed.session_id || parsed.session_id === sessionId;
      if (parsed.operation_id && isWithinWindow && matchesSession) {
        return parsed.operation_id;
      }
    }
  } catch {
    // Ignore parse errors and generate fresh
  }
  const opId = generateUUID();
  try {
    localStorage.setItem(
      PENDING_OP_KEY,
      JSON.stringify({
        operation_id: opId,
        created_at: Date.now(),
        ...(sessionId ? { session_id: sessionId } : {}),
      })
    );
  } catch {
    // LocalStorage write failed
  }
  return opId;
}

export function clearPendingOperation(expectedOpId?: string): void {
  try {
    if (expectedOpId) {
      const stored = localStorage.getItem(PENDING_OP_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        if (parsed.operation_id && parsed.operation_id !== expectedOpId) {
          // A newer operation has already replaced it; preserve the newer operation
          return;
        }
      }
    }
    localStorage.removeItem(PENDING_OP_KEY);
  } catch {
    // Ignore
  }
}

async function executeRefresh(
  expectedSessionId?: string | null,
  expectedEpoch?: number
): Promise<string> {
  const requestEpoch = expectedEpoch || ensureAuthEpoch();
  const requestSessionId = expectedSessionId || ensureSessionId();
  const opId = getOrGenerateOperationId(requestSessionId);

  // Network error: the operation is unresolved/in-flight.
  // Retain PENDING_OP_KEY so that an immediate retry (or a secondary tab)
  // retries with the SAME operation ID to recover idempotently under backend Scenario A.
  const response = await fetch("/api/v1/auth/refresh", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Refresh-Operation-Id": opId,
    },
    credentials: "include", // Send HttpOnly refresh cookie
  });

  if (!response.ok) {
    const status = response.status;
    const errData = await response.json().catch(() => null);
    const errCode = errData?.error?.code || "REFRESH_FAILED";
    const errMessage = errData?.error?.message || "Token refresh failed";

    // 1. Transient infrastructure and gateway errors (502, 503, 504, 500):
    // Preserve PENDING_OP_KEY so that subsequent retry reuses the same operation ID
    // if backend already committed rotation. Do NOT log out the user on transient errors.
    if (status === 502 || status === 503 || status === 504 || status === 500) {
      throw new ApiError(status, errCode, errMessage, errData?.error?.details);
    }

    // 2. Conflict (409 OPERATION_ID_REUSED):
    // Operation ID was previously bound to an incompatible session. Clear stale op.
    if (status === 409) {
      clearPendingOperation(opId);
      throw new ApiError(status, errCode, errMessage, errData?.error?.details);
    }

    // 3. Terminal session rejection (401, 403, etc.):
    // Validate whether the session has already changed while this request was in-flight.
    const currentEpoch = getAuthEpoch();
    const currentSessionId = getSessionId();
    if (
      (requestSessionId && currentSessionId && currentSessionId !== requestSessionId) ||
      (currentEpoch !== requestEpoch && currentEpoch > requestEpoch)
    ) {
      // Newer session already active; do not log out or clear the newer session.
      throw new ApiError(401, "SESSION_EXPIRED", "Session was terminated during token refresh.");
    }

    clearPendingOperation(opId);
    setAccessToken(null);
    notifyLogout();
    onLogout();
    throw new ApiError(status, errCode, errMessage, errData?.error?.details);
  }

  const data = await response.json();
  const newAccessToken = data.access_token;

  // The logical operation completed successfully.
  // Immediately clear PENDING_OP_KEY unless a newer operation has already replaced it.
  clearPendingOperation(opId);

  // Validate that no logout or session change occurred while the request was in-flight.
  const currentEpoch = getAuthEpoch();
  const currentSessionId = getSessionId();
  if (
    (requestSessionId && currentSessionId !== requestSessionId) ||
    currentEpoch !== requestEpoch ||
    requestEpoch === 0 ||
    !currentSessionId
  ) {
    // Logout or session switch occurred while refresh was in flight! Discard response to prevent resurrection.
    if (!currentSessionId) {
      setAccessToken(null);
    }
    throw new ApiError(401, "SESSION_EXPIRED", "Session was terminated during token refresh.");
  }

  setAccessToken(newAccessToken);
  broadcastAuthEvent({
    type: "AUTH_REFRESH_SUCCESS",
    accessToken: newAccessToken,
    epoch: requestEpoch,
    sessionId: requestSessionId,
  });
  return newAccessToken;
}

let activeRefreshPromise: Promise<string> | null = null;

export async function refreshAccessTokenCoordinated(
  failedToken?: string | null
): Promise<string> {
  const callingEpoch = ensureAuthEpoch();
  const callingSessionId = getSessionId();

  // 1. Join any existing in-flight refresh within this tab
  if (activeRefreshPromise) {
    const inFlightToken = await activeRefreshPromise;
    if (inFlightToken && inFlightToken !== failedToken) {
      return inFlightToken;
    }
  }

  // 2. Reuse refreshed token if already updated by another tab or request
  const currentToken = getAccessToken();
  if (currentToken && currentToken !== failedToken) {
    return currentToken;
  }

  const doRefresh = async (): Promise<string> => {
    // Check if session was terminated or changed while waiting for lock
    const currentEpoch = getAuthEpoch();
    const currentSessionId = getSessionId();
    if (
      currentEpoch !== callingEpoch ||
      (callingSessionId && currentSessionId !== callingSessionId) ||
      (callingSessionId && !currentSessionId)
    ) {
      throw new ApiError(401, "SESSION_EXPIRED", "Session was terminated during token refresh.");
    }

    // Re-check token inside execution boundary for the active session
    const tokenInside = getAccessToken();
    if (tokenInside && tokenInside !== failedToken) {
      return tokenInside;
    }

    return await executeRefresh(callingSessionId, callingEpoch);
  };

  activeRefreshPromise = (async () => {
    try {
      if (typeof navigator !== "undefined" && navigator.locks) {
        return await navigator.locks.request(REFRESH_LOCK_NAME, doRefresh);
      }
      return await doRefresh();
    } finally {
      activeRefreshPromise = null;
    }
  })();

  return await activeRefreshPromise;
}

export async function apiClient<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getAccessToken();
  const headers = new Headers(options.headers || {});

  if (!headers.has("Content-Type") && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const url = endpoint.startsWith("http")
    ? endpoint
    : endpoint.startsWith("/api")
      ? endpoint
      : `/api/v1${endpoint.startsWith("/") ? endpoint : `/${endpoint}`}`;

  let response = await fetch(url, {
    ...options,
    headers,
    credentials: "include",
  });

  // Handle 401 with coordinated refresh (exclude auth endpoints that should not trigger refresh)
  const isAuthExempt =
    endpoint.includes("/auth/token") ||
    endpoint.includes("/auth/refresh") ||
    endpoint.includes("/auth/logout") ||
    endpoint.includes("/auth/register");

  if (response.status === 401 && !isAuthExempt) {
    const preRefreshSessionId = ensureSessionId();
    const preRefreshEpoch = ensureAuthEpoch();
    let newToken: string;
    try {
      newToken = await refreshAccessTokenCoordinated(token);
    } catch (refreshErr) {
      // 1. Preserve active session on cancellation (AbortError) or transient network/5xx errors
      if (isCancellationError(refreshErr) || isTransientError(refreshErr)) {
        throw refreshErr;
      }

      // 2. Terminal refresh failure: verify session generation before clearing
      const postRefreshSessionId = getSessionId();
      const postRefreshEpoch = getAuthEpoch();
      const sessionIsActive =
        preRefreshSessionId &&
        postRefreshSessionId === preRefreshSessionId &&
        postRefreshEpoch === preRefreshEpoch;

      if (sessionIsActive) {
        setAccessToken(null);
        clearPendingOperation();
        onLogout();
      }
      throw new ApiError(401, "SESSION_EXPIRED", "Session expired, please log in again.");
    }

    // Validate that session hasn't switched before retrying protected request
    const postRefreshSessionId = getSessionId();
    const postRefreshEpoch = getAuthEpoch();
    if (
      !postRefreshSessionId ||
      postRefreshSessionId !== preRefreshSessionId ||
      postRefreshEpoch !== preRefreshEpoch
    ) {
      throw new ApiError(401, "SESSION_EXPIRED", "Session was terminated during token refresh.");
    }

    headers.set("Authorization", `Bearer ${newToken}`);
    response = await fetch(url, {
      ...options,
      headers,
      credentials: "include",
    });

    if (response.status === 401) {
      const retryErrorData = await response.json().catch(() => null);
      const errCode = retryErrorData?.error?.code || "UNAUTHORIZED";
      const errMessage = retryErrorData?.error?.message || "Unauthorized";

      // Distinguish endpoint-specific failure from genuine active session invalidation.
      // An arbitrary protected endpoint returning 401 after a successful token refresh
      // MUST NOT automatically destroy a valid authentication session without justification.
      // Only log out if:
      // a) The failure is from the core profile/identity endpoint (/auth/me), or
      // b) The backend explicitly signaled account invalidation (e.g. ACCOUNT_INACTIVE, USER_NOT_FOUND, SESSION_REVOKED).
      const isCoreIdentityEndpoint = endpoint.includes("/auth/me");
      const isAccountInvalidated =
        errCode === "ACCOUNT_INACTIVE" ||
        errCode === "USER_NOT_FOUND" ||
        errCode === "SESSION_REVOKED";

      const postRetrySessionId = getSessionId();
      const postRetryEpoch = getAuthEpoch();
      const sessionIsStillActive =
        preRefreshSessionId &&
        postRetrySessionId === preRefreshSessionId &&
        postRetryEpoch === preRefreshEpoch;

      if (sessionIsStillActive && (isCoreIdentityEndpoint || isAccountInvalidated)) {
        setAccessToken(null);
        clearPendingOperation();
        onLogout();
      }

      throw new ApiError(
        401,
        errCode,
        errMessage,
        retryErrorData?.error?.details
      );
    }
  }

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new ApiError(
      response.status,
      errorData?.error?.code || "HTTP_ERROR",
      errorData?.error?.message || `Request failed with status ${response.status}`,
      errorData?.error?.details
    );
  }

  if (response.status === 204) {
    return undefined as unknown as T;
  }

  return (await response.json()) as T;
}
