import { afterEach, describe, expect, it, vi } from "vitest";

import * as clientModule from "../client";
import { useAuthStore } from "../../stores/authStore";
import { crtKeys, getCrtCacheScope } from "../crtHooks";

describe("CRT React Query keys", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    useAuthStore.setState({ user: null, status: "loading" });
  });

  it("captures the authenticated owner and API origin in the default scope", () => {
    vi.spyOn(clientModule, "getApiBaseUrl").mockReturnValue("https://first.example/api");
    useAuthStore.setState({ user: { id: "owner-a", email: "a@example.test" }, status: "authed" });

    expect(getCrtCacheScope()).toEqual({ ownerId: "owner-a", apiOrigin: "https://first.example/api" });
    expect(crtKeys.list()).toEqual([
      "crt",
      "trees",
      { ownerId: "owner-a", apiOrigin: "https://first.example/api" },
      "list"
    ]);
  });

  it("separates every tree cache family by owner and API origin", () => {
    const getOrigin = vi.spyOn(clientModule, "getApiBaseUrl").mockReturnValue("https://first.example/api");
    useAuthStore.setState({ user: { id: "owner-a", email: "a@example.test" }, status: "authed" });
    const ownerA = {
      list: crtKeys.list(),
      detail: crtKeys.detail("tree-1"),
      export: crtKeys.export("tree-1")
    };

    useAuthStore.setState({ user: { id: "owner-b", email: "b@example.test" }, status: "authed" });
    const ownerB = {
      list: crtKeys.list(),
      detail: crtKeys.detail("tree-1"),
      export: crtKeys.export("tree-1")
    };
    expect(ownerA.list).not.toEqual(ownerB.list);
    expect(ownerA.detail).not.toEqual(ownerB.detail);
    expect(ownerA.export).not.toEqual(ownerB.export);

    getOrigin.mockReturnValue("https://second.example/api");
    const otherOrigin = crtKeys.list();
    expect(otherOrigin).not.toEqual(ownerB.list);
  });

  it("keeps collection, detail, and export keys distinct under one scope", () => {
    const scope = { ownerId: "owner-a", apiOrigin: "https://first.example/api" } as const;

    expect(crtKeys.all).toEqual(["crt"]);
    expect(crtKeys.forScope(scope).all).toEqual(["crt", scope]);
    expect(crtKeys.exposure(scope)).toEqual(["crt", "exposure", scope]);
    expect(crtKeys.trees(scope)).toEqual(["crt", "trees", scope]);
    expect(crtKeys.list(scope)).toEqual(["crt", "trees", scope, "list"]);
    expect(crtKeys.detail("tree-1", scope)).toEqual(["crt", "trees", scope, "detail", "tree-1"]);
    expect(crtKeys.export("tree-1", scope)).toEqual(["crt", "trees", scope, "export", "tree-1"]);
    expect(crtKeys.detail("tree-1", scope)).not.toEqual(crtKeys.detail("tree-2", scope));
  });

  it("uses a null owner for missing auth and captures the normalized API origin in every default key", () => {
    vi.spyOn(clientModule, "getApiBaseUrl").mockReturnValue("https://second.example/api");
    useAuthStore.setState({ user: null, status: "anon" });

    const scope = getCrtCacheScope();
    expect(scope).toEqual({ ownerId: null, apiOrigin: "https://second.example/api" });
    expect(getCrtCacheScope("explicit-owner")).toEqual({
      ownerId: "explicit-owner",
      apiOrigin: "https://second.example/api"
    });
    expect(crtKeys.exposure()).toEqual(["crt", "exposure", scope]);
    expect(crtKeys.trees()).toEqual(["crt", "trees", scope]);
    expect(crtKeys.list()).toEqual(["crt", "trees", scope, "list"]);
    expect(crtKeys.detail("tree-1")).toEqual(["crt", "trees", scope, "detail", "tree-1"]);
    expect(crtKeys.export("tree-1")).toEqual(["crt", "trees", scope, "export", "tree-1"]);
  });
});
