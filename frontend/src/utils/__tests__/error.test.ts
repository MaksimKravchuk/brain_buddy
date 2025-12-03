import { describe, expect, it } from "vitest";

import { ApiError } from "../../api/client";
import { getErrorMessage } from "../error";

describe("getErrorMessage", () => {
  it("prefers detail array messages from ApiError payload", () => {
    const apiError = new ApiError("Bad Request", 400, [{ msg: "Invalid tree payload" }], "corr-123");
    expect(getErrorMessage(apiError)).toBe("Invalid tree payload (ref: corr-123)");
  });

  it("falls back to status text when payload is empty", () => {
    const apiError = new ApiError("Bad Request", 400, null);
    expect(getErrorMessage(apiError)).toBe("400: Bad Request");
  });
});
