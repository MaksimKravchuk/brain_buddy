import { afterEach, describe, expect, it, vi } from "vitest";

import { applyBrand, BRAND_STORAGE_KEY, initBrand, resolveBrand } from "../brand";

function memoryStorage(initial: Record<string, string> = {}): Storage {
  const values = new Map(Object.entries(initial));
  return {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => Array.from(values.keys())[index] ?? null,
    removeItem: (key) => {
      values.delete(key);
    },
    setItem: (key, value) => {
      values.set(key, value);
    }
  };
}

function blockedStorage(): Storage {
  const fail = (): never => {
    throw new DOMException("blocked", "SecurityError");
  };
  return {
    length: 0,
    clear: fail,
    getItem: fail,
    key: fail,
    removeItem: fail,
    setItem: fail
  };
}

describe("Carry On brand switch", () => {
  it("keeps today's look when nothing asks for Carry On", () => {
    expect(resolveBrand({ buildDefault: undefined, search: "", storage: memoryStorage() })).toBe(
      "legacy"
    );
  });

  it("uses the build default", () => {
    expect(
      resolveBrand({ buildDefault: "carry-on", search: "", storage: memoryStorage() })
    ).toBe("carry-on");
  });

  it("ignores an unknown build default", () => {
    expect(resolveBrand({ buildDefault: "sky", search: "", storage: memoryStorage() })).toBe(
      "legacy"
    );
  });

  it("lets the URL preview Carry On and remembers it for this browser", () => {
    const storage = memoryStorage();

    expect(resolveBrand({ buildDefault: "legacy", search: "?brand=carry-on", storage })).toBe(
      "carry-on"
    );
    expect(storage.getItem(BRAND_STORAGE_KEY)).toBe("carry-on");
    expect(resolveBrand({ buildDefault: "legacy", search: "", storage })).toBe("carry-on");
  });

  it("lets the URL return to today's look over a carry-on build", () => {
    const storage = memoryStorage({ [BRAND_STORAGE_KEY]: "carry-on" });

    expect(resolveBrand({ buildDefault: "carry-on", search: "?brand=legacy", storage })).toBe(
      "legacy"
    );
    expect(resolveBrand({ buildDefault: "carry-on", search: "", storage })).toBe("legacy");
  });

  it("ignores an unknown URL or stored value", () => {
    const storage = memoryStorage({ [BRAND_STORAGE_KEY]: "neon" });

    expect(resolveBrand({ buildDefault: "carry-on", search: "?brand=neon", storage })).toBe(
      "carry-on"
    );
  });

  it("still honours the URL when storage is blocked", () => {
    expect(
      resolveBrand({ buildDefault: undefined, search: "?brand=carry-on", storage: blockedStorage() })
    ).toBe("carry-on");
    expect(
      resolveBrand({ buildDefault: undefined, search: "", storage: blockedStorage() })
    ).toBe("legacy");
  });

  it("works without any storage", () => {
    expect(resolveBrand({ buildDefault: "carry-on", search: "", storage: undefined })).toBe(
      "carry-on"
    );
  });

  it("marks the root only for Carry On", () => {
    const root = document.createElement("html");

    applyBrand(root, "carry-on");
    expect(root.dataset.brand).toBe("carry-on");

    applyBrand(root, "legacy");
    expect(root.hasAttribute("data-brand")).toBe(false);
  });

  describe("on page load", () => {
    afterEach(() => {
      vi.restoreAllMocks();
      window.localStorage.removeItem(BRAND_STORAGE_KEY);
      window.history.replaceState(null, "", "/");
      delete document.documentElement.dataset.brand;
    });

    it("marks the page from the URL and remembers the choice", () => {
      window.history.replaceState(null, "", "/tasks/next?brand=carry-on");

      expect(initBrand()).toBe("carry-on");
      expect(document.documentElement.dataset.brand).toBe("carry-on");
      expect(window.localStorage.getItem(BRAND_STORAGE_KEY)).toBe("carry-on");
    });

    it("keeps today's look when the browser refuses storage", () => {
      vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
        throw new DOMException("blocked", "SecurityError");
      });

      expect(initBrand()).toBe("legacy");
      expect(document.documentElement.hasAttribute("data-brand")).toBe(false);
    });
  });
});
