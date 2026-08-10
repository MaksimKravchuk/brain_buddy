/**
 * Integration suite: runs the REAL mobile API client (src/api/client.ts)
 * against a locally booted backend, end to end:
 *
 *   auth (invite signup, cookie session, /me flags)
 *   task lifecycle (create/list/counts/patch/transitions/409)
 *   projects & tags (create, classify, filter)
 *   brain dump — full seal protocol with the test-env text fixture
 *   brain dump — multi-chunk binary WAV upload (prefix inspection + manifest)
 *
 * Run with: npm run integration   (boots its own uvicorn; ~1 min)
 */

import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";

import { ApiError, createApiClient } from "../src/api/client";
import type { BrainDumpOperationResponse } from "../src/api/types";
import {
  buildConsent,
  isPollable,
  nextPollDelay,
  visibleProposals,
} from "../src/braindump/machine";
import { chunkSha256Hex, manifestHash } from "../src/braindump/manifest";
import { uploadChunks } from "../src/braindump/uploader";
import { startBackend } from "./backend";
import { createCookieFetch } from "./cookieFetch";
import { makeWav } from "./wav";

const key = () => randomUUID();

let passed = 0;
function ok(label: string) {
  passed += 1;
  console.log(`  ✓ ${label}`);
}

async function pollUntilSettled(
  client: ReturnType<typeof createApiClient>,
  operationId: string,
  timeoutMs = 60_000,
): Promise<BrainDumpOperationResponse> {
  const deadline = Date.now() + timeoutMs;
  let delay: number | null = null;
  let operation = await client.getBrainDump(operationId);
  while (isPollable(operation.status) || operation.status === "recording") {
    if (Date.now() > deadline) {
      throw new Error(`Operation ${operationId} still ${operation.status} after ${timeoutMs}ms`);
    }
    delay = nextPollDelay(delay);
    const wait = Math.min(delay, 1000);
    await new Promise((resolve) => setTimeout(resolve, wait));
    operation = await client.getBrainDump(operationId);
  }
  return operation;
}

// A random port in a 200-wide window still collides when several agents run
// the integration suite at once, and a collision surfaces as an opaque backend
// boot failure. BRAIN_BUDDY_MOBILE_IT_PORT lets a caller pin a lane.
function resolvePort(): number {
  const override = process.env.BRAIN_BUDDY_MOBILE_IT_PORT;
  if (override === undefined || override === "") {
    return 8700 + Math.floor(Math.random() * 200);
  }
  const parsed = Number.parseInt(override, 10);
  if (!Number.isInteger(parsed) || parsed < 1024 || parsed > 65535) {
    throw new Error(
      `BRAIN_BUDDY_MOBILE_IT_PORT must be an integer in 1024..65535, got "${override}"`,
    );
  }
  return parsed;
}

async function main() {
  const port = resolvePort();
  console.log("Booting backend…");
  const backend = await startBackend(port);

  try {
    const client = createApiClient({
      getBaseUrl: () => `${backend.baseUrl}/api`,
      fetchImpl: createCookieFetch(),
    });

    // --- Auth ---
    console.log("auth");
    const email = `mobile-it-${Date.now()}@example.com`;
    const password = "correct-horse-battery-staple-1";
    const invite = backend.invite();
    const me = await client.signup({ email, password, invite_code: invite });
    assert.equal(me.email, email);
    ok("signup with invite sets the session cookie");

    const profile = await client.me();
    assert.equal(profile.id, me.id);
    assert.equal(profile.feature_flags.voice_brain_dump, true);
    ok("/me confirms the session and the voice flag");

    // --- Task lifecycle ---
    console.log("tasks");
    const created = await client.createTask({ title: "Call the notary", state: "inbox" }, key());
    assert.equal(created.state, "inbox");
    assert.equal(created.revision, 1);

    const inbox = await client.listTasks({ state: "inbox" });
    assert.ok(inbox.items.some((task) => task.id === created.id));
    assert.equal(inbox.counts_by_state.inbox, 1);
    ok("create + list + counts_by_state");

    const titled = await client.updateTask(
      created.id,
      { title: "Call the notary about the flat", expected_revision: created.revision },
      key(),
    );
    assert.equal(titled.title, "Call the notary about the flat");
    ok("PATCH title with expected_revision");

    await assert.rejects(
      client.updateTask(created.id, { title: "stale", expected_revision: 1 }, key()),
      (error: unknown) => error instanceof ApiError && error.status === 409,
    );
    ok("stale expected_revision → 409");

    const waiting = await client.transitionTask(
      created.id,
      {
        action: "move",
        to_state: "waiting",
        waiting_for: "Notary reply",
        expected_revision: titled.revision,
      },
      key(),
    );
    assert.equal(waiting.state, "waiting");
    assert.equal(waiting.waiting_for, "Notary reply");
    assert.ok(waiting.waiting_since);
    ok("move → waiting requires and stores waiting_for");

    await assert.rejects(
      client.transitionTask(
        created.id,
        { action: "move", to_state: "next", expected_revision: 999 },
        key(),
      ),
      (error: unknown) => error instanceof ApiError && error.status === 409,
    );

    const completed = await client.transitionTask(
      created.id,
      { action: "complete", expected_revision: waiting.revision },
      key(),
    );
    assert.equal(completed.state, "completed");
    assert.equal(completed.waiting_for, null);
    ok("complete clears waiting metadata");

    const reopened = await client.transitionTask(
      created.id,
      { action: "reopen", to_state: "next", expected_revision: completed.revision },
      key(),
    );
    assert.equal(reopened.state, "next");
    assert.equal(reopened.completed_at, null);
    ok("reopen to an explicit destination");

    // --- Projects & tags ---
    console.log("projects & tags");
    const project = await client.createProject({ name: "Personal admin", color: "#6366F1" }, key());
    const tag = await client.createTag({ name: "calls" }, key());
    const classified = await client.createTask(
      { title: "Email venue about offsite", state: "next", project_id: project.id, tag_ids: [tag.id] },
      key(),
    );
    const byProject = await client.listTasks({ projectId: project.id });
    assert.ok(byProject.items.some((task) => task.id === classified.id));
    const byTag = await client.listTasks({ tagId: tag.id });
    assert.ok(byTag.items.some((task) => task.id === classified.id));
    const projects = await client.listProjects();
    assert.equal(projects.find((p) => p.id === project.id)?.open_task_count, 1);
    ok("project/tag classification and filtered lists");

    // --- Brain dump: text-fixture end-to-end ---
    console.log("brain dump (text fixture)");
    const providers = await client.getBrainDumpProviders();
    assert.ok(providers.accurate_stt, "test env must configure an accurate STT provider");
    const consent = buildConsent(providers, ["ru", "en"]);
    assert.ok(consent, "consent must be buildable when providers exist");

    const operation = await client.startBrainDump(consent, key());
    assert.equal(operation.status, "recording");

    const fixture = new TextEncoder().encode(
      "Call the notary about the apartment. Email Anna about the lease agreement.",
    );
    const uploaded = await client.uploadBrainDumpAudio(
      operation.id,
      0,
      fixture,
      chunkSha256Hex(fixture),
      "audio/x-brain-buddy-test-text",
    );
    assert.equal(uploaded.audio_chunks?.length, 1);
    assert.equal(uploaded.audio_chunks?.[0].sha256, chunkSha256Hex(fixture));
    ok("chunk upload echoes chunk metadata");

    const sealed = await client.sealBrainDump(
      operation.id,
      {
        expected_revision: uploaded.revision,
        expected_chunks: 1,
        manifest_hash: manifestHash(uploaded.audio_chunks ?? [], 1),
      },
      key(),
    );
    assert.ok(isPollable(sealed.status) || sealed.status === "awaiting_confirmation");
    ok("seal accepts the client-computed manifest hash");

    const reviewReady = await pollUntilSettled(client, operation.id);
    assert.equal(reviewReady.status, "awaiting_confirmation");
    const proposals = visibleProposals(reviewReady);
    assert.ok(proposals.length >= 1, "expected at least one proposal");
    ok(`review reached with ${proposals.length} proposal(s)`);

    const edited = await client.updateBrainDumpProposal(
      operation.id,
      proposals[0].id,
      { title: "Edited on mobile: call the notary", expected_revision: reviewReady.revision },
      key(),
    );
    const editedProposal = visibleProposals(edited).find((p) => p.id === proposals[0].id);
    assert.equal(editedProposal?.title, "Edited on mobile: call the notary");
    assert.equal(editedProposal?.user_edited, true);
    ok("proposal title edit locks the user's wording");

    const committed = await client.commandBrainDump(operation.id, "commit", edited.revision, key());
    const settled =
      committed.status === "completed" ? committed : await pollUntilSettled(client, operation.id);
    assert.equal(settled.status, "completed");
    assert.equal(settled.committed_task_ids.length, visibleProposals(edited).length);
    ok(`commit created ${settled.committed_task_ids.length} inbox task(s), exactly once`);

    const inboxAfter = await client.listTasks({ state: "inbox" });
    assert.ok(
      inboxAfter.items.some((task) => task.title === "Edited on mobile: call the notary"),
      "committed task must appear in the inbox",
    );
    const committedTask = inboxAfter.items.find(
      (task) => task.title === "Edited on mobile: call the notary",
    );
    assert.equal(committedTask?.priority, "none");
    assert.equal(committedTask?.project_id, null);
    ok("committed tasks are title-only inbox tasks (no inferred metadata)");

    // --- Brain dump: multi-chunk binary WAV upload ---
    console.log("brain dump (multi-chunk WAV)");
    const wavOperation = await client.startBrainDump(consent, key());
    const wav = makeWav(1.5);
    const result = await uploadChunks({
      reader: {
        size: wav.byteLength,
        read: async (offset, length) => wav.slice(offset, offset + length),
      },
      mimeType: "audio/wav",
      chunkBytes: 16 * 1024,
      put: (chunkNumber, bytes, sha, mime) =>
        client.uploadBrainDumpAudio(wavOperation.id, chunkNumber, bytes, sha, mime),
    });
    assert.ok(result.expectedChunks >= 2, "the WAV must span multiple chunks");
    ok(`uploaded ${result.expectedChunks} WAV chunks past the cumulative-prefix inspection`);

    const wavSealed = await client.sealBrainDump(
      wavOperation.id,
      {
        expected_revision: result.lastOperation.revision,
        expected_chunks: result.expectedChunks,
        manifest_hash: manifestHash(result.lastOperation.audio_chunks ?? [], result.expectedChunks),
      },
      key(),
    );
    assert.notEqual(wavSealed.status, "recording");
    ok("binary WAV seal accepted (manifest verified server-side)");

    // What happens after seal (deterministic STT over a tone) is backend
    // provider behavior, not a client contract — just clean the operation up.
    // The background runner may bump the revision concurrently, so do what
    // the app does on 409: refetch and retry with the fresh revision.
    let wavFinal = wavSealed;
    for (let attempt = 0; attempt < 5; attempt += 1) {
      try {
        wavFinal = await client.commandBrainDump(
          wavOperation.id,
          "cancel",
          wavFinal.revision,
          key(),
        );
        break;
      } catch (error) {
        if (error instanceof ApiError && error.status === 409 && attempt < 4) {
          wavFinal = await client.getBrainDump(wavOperation.id);
          continue;
        }
        throw error;
      }
    }
    assert.ok(["cancelled", "cancelling"].includes(wavFinal.status));
    ok("WAV operation cancelled after seal (409 → refetch → retry)");

    // --- Logout closes the session ---
    await client.logout();
    await assert.rejects(
      client.me(),
      (error: unknown) => error instanceof ApiError && error.status === 401,
    );
    ok("logout invalidates the session cookie");

    console.log(`\nIntegration suite passed (${passed} checks).`);
  } finally {
    backend.stop();
  }
}

main().catch((error) => {
  console.error("\nIntegration suite FAILED:");
  console.error(error);
  process.exit(1);
});
