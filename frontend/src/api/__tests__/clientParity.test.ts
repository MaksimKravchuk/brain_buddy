import { describe, expect, it, vi } from "vitest";
import { apiClient } from "../client";

interface RuntimeFileSystem {
  readFileSync(path: string, encoding: "utf8"): string;
}

interface RuntimeProcess {
  cwd(): string;
  getBuiltinModule(name: "fs"): RuntimeFileSystem;
}

interface RuntimeGlobals {
  process: RuntimeProcess;
}

function loadParityManifest(): string {
  const runtime = globalThis as typeof globalThis & RuntimeGlobals;
  const path = `${runtime.process.cwd()}/../contracts/api-client-parity.json`;
  return runtime.process.getBuiltinModule("fs").readFileSync(path, "utf8");
}

type Client = typeof apiClient;
type OperationName =
  | "listTasks" | "createTask" | "smartAddTask" | "getTask" | "updateTask"
  | "transitionTask" | "createSubtask" | "updateSubtask" | "transitionSubtask"
  | "createComment" | "updateComment" | "listProjects" | "createProject"
  | "updateProject" | "archiveProject" | "listTags" | "createTag" | "updateTag"
  | "deleteTag" | "getBrainDumpProviders" | "startBrainDump" | "getBrainDump"
  | "appendBrainDumpTranscript" | "uploadBrainDumpAudio" | "sealBrainDump"
  | "updateBrainDumpProposal" | "commandBrainDump" | "listAgentConnections"
  | "createAgentConnection" | "getAgentConnection" | "updateAgentConnection"
  | "testAgentConnection" | "rotateAgentCredential"
  | "disconnectAgentConnection" | "previewAgentHandoff" | "confirmAgentHandoff"
  | "listAgentRuns" | "getAgentRun" | "listAgentRunSummaries" | "replyToAgentRun"
  | "cancelAgentRun";
type Manifest = { operations: Record<OperationName, { path: string; method: string; body: "none" | "json" | "binary"; idempotency: boolean; headers: string[] }> };
function isManifest(value: unknown): value is Manifest {
  return typeof value === "object" && value !== null && "operations" in value && typeof value.operations === "object" && value.operations !== null;
}
const manifestValue: unknown = JSON.parse(loadParityManifest());
if (!isManifest(manifestValue)) throw new Error("Invalid API client parity manifest");
const manifest = manifestValue;
type Adapter = (client: Client) => Promise<unknown>;

const adapters = {
  listTasks: (c) => c.listTasks({ state: "inbox", projectId: "project-1", tagId: "tag-1", cursor: "page-2", limit: 25, includeCompleted: true, includeCancelled: true, q: " shared ", unassignedProject: true, priority: ["high", "medium"], dueBefore: "2026-08-01", dueOn: "2026-08-02", dueAfter: "2026-08-03", sort: "due" }),
  createTask: (c) => c.createTask({ title: "fixture" }, "key-create"),
  smartAddTask: (c) => c.smartAddTask({ title: "fixture" }, "key-smart"),
  getTask: (c) => c.getTask("task-1"),
  updateTask: (c) => c.updateTask("task-1", { expected_revision: 1 }, "key-update"),
  transitionTask: (c) => c.transitionTask("task-1", { action: "complete", expected_revision: 1 }, "key-transition"),
  createSubtask: (c) => c.createSubtask("task-1", { title: "subtask" }, "key-subtask"),
  updateSubtask: (c) => c.updateSubtask("task-1", "subtask-1", { expected_revision: 1 }, "key-subtask-update"),
  transitionSubtask: (c) => c.transitionSubtask("task-1", "subtask-1", { action: "complete", expected_revision: 1 }, "key-subtask-transition"),
  createComment: (c) => c.createComment("task-1", { body: "comment" }, "key-comment"),
  updateComment: (c) => c.updateComment("task-1", "comment-1", { body: "edited", expected_revision: 1 }, "key-comment-update"),
  listProjects: (c) => c.listProjects(),
  createProject: (c) => c.createProject({ name: "project" }, "key-project"),
  updateProject: (c) => c.updateProject("project-1", { expected_revision: 1 }, "key-project-update"),
  archiveProject: (c) => c.archiveProject("project-1", 1, "key-project-archive"),
  listTags: (c) => c.listTags(),
  createTag: (c) => c.createTag({ name: "tag" }, "key-tag"),
  updateTag: (c) => c.updateTag("tag-1", { expected_revision: 1 }, "key-tag-update"),
  deleteTag: (c) => c.deleteTag("tag-1", 4, "key-tag-delete"),
  getBrainDumpProviders: (c) => c.getBrainDumpProviders(),
  startBrainDump: (c) => c.startBrainDump({ consent: { microphone: true, external_processing_allowed: false, language_hints: [], vocabulary: [] } }, "key-dump-start"),
  getBrainDump: (c) => c.getBrainDump("op-1"),
  appendBrainDumpTranscript: (c) => c.appendBrainDumpTranscript("op-1", { segments: [{ sequence: 0, text: "hello", stability: "stable" }] }, "key-dump-transcript"),
  uploadBrainDumpAudio: (c) => c.uploadBrainDumpAudio("op-1", 0, new ArrayBuffer(0), "sha", "audio/wav"),
  sealBrainDump: (c) => c.sealBrainDump("op-1", { expected_revision: 1, expected_chunks: 1, manifest_hash: "hash" }, "key-dump-seal"),
  updateBrainDumpProposal: (c) => c.updateBrainDumpProposal("op-1", "proposal-1", { expected_revision: 1 }, "key-dump-proposal"),
  commandBrainDump: (c) => c.commandBrainDump("op-1", "finish", 1, "key-dump-command"),
  listAgentConnections: (c) => c.listAgentConnections(),
  createAgentConnection: (c) => c.createAgentConnection({ name: "agent", agent_address: "https://agent.test", credential: "credential", current_password: "password" }, "key-agent-create"),
  getAgentConnection: (c) => c.getAgentConnection("connection-1"),
  updateAgentConnection: (c) => c.updateAgentConnection("connection-1", { expected_revision: 1 }, "key-agent-update"),
  testAgentConnection: (c) => c.testAgentConnection("connection-1"),
  rotateAgentCredential: (c) => c.rotateAgentCredential("connection-1", { credential: "credential", current_password: "password", expected_revision: 1 }, "key-agent-credential"),
  disconnectAgentConnection: (c) => c.disconnectAgentConnection("connection-1", { current_password: "password", expected_revision: 1 }, "key-agent-disconnect"),
  previewAgentHandoff: (c) => c.previewAgentHandoff("task-1", { connection_id: "connection-1" }),
  confirmAgentHandoff: (c) => c.confirmAgentHandoff("task-1", { connection_id: "connection-1", manifest_token: "token" }, "key-agent-confirm"),
  listAgentRuns: (c) => c.listAgentRuns("task-1"),
  getAgentRun: (c) => c.getAgentRun("run-1"),
  listAgentRunSummaries: (c) => c.listAgentRunSummaries(["task-1", "task-2"]),
  replyToAgentRun: (c) => c.replyToAgentRun("run-1", { message: "reply", expected_revision: 1 }, "key-agent-reply"),
  cancelAgentRun: (c) => c.cancelAgentRun("run-1", "key-agent-cancel"),
} satisfies Record<OperationName, Adapter>;

function jsonResponse(): Response {
  return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
}

describe("common client wire parity inventory", () => {
  it("covers exactly 41 common operations with typed adapters", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockImplementation(async () => jsonResponse());
    vi.stubGlobal("fetch", fetchMock);
    const names = Object.keys(manifest.operations) as OperationName[];
    expect(names).toHaveLength(41);
    expect(Object.keys(adapters).sort()).toEqual(names.sort());
    for (const name of names) await adapters[name](apiClient);
    expect(fetchMock).toHaveBeenCalledTimes(41);
    fetchMock.mock.calls.forEach(([url, init], index) => {
      const operation = manifest.operations[names[index]];
      expect(String(url)).toBe(`/api${operation.path}`);
      expect(init?.credentials).toBe("include");
      expect(init?.method ?? "GET").toBe(operation.method);
      const headers = new Headers(init?.headers);
      expect(Boolean(headers.get("Idempotency-Key"))).toBe(operation.idempotency);
      if (operation.body === "json") {
        expect(headers.get("Content-Type")).toContain("application/json");
        const body = init?.body;
        expect(typeof body).toBe("string");
        if (typeof body !== "string") throw new Error("JSON operation body is missing");
        expect(() => JSON.parse(body)).not.toThrow();
      }
      if (operation.body === "none") expect(init?.body).toBeUndefined();
      if (operation.body === "binary") expect(init?.body).toBeInstanceOf(ArrayBuffer);
      for (const header of operation.headers) expect(headers.has(header)).toBe(true);
    });
    vi.unstubAllGlobals();
  });
});
