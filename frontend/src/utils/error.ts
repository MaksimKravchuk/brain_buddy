import { ApiError } from "../api/client";

export function getErrorMessage(error: unknown, fallback = "Something went wrong"): string {
  if (error instanceof ApiError) {
    const reference = error.correlationId ? ` (ref: ${error.correlationId})` : "";
    const payload = error.payload;

    if (typeof payload === "string" && payload.trim().length > 0) {
      return `${payload}${reference}`;
    }

    if (Array.isArray(payload)) {
      const detailMessages = payload
        .map((item) => {
          if (typeof item === "string") {
            return item;
          }
          if (item && typeof item === "object" && "msg" in item && typeof item.msg === "string") {
            return item.msg;
          }
          return null;
        })
        .filter(Boolean);
      if (detailMessages.length > 0) {
        return `${detailMessages.join("; ")}${reference}`;
      }
    }

    if (payload && typeof payload === "object") {
      if ("message" in payload) {
        const message = (payload as Record<string, unknown>).message;
        if (typeof message === "string" && message.trim().length > 0) {
          return `${message}${reference}`;
        }
      }
      if ("detail" in payload) {
        const detail = (payload as Record<string, unknown>).detail;
        if (typeof detail === "string" && detail.trim().length > 0) {
          return `${detail}${reference}`;
        }
        if (Array.isArray(detail)) {
          const detailMessages = detail
            .map((item) => {
              if (typeof item === "string") {
                return item;
              }
              if (item && typeof item === "object" && "msg" in item && typeof item.msg === "string") {
                return item.msg;
              }
              return null;
            })
            .filter(Boolean);
          if (detailMessages.length > 0) {
            return `${detailMessages.join("; ")}${reference}`;
          }
        }
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
