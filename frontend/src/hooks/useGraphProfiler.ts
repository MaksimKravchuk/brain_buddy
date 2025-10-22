import { useEffect, useRef } from "react";

interface UseGraphProfilerOptions {
  nodeCount: number;
  edgeCount: number;
  label?: string;
  thresholdMs?: number;
  onSample?: (payload: { durationMs: number; nodeCount: number; edgeCount: number }) => void;
}

const isProduction = import.meta.env.MODE === "production";

/**
 * Dev-only helper that logs render timing for large graphs so we can tune React Flow settings.
 */
export function useGraphProfiler({
  nodeCount,
  edgeCount,
  label = "TreeCanvas",
  thresholdMs = 12,
  onSample
}: UseGraphProfilerOptions): void {
  const startRef = useRef<number | null>(null);

  useEffect(() => {
    if (
      isProduction ||
      typeof performance === "undefined" ||
      typeof requestAnimationFrame === "undefined" ||
      typeof cancelAnimationFrame === "undefined"
    ) {
      return;
    }

    startRef.current = performance.now();
    const handle = requestAnimationFrame(() => {
      if (startRef.current === null || typeof performance === "undefined") {
        return;
      }

      const durationMs = performance.now() - startRef.current;
      if (durationMs >= thresholdMs) {
        const message = `[perf] ${label}: ${nodeCount} nodes / ${edgeCount} edges rendered in ${durationMs.toFixed(
          1
        )}ms`;
        console.info(message);
      }
      if (onSample) {
        onSample({ durationMs, nodeCount, edgeCount });
      }
    });

    return () => {
      cancelAnimationFrame(handle);
    };
  }, [nodeCount, edgeCount, label, onSample, thresholdMs]);
}
