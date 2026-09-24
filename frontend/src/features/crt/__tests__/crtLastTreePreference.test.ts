import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CrtTreeListItem } from "../../../api/crt";
import {
  bindCrtLastTreePreferenceSession,
  clearCrtLastTreePreference,
  crtLastTreePreferenceKey,
  rememberCrtLastTreePreference,
  readCrtLastTreePreference,
  sweepCrtLastTreePreferences
} from "../crtLastTreePreference";
import { useAuthStore } from "../../../stores/authStore";

const scope = { ownerId: "owner-a", origin: "https://app.example.test" };

class PreferenceMemoryStorage implements Storage {
  private readonly values = new Map<string, string>();
  get length(): number { return this.values.size; }
  clear(): void { this.values.clear(); }
  getItem(key: string): string | null { return this.values.get(key) ?? null; }
  key(index: number): string | null { return [...this.values.keys()][index] ?? null; }
  removeItem(key: string): void { this.values.delete(key); }
  setItem(key: string, value: string): void { this.values.set(key, value); }
}

function tree(id: string, updated_at: string, owner_id: string | null = "owner-a"): CrtTreeListItem {
  return { id, name: id, updated_at, owner_id };
}

describe("019 last-tree preference", () => {
  beforeEach(() => {
    Object.defineProperty(window, "localStorage", { configurable: true, value: new PreferenceMemoryStorage() });
    window.localStorage.clear();
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-21T12:00:00Z"));
    useAuthStore.setState({ user: { id: "owner-a", email: "a@example.test" }, status: "authed" });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
    vi.useRealTimers();
    useAuthStore.setState({ user: null, status: "loading" });
  });

  it("resolves the stored tree only from the owner-scoped list and falls back to newest", () => {
    const trees = [
      tree("older", "2026-09-19T10:00:00Z"),
      tree("newest", "2026-09-20T10:00:00Z"),
      tree("other-owner", "2026-09-21T10:00:00Z", "owner-b")
    ];
    rememberCrtLastTreePreference(scope, "older");

    expect(readCrtLastTreePreference(scope, trees)?.id).toBe("older");
    expect(readCrtLastTreePreference({ ...scope, ownerId: "owner-b" }, trees)?.id).toBe("other-owner");

    clearCrtLastTreePreference(scope);
    expect(readCrtLastTreePreference(scope, trees)?.id).toBe("newest");
    expect(window.localStorage.getItem(crtLastTreePreferenceKey(scope))).toBeNull();
  });

  it("clears expired or deleted preferences without preventing a safe fallback", () => {
    const trees = [tree("newest", "2026-09-20T10:00:00Z"), tree("older", "2026-09-19T10:00:00Z")];
    rememberCrtLastTreePreference(scope, "older", Date.now() - 30 * 24 * 60 * 60 * 1000);
    expect(readCrtLastTreePreference(scope, trees)?.id).toBe("newest");
    expect(window.localStorage.getItem(crtLastTreePreferenceKey(scope))).toBeNull();

    rememberCrtLastTreePreference(scope, "older");
    const newest = trees[0];
    if (!newest) throw new Error("missing test tree");
    expect(readCrtLastTreePreference(scope, [newest])?.id).toBe("newest");
    expect(window.localStorage.getItem(crtLastTreePreferenceKey(scope))).toBeNull();
  });

  it("rejects malformed, future, stale, and owner-mismatched records while keeping the newest fallback", () => {
    const newest = tree("newest", "2026-09-20T10:00:00Z");
    const key = crtLastTreePreferenceKey(scope);
    window.localStorage.setItem(key, "not-json");
    expect(readCrtLastTreePreference(scope, [tree("older", "2026-09-19T10:00:00Z"), newest])).toEqual(newest);
    expect(window.localStorage.getItem(key)).toBeNull();

    window.localStorage.setItem(key, JSON.stringify({ last_tree_id: "older", updated_at: "2026-09-22T00:00:00Z" }));
    expect(readCrtLastTreePreference(scope, [tree("older", "2026-09-19T10:00:00Z"), newest])).toEqual(newest);
    window.localStorage.setItem(key, JSON.stringify({ last_tree_id: "older", updated_at: "2026-08-22T00:00:00Z" }));
    expect(readCrtLastTreePreference(scope, [tree("older", "2026-09-19T10:00:00Z"), newest])).toEqual(newest);
    expect(readCrtLastTreePreference(scope, [tree("other", "2026-09-21T00:00:00Z", "owner-b")])).toEqual(null);
  });

  it("tolerates invalid inputs and storage failures", () => {
    rememberCrtLastTreePreference({ ownerId: "", origin: "not-an-origin" }, "tree");
    rememberCrtLastTreePreference(scope, "", Number.NaN);
    expect(window.localStorage.length).toBe(0);

    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("quota"); });
    expect(() => rememberCrtLastTreePreference(scope, "tree")).not.toThrow();
    setItem.mockRestore();
    const getItem = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("revoked"); });
    expect(readCrtLastTreePreference(scope, [tree("newest", "2026-09-20T10:00:00Z")])).toEqual(tree("newest", "2026-09-20T10:00:00Z"));
    getItem.mockRestore();
    const removeItem = vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => { throw new Error("revoked"); });
    expect(() => clearCrtLastTreePreference(scope)).not.toThrow();
    removeItem.mockRestore();
  });

  it("sweeps malformed keys on focus and interval, and unbinds all listeners", () => {
    const key = crtLastTreePreferenceKey(scope);
    window.localStorage.setItem(key, "{}");
    const unbind = bindCrtLastTreePreferenceSession(scope.origin);
    expect(window.localStorage.getItem(key)).toBeNull();
    window.localStorage.setItem(key, "{}");
    window.dispatchEvent(new Event("focus"));
    expect(window.localStorage.getItem(key)).toBeNull();
    window.localStorage.setItem(key, "{}");
    vi.advanceTimersByTime(15 * 60 * 1000);
    expect(window.localStorage.getItem(key)).toBeNull();
    unbind();
    window.localStorage.setItem(key, "{}");
    window.dispatchEvent(new Event("focus"));
    expect(window.localStorage.getItem(key)).toBe("{}");
  });

  it("survives a revoked storage getter and cleanup methods that throw", () => {
    const descriptor = Object.getOwnPropertyDescriptor(window, "localStorage");
    Object.defineProperty(window, "localStorage", { configurable: true, get: () => { throw new Error("revoked"); } });
    expect(readCrtLastTreePreference(scope, [tree("newest", "2026-09-20T10:00:00Z")])).toEqual(tree("newest", "2026-09-20T10:00:00Z"));
    expect(() => rememberCrtLastTreePreference(scope, "tree")).not.toThrow();
    expect(() => clearCrtLastTreePreference(scope)).not.toThrow();
    expect(() => sweepCrtLastTreePreferences()).not.toThrow();
    if (descriptor) Object.defineProperty(window, "localStorage", descriptor);

    const key = crtLastTreePreferenceKey(scope);
    const throwingStorage: Storage = {
      get length() { return 1; },
      clear: vi.fn(),
      getItem: vi.fn(() => "{}"),
      key: vi.fn(() => key),
      removeItem: vi.fn(() => { throw new Error("revoked"); }),
      setItem: vi.fn()
    };
    Object.defineProperty(window, "localStorage", { configurable: true, value: throwingStorage });
    expect(readCrtLastTreePreference(scope, [tree("newest", "2026-09-20T10:00:00Z")])).toEqual(tree("newest", "2026-09-20T10:00:00Z"));
    expect(() => sweepCrtLastTreePreferences()).not.toThrow();
  });
  it("covers deterministic ties, authenticated null owners, and getter failures", () => {
    const tied = [tree("z-tree", "2026-09-20T10:00:00Z"), tree("a-tree", "2026-09-20T10:00:00Z")];
    expect(readCrtLastTreePreference({ ...scope, ownerId: "owner-a" }, tied)?.id).toBe("a-tree");
    const throwingStorage: Storage = {
      get length() { return 0; },
      clear: vi.fn(),
      getItem: vi.fn(() => { throw new Error("revoked"); }),
      key: vi.fn(() => null),
      removeItem: vi.fn(),
      setItem: vi.fn()
    };
    Object.defineProperty(window, "localStorage", { configurable: true, value: throwingStorage });
    expect(readCrtLastTreePreference(scope, tied)?.id).toBe("a-tree");
    const unbind = bindCrtLastTreePreferenceSession();
    useAuthStore.setState({ user: null, status: "authed" });
    unbind();
  });
  it("clears the previous owner on logout and on an authenticated account change", () => {
    rememberCrtLastTreePreference({ ownerId: "owner-a", origin: scope.origin }, "a");
    rememberCrtLastTreePreference({ ownerId: "owner-b", origin: scope.origin }, "b");
    const unbind = bindCrtLastTreePreferenceSession(scope.origin);
    useAuthStore.setState({ user: null, status: "anon" });
    expect(window.localStorage.getItem(crtLastTreePreferenceKey({ ownerId: "owner-a", origin: scope.origin }))).toBeNull();
    useAuthStore.setState({ user: { id: "owner-b", email: "b@example.test" }, status: "authed" });
    useAuthStore.setState({ user: { id: "owner-c", email: "c@example.test" }, status: "authed" });
    expect(window.localStorage.getItem(crtLastTreePreferenceKey({ ownerId: "owner-b", origin: scope.origin }))).toBeNull();
    unbind();
  });

  it("normalizes non-http origins and accepts string timestamps without persisting invalid scopes", () => {
    const ftpScope = { ownerId: "owner-a", origin: "ftp://app.example.test/path" };
    expect(crtLastTreePreferenceKey(ftpScope)).toContain(encodeURIComponent(""));
    rememberCrtLastTreePreference(ftpScope, "tree", "2026-09-20T10:00:00Z");
    expect(window.localStorage.length).toBe(0);
    rememberCrtLastTreePreference(scope, "tree", "2026-09-20T10:00:00Z");
    expect(readCrtLastTreePreference(scope, [tree("tree", "2026-09-20T10:00:00Z")])?.id).toBe("tree");
  });

  it("uses the deterministic id tie-breaker when newer timestamps are equal", () => {
    const tied = [tree("z-tree", "2026-09-20T10:00:00Z"), tree("a-tree", "2026-09-20T10:00:00Z")];
    expect(readCrtLastTreePreference({ ...scope, ownerId: "owner-a" }, tied)?.id).toBe("a-tree");
  });

  it("uses a blank default origin when the global location is absent", () => {
    const previousLocation = globalThis.location;
    vi.stubGlobal("location", undefined);
    try {
      const unbind = bindCrtLastTreePreferenceSession();
      unbind();
    } finally {
      vi.stubGlobal("location", previousLocation);
    }
  });

  it("falls back to owner filtering when browser storage is unavailable", () => {
    const browserWindow = globalThis.window;
    vi.stubGlobal("window", undefined);
    try {
      const trees = [tree("ssr-tree", "2026-09-20T10:00:00Z")];
      expect(readCrtLastTreePreference(scope, trees)?.id).toBe("ssr-tree");
      expect(() => rememberCrtLastTreePreference(scope, "ssr-tree")).not.toThrow();
      expect(() => clearCrtLastTreePreference(scope)).not.toThrow();
      expect(() => sweepCrtLastTreePreferences()).not.toThrow();
      expect(() => bindCrtLastTreePreferenceSession(scope.origin)).not.toThrow();
    } finally {
      vi.stubGlobal("window", browserWindow);
    }
  });
});
