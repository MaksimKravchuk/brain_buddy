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

export function normalizeServerUrl(raw: string): string {
  const trimmed = raw.trim().replace(/\/+$/, "");
  if (!trimmed) {
    return DEFAULT_SERVER_URL;
  }
  return trimmed;
}

export async function loadServerUrl(): Promise<string> {
  try {
    const stored = await AsyncStorage.getItem(STORAGE_KEY);
    return stored ? normalizeServerUrl(stored) : DEFAULT_SERVER_URL;
  } catch {
    return DEFAULT_SERVER_URL;
  }
}

export async function saveServerUrl(url: string): Promise<string> {
  const normalized = normalizeServerUrl(url);
  if (normalized === DEFAULT_SERVER_URL) {
    await AsyncStorage.removeItem(STORAGE_KEY);
  } else {
    await AsyncStorage.setItem(STORAGE_KEY, normalized);
  }
  return normalized;
}
