import { describe, expect, it } from "vitest";

import { ApiError } from "../../api/client";
import { getErrorContext, getErrorMessage } from "../error";

describe("getErrorMessage", () => {
  it("prefers detail array messages from ApiError payload", () => {
    const apiError = new ApiError("Bad Request", 400, [{ msg: "Invalid tree payload" }], "corr-123");
    expect(getErrorMessage(apiError)).toBe("Invalid tree payload (ref: corr-123)");
  });

  it("falls back to status text when payload is empty", () => {
    const apiError = new ApiError("Bad Request", 400, null);
    expect(getErrorMessage(apiError)).toBe("400: Bad Request");
  });

  it("extracts message, detail, and reference aliases from API payloads", () => {
    expect(getErrorMessage(new ApiError("Ignored", 422, { message: "Bad node", reference: "ref-1" }))).toBe(
      "Bad node (ref: ref-1)"
    );
    expect(getErrorMessage(new ApiError("Ignored", 422, { detail: "Bad relation", referenceId: "ref-2" }))).toBe(
      "Bad relation (ref: ref-2)"
    );
  });

  it("normalizes validation arrays and non-API errors for error displays", () => {
    expect(getErrorMessage(new ApiError("Invalid", 422, [{ msg: "One" }, "Two", { ignored: true }]))).toBe(
      "One; Two"
    );
    expect(getErrorContext(new Error("Network unavailable"))).toEqual({ message: "Network unavailable" });
    expect(getErrorContext("Plain failure")).toEqual({ message: "Plain failure" });
    expect(getErrorContext({ unknown: true }, "Fallback text")).toEqual({ message: "Fallback text" });
  });

  it("uses the fallback message when the payload is empty and error has no message", () => {
    expect(getErrorMessage(undefined, "Something went wrong")).toBe("Something went wrong");
    expect(getErrorContext(null, "Default fallback")).toEqual({ message: "Default fallback" });
  });

  it("joins detail arrays nested under an ApiError payload detail field", () => {
    const apiError = new ApiError("Invalid", 422, { detail: [{ msg: "Missing field" }, "Extra problem"] });
    expect(getErrorMessage(apiError)).toBe("Missing field; Extra problem");
  });

  it("keeps a string payload with only whitespace from falling back", () => {
    expect(getErrorMessage(new ApiError("Empty", 400, "   "))).toBe("400: Empty");
  });

  it("shows a plain string payload as the message", () => {
    expect(getErrorMessage(new ApiError("Ignored", 502, "Upstream is down"))).toBe("Upstream is down");
  });

  it("ignores empty and blank fields rather than showing them as the message", () => {
    expect(getErrorMessage(new ApiError("Conflict", 409, []))).toBe("409: Conflict");
    expect(getErrorMessage(new ApiError("Conflict", 409, { message: "  ", detail: "  " }))).toBe("409: Conflict");
    expect(getErrorMessage(new ApiError("Conflict", 409, { detail: [] }))).toBe("409: Conflict");
    expect(getErrorMessage(new ApiError("Conflict", 409, { detail: [{ code: 1 }] }))).toBe("409: Conflict");
  });

  it("ignores a blank reference id instead of appending an empty one", () => {
    expect(getErrorMessage(new ApiError("Ignored", 500, { message: "Broke", reference_id: "   " }))).toBe("Broke");
    expect(getErrorMessage(new ApiError("Ignored", 500, { message: "Broke", reference_id: 42 }))).toBe("Broke");
  });
});
