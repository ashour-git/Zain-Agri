/**
 * API client.
 *
 * The access token lives in a module-level variable — never localStorage,
 * sessionStorage or a readable cookie. The refresh token is an HttpOnly cookie
 * the server sets on `/api/v1/auth/*`, so it is invisible to this code by
 * design: the only thing the browser can do with it is send it back.
 *
 * On a 401 the client rotates the session once (deduplicated across concurrent
 * callers) and replays the original request.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

let accessToken: string | null = null;
let refreshInFlight: Promise<boolean> | null = null;

export class ApiRequestError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details?: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

type ErrorEnvelope = {
  error?: { code?: string; message?: string; details?: unknown };
};

async function toError(response: Response): Promise<ApiRequestError> {
  let body: ErrorEnvelope = {};
  try {
    body = (await response.json()) as ErrorEnvelope;
  } catch {
    // Non-JSON error body (proxy, gateway): fall through to a generic message.
  }
  return new ApiRequestError(
    response.status,
    body.error?.code ?? "http_error",
    body.error?.message ?? "تعذّر إكمال الطلب. حاول مرة أخرى.",
    body.error?.details,
  );
}

export function refreshAccessToken(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;

  const attempt = (async () => {
    try {
      const response = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      if (!response.ok) {
        accessToken = null;
        return false;
      }
      const data = (await response.json()) as { access_token: string };
      accessToken = data.access_token;
      return true;
    } catch {
      accessToken = null;
      return false;
    }
  })();

  refreshInFlight = attempt;
  void attempt.finally(() => {
    if (refreshInFlight === attempt) refreshInFlight = null;
  });
  return attempt;
}

type RequestOptions = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  /** Skip the Authorization header (login, register, refresh). */
  anonymous?: boolean;
  /** Internal: the retry after a silent refresh must not recurse. */
  isRetry?: boolean;
};

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, anonymous = false, isRetry = false } = options;

  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (!anonymous && accessToken) headers.Authorization = `Bearer ${accessToken}`;

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    credentials: "include",
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (response.status === 401 && !anonymous && !isRetry) {
    if (await refreshAccessToken()) {
      return apiRequest<T>(path, { ...options, isRetry: true });
    }
  }

  if (!response.ok) throw await toError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export { API_BASE };
