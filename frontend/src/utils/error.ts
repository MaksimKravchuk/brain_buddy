import { ApiError } from "../api/client";

export function getErrorMessage(error: unknown, fallback = "Something went wrong"): string {
  if (error instanceof ApiError) {
    const reference = error.correlationId ? ` (ref: ${error.correlationId})` : "";
    if (typeof error.payload === "object" && error.payload && "message" in error.payload) {
      const message = (error.payload as Record<string, unknown>).message;
      if (typeof message === "string" && message.trim().length > 0) {
        return `${message}${reference}`;
      }
    }
    return `${error.status}: ${error.message}${reference}`;
  }

  if (error instanceof Error) {
    return error.message;
  }

  if (typeof error === "string") {
    return error;
  }

  return fallback;
}
