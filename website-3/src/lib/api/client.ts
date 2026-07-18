// Typed fetch wrapper for the NovaGuard bot API (docs/API.md).
// Errors always surface as ApiError with the contract's stable `code`.
import type { ZodType } from "zod";

export const API_BASE: string = import.meta.env.PUBLIC_API_BASE ?? "";

export class ApiError extends Error {
  code: string;
  status: number;
  retryAfter?: number;
  details?: string[];

  constructor(
    message: string,
    code: string,
    status: number,
    retryAfter?: number,
    details?: string[],
  ) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.retryAfter = retryAfter;
    this.details = details;
  }
}

/** Login must be a full browser navigation, never a fetch (API.md). */
export function loginUrl(): string {
  return `${API_BASE}/api/v1/auth/login`;
}

export function inviteUrl(): string {
  return `${API_BASE}/api/v1/invite`;
}

export async function apiFetch<T>(
  path: string,
  schema: ZodType<T>,
  init?: RequestInit,
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1${path}`, {
      credentials: "include",
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError("Could not reach the bot.", "network_error", 0);
  }

  if (!res.ok) {
    const retryHeader = res.headers.get("Retry-After");
    const retryAfter = retryHeader ? Number(retryHeader) || undefined : undefined;
    let body: { error?: string; code?: string; details?: string[] } = {};
    try {
      body = await res.json();
    } catch {
      // non-JSON error body (proxy page, crash) — keep the fallback code
    }
    throw new ApiError(
      body.error ?? "Unexpected server error.",
      body.code ?? "internal_error",
      res.status,
      retryAfter,
      body.details,
    );
  }

  return schema.parse(await res.json());
}
