import { ApiError } from "../api/client";

type ErrorContext = { message: string; referenceId?: string };

function extractReferenceId(payload: unknown): string | undefined {
  if (payload && typeof payload === "object") {
    const candidate =
      (payload as Record<string, unknown>).reference_id ??
      (payload as Record<string, unknown>).reference ??
      (payload as Record<string, unknown>).referenceId;
    if (typeof candidate === "string" && candidate.trim().length > 0) {
      return candidate;
    }
  }
  return undefined;
}

function coerceDetailMessages(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (typeof item === "string") {
        return item;
      }
      if (item && typeof item === "object" && "msg" in item && typeof item.msg === "string") {
        return item.msg;
      }
      return null;
    })
    .filter((item): item is string => Boolean(item));
}

function extractPayloadMessage(payload: unknown): string | null {
  if (typeof payload === "string" && payload.trim().length > 0) {
    return payload;
  }

  if (Array.isArray(payload)) {
    const detailMessages = coerceDetailMessages(payload);
    if (detailMessages.length > 0) {
      return detailMessages.join("; ");
    }
  }

  if (payload && typeof payload === "object") {
    const message = (payload as Record<string, unknown>).message;
    if (typeof message === "string" && message.trim().length > 0) {
      return message;
    }

    const detail = (payload as Record<string, unknown>).detail;
    if (typeof detail === "string" && detail.trim().length > 0) {
      return detail;
    }
    const detailMessages = coerceDetailMessages(detail);
    if (detailMessages.length > 0) {
      return detailMessages.join("; ");
    }
  }

  return null;
}

function deriveErrorDetails(error: unknown, fallback: string): ErrorContext {
  if (error instanceof ApiError) {
    const payload = error.payload;
    const payloadMessage = extractPayloadMessage(payload);
    const referenceId = error.correlationId ?? extractReferenceId(payload);
    return {
      message: payloadMessage ?? `${error.status}: ${error.message}`,
      referenceId: referenceId ?? undefined
    };
  }

  if (error instanceof Error) {
    return { message: error.message };
  }

  if (typeof error === "string") {
    return { message: error };
  }

  return { message: fallback };
}

export function getErrorMessage(error: unknown, fallback = "Something went wrong"): string {
  const { message, referenceId } = deriveErrorDetails(error, fallback);
  return referenceId ? `${message} (ref: ${referenceId})` : message;
}

export function getErrorContext(error: unknown, fallback = "Something went wrong"): ErrorContext {
  return deriveErrorDetails(error, fallback);
}
