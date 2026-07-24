import type { ResponseParser } from "../lib/api/client";

export interface MeResponse {
  user: {
    id: string;
    username: string;
    avatar: string | null;
  };
}

export interface OkResponse {
  ok: boolean;
}

function asRecord(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`Invalid ${label} response.`);
  }
  return value as Record<string, unknown>;
}

function requiredString(value: unknown, label: string): string {
  if (typeof value !== "string") throw new Error(`Invalid ${label} response.`);
  return value;
}

export const MeResponseSchema: ResponseParser<MeResponse> = {
  parse(value) {
    const response = asRecord(value, "session");
    const user = asRecord(response.user, "session user");
    const avatar = user.avatar;
    if (avatar !== null && typeof avatar !== "string") {
      throw new Error("Invalid session user response.");
    }

    return {
      user: {
        id: requiredString(user.id, "session user"),
        username: requiredString(user.username, "session user"),
        avatar,
      },
    };
  },
};

export const OkResponseSchema: ResponseParser<OkResponse> = {
  parse(value) {
    const response = asRecord(value, "operation");
    if (typeof response.ok !== "boolean") throw new Error("Invalid operation response.");
    return { ok: response.ok };
  },
};
