import { makeQueryClient } from "@/test/harness";
import { disposeQueryClient } from "@/test/queryClient";
import { testQueryClient } from "@/test/render";

describe("mobile render harness query clients", () => {
  it("keeps production-like default mutation retention", () => {
    expect(makeQueryClient().getDefaultOptions().mutations).toEqual({ retry: false });
    expect(testQueryClient().getDefaultOptions().mutations).toEqual({ retry: false });
  });

  it("destroys retained mutation timers when an owned client is disposed", () => {
    jest.useFakeTimers();
    try {
      const client = makeQueryClient();
      client.getMutationCache().build(client, { mutationFn: async () => undefined });
      expect(jest.getTimerCount()).toBeGreaterThan(0);

      disposeQueryClient(client);

      expect(jest.getTimerCount()).toBe(0);
    } finally {
      jest.useRealTimers();
    }
  });
});
