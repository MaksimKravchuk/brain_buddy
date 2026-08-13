import { QueryClient } from "@tanstack/react-query";

import { PRIVATE_AGENT_ROOT, resetPrivateAgentState } from "@/api/privateAgentCache";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe("resetPrivateAgentState", () => {
  it("cancels and removes private agent state without clearing unrelated public caches", async () => {
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false, gcTime: 0 },
        mutations: { retry: false, gcTime: 0 },
      },
    });
    const owner = "https://brain-a.example.test/api|user-a";
    const pending = deferred<string[]>();
    const request = client.fetchQuery({
      queryKey: [...PRIVATE_AGENT_ROOT, owner, "connections"],
      queryFn: () => pending.promise,
    });
    const requestOutcome = request.then(
      () => "resolved",
      () => "cancelled",
    );
    client.setQueryData(["public", "release-notes"], ["keep me"]);
    client.getMutationCache().build(client, {
      mutationKey: [...PRIVATE_AGENT_ROOT, owner, "mutation", "reply-run"],
      mutationFn: async () => undefined,
    });

    await resetPrivateAgentState(client, () => true);
    pending.resolve(["Account A endpoint"]);
    await expect(requestOutcome).resolves.toBe("cancelled");
    await Promise.resolve();

    expect(client.getQueriesData({ queryKey: PRIVATE_AGENT_ROOT })).toEqual([]);
    expect(
      client.getMutationCache().findAll({ mutationKey: PRIVATE_AGENT_ROOT }),
    ).toEqual([]);
    expect(client.getQueryData(["public", "release-notes"])).toEqual(["keep me"]);

    client.clear();
  });

  it("removes nothing once the scope that asked for the cleanup has been replaced", async () => {
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false, gcTime: 0 },
        mutations: { retry: false, gcTime: 0 },
      },
    });
    // Ownership is lost exactly once, at the moment the cleanup asks again
    // after cancelling — the window a pre-flight check alone cannot cover.
    let owned = true;
    const successor = "https://brain-a.example.test/api|user-b";
    client.setQueryData([...PRIVATE_AGENT_ROOT, successor, "connections"], ["successor state"]);

    await resetPrivateAgentState(client, () => {
      const answer = owned;
      owned = false;
      return answer;
    });

    expect(client.getQueryData([...PRIVATE_AGENT_ROOT, successor, "connections"])).toEqual([
      "successor state",
    ]);

    client.clear();
  });
});
