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
});
