type TelemetryLevel = "info" | "warn";

export interface TelemetryEvent {
  name: string;
  durationMs?: number;
  ok?: boolean;
  details?: Record<string, unknown>;
}

function roundDuration(durationMs: number): number {
  return Math.round(durationMs * 10) / 10;
}

export function recordTelemetry(event: TelemetryEvent, level: TelemetryLevel = "info") {
  const payload = {
    ...event,
    ...(typeof event.durationMs === "number" ? { durationMs: roundDuration(event.durationMs) } : {})
  };
  const logger = level === "warn" ? console.warn : console.info;
  logger("[telemetry]", payload);
}

export function nowMs(): number {
  if (typeof performance !== "undefined" && typeof performance.now === "function") {
    return performance.now();
  }
  return Date.now();
}
