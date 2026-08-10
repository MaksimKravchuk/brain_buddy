/**
 * Coverage of the api client's request plumbing and the endpoints the unit
 * suite for `client.test.ts` does not already pin: classification CRUD, the
 * brain-dump surface, and the binary/no-content paths.
 */

import { createApiClient, toArrayBuffer } from "../client";

interface Recorded {
  url: string;
  init: RequestInit;
}

function makeClient(responder: (call: Recorded) => Response) {
  const calls: Recorded[] = [];
  const fetchImpl = (async (url: RequestInfo | URL, init?: RequestInit) => {
    const call = { url: String(url), init: init ?? {} };
    calls.push(call);
    return responder(call);
  }) as unknown as typeof fetch;
  const client = createApiClient({ getBaseUrl: () => "https://example.test/api", fetchImpl });
  return { client, calls };
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("toArrayBuffer", () => {
  it("hands back the whole buffer when the view spans it", () => {
    const bytes = Uint8Array.from([1, 2, 3]);
    expect(new Uint8Array(toArrayBuffer(bytes))).toEqual(bytes);
  });

  it("copies out just the view's window when it is a slice of a larger buffer", () => {
    const backing = Uint8Array.from([9, 9, 1, 2, 3, 9]);
    const view = backing.subarray(2, 5);

    const buffer = toArrayBuffer(view);

    expect(new Uint8Array(buffer)).toEqual(Uint8Array.from([1, 2, 3]));
    expect(buffer.byteLength).toBe(3);
  });
});

describe("request plumbing", () => {
  it("returns undefined for a 204 rather than trying to parse a body", async () => {
    const { client } = makeClient(() => new Response(null, { status: 204 }));

    await expect(client.logout()).resolves.toBeUndefined();
  });

  it("reads a non-JSON body as text and reports it on failure", async () => {
    const { client } = makeClient(
      () => new Response("upstream timeout", { status: 504, headers: { "Content-Type": "text/plain" } }),
    );

    await expect(client.me()).rejects.toMatchObject({ status: 504, payload: "upstream timeout" });
  });

  it("sends a raw ArrayBuffer body unchanged", async () => {
    const { client, calls } = makeClient(() => json({ id: "op" }));
    const buffer = Uint8Array.from([1, 2, 3]).buffer;

    await client.request("/raw", { method: "PUT", body: buffer });

    expect(calls[0].init.body).toBe(buffer);
    expect((calls[0].init.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
  });

  it("passes a caller's abort signal alongside the timeout", async () => {
    const { client, calls } = makeClient(() => json({ id: "u" }));
    const controller = new AbortController();

    await client.me(controller.signal);

    expect(calls[0].init.signal).toBeInstanceOf(AbortSignal);
  });
});

describe("task endpoints", () => {
  it("sends no query string when there are no filters", async () => {
    const { client, calls } = makeClient(() =>
      json({ items: [], next_cursor: null, has_more: false, counts_by_state: {} }),
    );

    await client.listTasks();

    expect(calls[0].url).toBe("https://example.test/api/tasks");
  });

  it("passes each due filter and the sort through, but never sort=manual", async () => {
    const { client, calls } = makeClient(() =>
      json({ items: [], next_cursor: null, has_more: false, counts_by_state: {} }),
    );

    await client.listTasks({
      dueBefore: "2030-01-01",
      dueOn: "2030-01-02",
      dueAfter: "2030-01-03",
      priority: ["high", "low"],
      sort: "due",
    });
    await client.listTasks({ sort: "manual" });

    expect(calls[0].url).toContain("due_before=2030-01-01");
    expect(calls[0].url).toContain("due_on=2030-01-02");
    expect(calls[0].url).toContain("due_after=2030-01-03");
    expect(calls[0].url).toContain("priority=high&priority=low");
    expect(calls[0].url).toContain("sort=due");
    expect(calls[1].url).toBe("https://example.test/api/tasks");
  });

  it("routes smart add, subtask and comment writes to their own paths", async () => {
    const { client, calls } = makeClient(() => json({ id: "x" }));

    await client.smartAddTask({ title: "Call the notary" }, "k1");
    await client.updateSubtask("t1", "s1", { title: "Ring", expected_revision: 2 }, "k2");
    await client.updateComment("t1", "c1", { body: "note", expected_revision: 1 }, "k3");

    expect(calls.map((call) => `${call.init.method} ${new URL(call.url).pathname}`)).toEqual([
      "POST /api/tasks/smart-add",
      "PATCH /api/tasks/t1/subtasks/s1",
      "PATCH /api/tasks/t1/comments/c1",
    ]);
    expect((calls[0].init.headers as Record<string, string>)["Idempotency-Key"]).toBe("k1");
  });
});

describe("project and tag endpoints", () => {
  it("creates, updates and archives a project", async () => {
    const { client, calls } = makeClient(() => json({ id: "p1" }));

    await client.listProjects();
    await client.createProject({ name: "Wedding" }, "k1");
    await client.updateProject("p1", { name: "Wedding 2", expected_revision: 2 }, "k2");
    await client.archiveProject("p1", 3, "k3");

    expect(calls.map((call) => `${call.init.method} ${new URL(call.url).pathname}`)).toEqual([
      "GET /api/projects",
      "POST /api/projects",
      "PATCH /api/projects/p1",
      "POST /api/projects/p1/archive",
    ]);
    expect(JSON.parse(String(calls[3].init.body))).toEqual({ expected_revision: 3 });
  });

  it("creates, updates and deletes a tag, carrying the revision on delete", async () => {
    const { client, calls } = makeClient(() => json({ id: "g1" }));

    await client.listTags();
    await client.createTag({ name: "errand" }, "k1");
    await client.updateTag("g1", { name: "errands", expected_revision: 4 }, "k2");
    await client.deleteTag("g1", 5, "k3");

    expect(calls[3].init.method).toBe("DELETE");
    expect(calls[3].url).toBe("https://example.test/api/tags/g1?expected_revision=5");
  });
});

describe("brain-dump endpoints", () => {
  it("appends a transcript and updates a proposal", async () => {
    const { client, calls } = makeClient(() => json({ id: "op-1" }));

    await client.appendBrainDumpTranscript(
      "op-1",
      { segments: [{ sequence: 1, text: "hello", stability: "stable" }] },
      "k1",
    );
    await client.updateBrainDumpProposal(
      "op-1",
      "prop-1",
      { title: "Call the notary", expected_revision: 2 },
      "k2",
    );

    expect(calls.map((call) => `${call.init.method} ${new URL(call.url).pathname}`)).toEqual([
      "POST /api/brain-dump-operations/op-1/transcript",
      "PATCH /api/brain-dump-operations/op-1/proposals/prop-1",
    ]);
  });

  it("sends an audio chunk as bytes with its digest and mime type", async () => {
    const { client, calls } = makeClient(() => json({ id: "op-1" }));

    await client.uploadBrainDumpAudio("op-1", 2, Uint8Array.from([1, 2, 3]), "abc123", "audio/wav");

    const headers = calls[0].init.headers as Record<string, string>;
    expect(calls[0].url).toBe("https://example.test/api/brain-dump-operations/op-1/audio/2");
    expect(headers["X-Content-SHA256"]).toBe("abc123");
    expect(headers["Content-Type"]).toBe("audio/wav");
    expect(calls[0].init.body).toBeInstanceOf(ArrayBuffer);
  });

  it("reads the configured providers", async () => {
    const { client, calls } = makeClient(() => json({ accurate_stt: "whisper", reconciler: null }));

    await expect(client.getBrainDumpProviders()).resolves.toEqual({
      accurate_stt: "whisper",
      reconciler: null,
    });
    expect(new URL(calls[0].url).pathname).toBe("/api/brain-dump-providers");
  });
});
