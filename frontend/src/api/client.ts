import type { Envelope } from "@/types";

// Subpath-aware: import.meta.env.BASE_URL is the Vite `base` (e.g. "/alert-hub/"
// or "/"), so the API lives at <prefix>/api/v1. The ingress strips <prefix>
// before the backend; the browser-facing URL (incl. the auth cookie path) keeps
// it. VITE_API_BASE_URL still overrides for special setups.
export const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? `${import.meta.env.BASE_URL}api/v1`;

// Access-token persistence: kept in localStorage so a page refresh survives
// (the in-memory-only token cleared on reload = the logout-on-refresh bug). The
// httpOnly refresh cookie is the more XSS-resistant mechanism, but it isn't
// reaching the browser under the subpath deploy, so localStorage is the
// reliable carrier. Key matches the atlas-* convention (atlas-ui-theme).
const TOKEN_KEY = "atlas-access-token";

function readStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

let accessToken: string | null = readStoredToken();
let onUnauthorized: (() => void) | null = null;

export function setAccessToken(token: string | null) {
  accessToken = token;
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable (private mode) — fall back to in-memory only */
  }
}

export function getAccessToken() {
  return accessToken;
}

export function setOnUnauthorized(handler: () => void) {
  onUnauthorized = handler;
}

export class ApiRequestError extends Error {
  code: string;
  status: number;
  details?: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

async function refreshAccessToken(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE_URL}/auth/refresh`, {
      method: "POST",
      credentials: "include",
    });
    if (!res.ok) return false;
    const body = (await res.json()) as Envelope<{ access_token: string }>;
    setAccessToken(body.data.access_token);
    return true;
  } catch {
    return false;
  }
}

async function request<T>(
  method: string,
  path: string,
  options: { body?: unknown; params?: Record<string, string | undefined>; retry?: boolean } = {},
): Promise<Envelope<T>> {
  const url = new URL(`${BASE_URL}${path}`, window.location.origin);
  if (options.params) {
    for (const [k, v] of Object.entries(options.params)) {
      if (v !== undefined && v !== "") url.searchParams.set(k, v);
    }
  }

  const headers: Record<string, string> = {};
  if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;
  if (options.body !== undefined) headers["Content-Type"] = "application/json";

  const res = await fetch(url.toString(), {
    method,
    headers,
    credentials: "include",
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  // The auth endpoints own their own 401 semantics (bad credentials / no
  // refresh cookie) — don't run the session-refresh dance for them, or a
  // failed login surfaces a misleading "Session expired" instead of the
  // real error message.
  const isAuthEndpoint = path.startsWith("/auth/login") || path.startsWith("/auth/refresh");

  if (res.status === 401 && options.retry !== false && !isAuthEndpoint) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      return request<T>(method, path, { ...options, retry: false });
    }
    onUnauthorized?.();
    throw new ApiRequestError(401, "unauthorized", "Session expired");
  }

  let body: Envelope<T>;
  try {
    body = (await res.json()) as Envelope<T>;
  } catch {
    throw new ApiRequestError(res.status, "invalid_response", `HTTP ${res.status}`);
  }

  if (!res.ok || body.error) {
    throw new ApiRequestError(
      res.status,
      body.error?.code ?? "unknown",
      body.error?.message ?? `HTTP ${res.status}`,
      body.error?.details,
    );
  }

  return body;
}

export const api = {
  get: <T>(path: string, params?: Record<string, string | undefined>) =>
    request<T>("GET", path, { params }),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, { body }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>("PATCH", path, { body }),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, { body }),
  delete: <T>(path: string) => request<T>("DELETE", path),
};
