/**
 * Minimal typed fetch wrapper. Every backend error has {code, message}; we surface it
 * as an ApiError so components can branch on `code` and show `message`.
 */
export class ApiError extends Error {
  code: string;
  status: number;
  details?: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

const BASE = "/api";

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...(init.headers as Record<string, string>) };
  if (init.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";

  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "Could not reach the server. Is the backend running?");
  }

  if (res.status === 204) return undefined as T;

  let body: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = { code: "BAD_RESPONSE", message: text.slice(0, 200) };
    }
  }

  if (!res.ok) {
    const err = (body ?? {}) as { code?: string; message?: string; details?: unknown };
    throw new ApiError(res.status, err.code ?? `HTTP_${res.status}`, err.message ?? res.statusText, err.details);
  }
  return body as T;
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === "VALIDATION_ERROR" && e.details && typeof e.details === "object") {
      const first = Object.entries(e.details as Record<string, unknown>)[0];
      if (first) return `${first[0]}: ${Array.isArray(first[1]) ? first[1].join(" ") : String(first[1])}`;
    }
    return e.message;
  }
  if (e instanceof Error) return e.message;
  return "Unknown error";
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}
