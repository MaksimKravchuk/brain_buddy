import { describe, expect, it } from "vitest";

import { parseOpenTaskState } from "../taskHooks";

describe("taskHooks", () => {
  it("parses supported open task states and falls back to next", () => {
    expect(parseOpenTaskState("inbox")).toBe("inbox");
    expect(parseOpenTaskState("next")).toBe("next");
    expect(parseOpenTaskState("waiting")).toBe("waiting");
    expect(parseOpenTaskState("someday")).toBe("someday");
    expect(parseOpenTaskState(undefined)).toBe("next");
    expect(parseOpenTaskState("completed")).toBe("next");
  });
});
