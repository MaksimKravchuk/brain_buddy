/**
 * Persisted API base URL.
 *
 * Default is the production frontend host, which proxies `/api` to the
 * private backend. For development against a LAN backend use
 * `http://<lan-ip>:8000/api` (the session cookie is non-Secure outside
 * production, so plain HTTP works there).
 */

import AsyncStorage from "@react-native-async-storage/async-storage";

export const DEFAULT_SERVER_URL = "https://brain-buddy-frontend.fly.dev/api";

const STORAGE_KEY = "bb.serverUrl";

/**
 * The URL the app is talking to right now.
 *
 * This is device configuration, not component state: it belongs to the module
 * that owns its persistence, and the api client reads it through
 * `currentServerUrl` instead of through a React ref synced during render.
 * `loadServerUrl` and `saveServerUrl` are the only two ways it changes.
 */
let current = DEFAULT_SERVER_URL;

export function currentServerUrl(): string {
  return current;
}

export function normalizeServerUrl(raw: string): string {
  const trimmed = raw.trim().replace(/\/+$/, "");
  if (!trimmed) {
    return DEFAULT_SERVER_URL;
  }
  return trimmed;
}

export async function loadServerUrl(): Promise<string> {
  current = await readStoredServerUrl();
  return current;
}

async function readStoredServerUrl(): Promise<string> {
  try {
    const stored = await AsyncStorage.getItem(STORAGE_KEY);
    return stored ? normalizeServerUrl(stored) : DEFAULT_SERVER_URL;
  } catch {
    // An unreadable store is not worth failing startup over: the default host
    // is always a valid destination.
    return DEFAULT_SERVER_URL;
  }
}

export async function saveServerUrl(url: string): Promise<string> {
  const normalized = normalizeServerUrl(url);
  if (normalized === DEFAULT_SERVER_URL) {
    // Storing the default would pin the app to today's host across upgrades.
    await AsyncStorage.removeItem(STORAGE_KEY);
  } else {
    await AsyncStorage.setItem(STORAGE_KEY, normalized);
  }
  current = normalized;
  return normalized;
}
