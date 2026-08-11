import AsyncStorage from "@react-native-async-storage/async-storage";

import {
  currentServerUrl,
  DEFAULT_SERVER_URL,
  loadServerUrl,
  normalizeServerUrl,
  saveServerUrl,
} from "../serverUrl";

const STORAGE_KEY = "bb.serverUrl";

beforeEach(async () => {
  await AsyncStorage.clear();
  await loadServerUrl();
});

describe("normalizeServerUrl", () => {
  it("strips surrounding whitespace and trailing slashes", () => {
    expect(normalizeServerUrl("  http://10.0.0.5:8000/api/  ")).toBe("http://10.0.0.5:8000/api");
    expect(normalizeServerUrl("http://10.0.0.5:8000/api///")).toBe("http://10.0.0.5:8000/api");
  });

  it("falls back to the default for an empty or blank value", () => {
    expect(normalizeServerUrl("")).toBe(DEFAULT_SERVER_URL);
    expect(normalizeServerUrl("   ")).toBe(DEFAULT_SERVER_URL);
    expect(normalizeServerUrl("///")).toBe(DEFAULT_SERVER_URL);
  });

  it("leaves an already-normal URL untouched", () => {
    expect(normalizeServerUrl("https://host/api")).toBe("https://host/api");
  });
});

describe("loadServerUrl", () => {
  it("returns the default when nothing is stored", async () => {
    await expect(loadServerUrl()).resolves.toBe(DEFAULT_SERVER_URL);
    expect(currentServerUrl()).toBe(DEFAULT_SERVER_URL);
  });

  it("normalizes what it read, so a stray slash cannot double up in a path", async () => {
    await AsyncStorage.setItem(STORAGE_KEY, "  http://10.0.0.5:8000/api/  ");

    await expect(loadServerUrl()).resolves.toBe("http://10.0.0.5:8000/api");
    expect(currentServerUrl()).toBe("http://10.0.0.5:8000/api");
  });

  it("falls back to the default when the store cannot be read", async () => {
    // Swapped by assignment: the store is itself a jest mock, and spying on a
    // mock leaves it implementation-less once restored.
    const original = AsyncStorage.getItem;
    AsyncStorage.getItem = (async () => {
      throw new Error("store unavailable");
    }) as typeof AsyncStorage.getItem;

    try {
      await expect(loadServerUrl()).resolves.toBe(DEFAULT_SERVER_URL);
    } finally {
      AsyncStorage.getItem = original;
    }
  });
});

describe("saveServerUrl", () => {
  it("persists a custom URL and makes it current", async () => {
    await expect(saveServerUrl("http://10.0.0.5:8000/api/")).resolves.toBe(
      "http://10.0.0.5:8000/api",
    );

    expect(currentServerUrl()).toBe("http://10.0.0.5:8000/api");
    await expect(AsyncStorage.getItem(STORAGE_KEY)).resolves.toBe("http://10.0.0.5:8000/api");
  });

  it("removes the entry when the URL is the default, so upgrades can move the host", async () => {
    await saveServerUrl("http://10.0.0.5:8000/api");

    await expect(saveServerUrl(DEFAULT_SERVER_URL)).resolves.toBe(DEFAULT_SERVER_URL);

    expect(currentServerUrl()).toBe(DEFAULT_SERVER_URL);
    await expect(AsyncStorage.getItem(STORAGE_KEY)).resolves.toBeNull();
  });

  it("treats a blank URL as a reset to the default", async () => {
    await saveServerUrl("http://10.0.0.5:8000/api");

    await expect(saveServerUrl("   ")).resolves.toBe(DEFAULT_SERVER_URL);

    expect(currentServerUrl()).toBe(DEFAULT_SERVER_URL);
    await expect(AsyncStorage.getItem(STORAGE_KEY)).resolves.toBeNull();
  });
});
