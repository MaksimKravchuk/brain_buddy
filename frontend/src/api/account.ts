/** Account-export download helper.
 *
 * Lives outside `apiClient` because the export is the one endpoint that
 * returns a binary attachment, and the core `request<T>` helper is
 * deliberately JSON-only.
 */

import { ApiError } from "./client";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api";

const FALLBACK_FILENAME = "brain-buddy-export.zip";

export function parseAttachmentFilename(disposition: string | null): string {
  const match = /filename="([^"]+)"/.exec(disposition ?? "");
  return match?.[1] ?? FALLBACK_FILENAME;
}

/** Hand a fetched blob to the browser as a named file download. */
function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/**
 * Download the caller's GDPR data export as a ZIP file.
 *
 * Resolves with the served filename once the download has been handed to the
 * browser; throws `ApiError` (with the correlation id) on failure.
 */
export async function downloadAccountExport(): Promise<string> {
  const response = await fetch(`${API_BASE_URL.replace(/\/$/, "")}/account/export`, {
    credentials: "include"
  });

  if (!response.ok) {
    const correlationId = response.headers.get("X-Correlation-ID") ?? undefined;
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      /* non-JSON error body: keep the null payload */
    }
    throw new ApiError(
      response.statusText || "Export failed",
      response.status,
      payload,
      correlationId
    );
  }

  const filename = parseAttachmentFilename(response.headers.get("Content-Disposition"));
  saveBlob(await response.blob(), filename);
  return filename;
}
