import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { downloadAccountExport, parseAttachmentFilename } from "../account";
import { ApiError } from "../client";

describe("parseAttachmentFilename", () => {
  it("extracts the served filename from a Content-Disposition header", () => {
    expect(
      parseAttachmentFilename('attachment; filename="brain-buddy-export-user_1-20260806.zip"')
    ).toBe("brain-buddy-export-user_1-20260806.zip");
  });

  it("falls back to a generic name when the header is missing or unparseable", () => {
    expect(parseAttachmentFilename(null)).toBe("brain-buddy-export.zip");
    expect(parseAttachmentFilename("attachment")).toBe("brain-buddy-export.zip");
  });
});

describe("downloadAccountExport", () => {
  const fetchMock = vi.fn();
  const clickSpy = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    clickSpy.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => "blob:export"),
      revokeObjectURL: vi.fn()
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(clickSpy);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("downloads the archive and resolves with the served filename", async () => {
    fetchMock.mockResolvedValue(
      new Response(new Blob(["zip-bytes"]), {
        status: 200,
        headers: {
          "Content-Type": "application/zip",
          "Content-Disposition": 'attachment; filename="my-export.zip"'
        }
      })
    );

    await expect(downloadAccountExport()).resolves.toBe("my-export.zip");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/account/export",
      expect.objectContaining({ credentials: "include" })
    );
    expect(clickSpy).toHaveBeenCalled();
  });

  it("throws an ApiError carrying the JSON error body and correlation id", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ message: "Authentication required." }), {
        status: 401,
        statusText: "Unauthorized",
        headers: {
          "Content-Type": "application/json",
          "X-Correlation-ID": "corr-1"
        }
      })
    );

    const failure = await downloadAccountExport().catch((error) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect(failure.status).toBe(401);
    expect(failure.correlationId).toBe("corr-1");
    expect(failure.payload).toEqual({ message: "Authentication required." });
    expect(clickSpy).not.toHaveBeenCalled();
  });

  it("copes with a non-JSON error body", async () => {
    fetchMock.mockResolvedValue(
      new Response("gateway exploded", { status: 502, statusText: "Bad Gateway" })
    );

    const failure = await downloadAccountExport().catch((error) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect(failure.status).toBe(502);
    expect(failure.payload).toBeNull();
  });

  it("names the failure itself when the response carries no status text", async () => {
    fetchMock.mockResolvedValue(new Response("", { status: 500, statusText: "" }));

    const failure = await downloadAccountExport().catch((error) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect(failure.message).toBe("Export failed");
  });
});
