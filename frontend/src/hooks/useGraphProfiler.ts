import { useEffect, useRef } from "react";

interface UseGraphProfilerOptions {
  nodeCount: number;
  edgeCount: number;
  label?: string;
  thresholdMs?: number;
  onSample?: (payload: { durationMs: number; nodeCount: number; edgeCount: number }) => void;
}

const isProduction = import.meta.env.MODE === "production";
const SMALL_GRAPH_SAMPLE_CUTOFF = 24;

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
  const slowStreakRef = useRef(0);

  useEffect(() => {
    if (
      isProduction ||
      typeof performance === "undefined" ||
      typeof requestAnimationFrame === "undefined" ||
      typeof cancelAnimationFrame === "undefined"
    ) {
      return;
    }

    if (nodeCount + edgeCount < SMALL_GRAPH_SAMPLE_CUTOFF) {
      return;
    }

    startRef.current = performance.now();
    const handle = requestAnimationFrame(() => {
      if (startRef.current === null || typeof performance === "undefined") {
        return;
      }

      const durationMs = performance.now() - startRef.current;
      const effectiveThreshold = Math.max(thresholdMs, nodeCount >= 200 ? 20 : thresholdMs);

      if (durationMs >= effectiveThreshold) {
        const message = `[perf] ${label}: ${nodeCount} nodes / ${edgeCount} edges rendered in ${durationMs.toFixed(
          1
        )}ms`;
        console.info(message);
        slowStreakRef.current += 1;
        if (slowStreakRef.current >= 3 && durationMs >= effectiveThreshold * 1.25) {
          console.warn(
            `[perf] ${label}: slow render streak (${slowStreakRef.current}) over threshold ${effectiveThreshold}ms`
          );
          slowStreakRef.current = 0;
        }
      } else {
        slowStreakRef.current = 0;
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
