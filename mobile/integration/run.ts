/**
 * Integration suite: runs the REAL mobile API client (src/api/client.ts)
 * against a locally booted backend, end to end:
 *
 *   auth (invite signup, cookie session, /me flags)
 *   task lifecycle (create/list/counts/patch/transitions/409)
 *   projects & tags (create, classify, filter)
 *   brain dump — full seal protocol with the test-env text fixture
 *   brain dump — multi-chunk binary WAV upload (prefix inspection + manifest)
 *   external agent relay — connection discovery and the authenticated probe
 *     against a real loopback A2A agent (014-FR-002, 014-SC-009)
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
import { startFakeAgent } from "./fakeAgent";
import { verifyNodeSafeClientImport } from "./clientNodeImport";
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
  verifyNodeSafeClientImport();
  ok("API client imports in Node and preserves relay intent snapshots");
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

    // --- Classification from the mobile task screen (spec 006) ---
    //
    // Everything below runs the real client against a real backend because the
    // failures worth catching here are all wire-level: whether an explicit
    // `null` survives serialization as a deliberate clear rather than being
    // dropped as "no opinion"; whether a Tag set is applied whole; what the
    // server does with a key it has already seen; and which `detail.resource`
    // separates the two different 409s the client has to tell apart. A mocked
    // backend would prove only that the mock was written.
    console.log("classification (006)");
    const launch = await client.createProject({ name: "Q3 launch" }, key());
    const onboarding = await client.createProject({ name: "Onboarding drop-off" }, key());
    const homeTag = await client.createTag({ name: "home" }, key());
    const deepTag = await client.createTag({ name: "deep work" }, key());

    const triaged = await client.createTask(
      { title: "Book the rehearsal room", state: "inbox" },
      key(),
    );
    assert.equal(triaged.project_id, null);
    assert.deepEqual(triaged.tag_ids, []);

    // 006-FR-001 — set a project from the task detail screen, and read it back.
    const withProject = await client.updateTask(
      triaged.id,
      { project_id: launch.id, expected_revision: triaged.revision },
      key(),
    );
    const afterProject = await client.getTask(triaged.id);
    assert.equal(
      afterProject.project_id,
      launch.id,
      "006-FR-001: the server must hold the project the phone set",
    );
    assert.equal(afterProject.revision, withProject.revision);
    ok("006-FR-001 a project set on the phone survives a re-read");

    // 006-FR-002 — attach two Tags, then detach one. `tag_ids` is the whole
    // intended set, so the assertion that matters is that the *other* Tag, and
    // the project, are untouched by a Tag change.
    const withTags = await client.updateTask(
      triaged.id,
      { tag_ids: [homeTag.id, deepTag.id], expected_revision: afterProject.revision },
      key(),
    );
    assert.deepEqual(
      [...withTags.tag_ids].sort(),
      [homeTag.id, deepTag.id].sort(),
      "006-FR-002: both Tags must attach, and the order they were added in must not matter",
    );
    const detached = await client.updateTask(
      triaged.id,
      { tag_ids: [homeTag.id], expected_revision: withTags.revision },
      key(),
    );
    assert.deepEqual(
      detached.tag_ids,
      [homeTag.id],
      "006-FR-002: detaching one Tag must leave the other attached",
    );
    assert.equal(
      detached.project_id,
      launch.id,
      "006-FR-002: a Tag change must not disturb the project",
    );
    ok("006-FR-002 two Tags attach, one detaches, the other and the project untouched");

    // 006-SC-002 — what the phone sent is what the server holds, read back
    // independently of the response the mutation returned. This is the
    // automated half of "visible in the web client on the next refresh"; the
    // other half is a person looking, and quickstart.md says so.
    const asStored = await client.getTask(triaged.id);
    assert.equal(
      asStored.project_id,
      launch.id,
      "006-SC-002: the server must hold the project the phone sent, not a merge of it",
    );
    assert.deepEqual(
      [...asStored.tag_ids].sort(),
      [homeTag.id],
      "006-SC-002: the server must hold exactly the Tag set the phone sent",
    );
    assert.equal(asStored.revision, detached.revision);

    // A task carries at most one project: picking a second replaces the first
    // rather than adding to it.
    const reProjected = await client.updateTask(
      triaged.id,
      { project_id: onboarding.id, expected_revision: asStored.revision },
      key(),
    );
    assert.equal(
      (await client.getTask(triaged.id)).project_id,
      onboarding.id,
      "006-SC-002: a second project replaces the first — a task holds at most one",
    );
    ok("006-SC-002 the server holds exactly what the phone sent");

    // 006-FR-003 — clearing is a supported outcome, not the absence of one, so
    // it goes as an explicit `null`. `undefined` would mean "untouched" and the
    // project would survive.
    const clearedProject = await client.updateTask(
      triaged.id,
      { project_id: null, expected_revision: reProjected.revision },
      key(),
    );
    assert.equal(
      clearedProject.project_id,
      null,
      "006-FR-003: an explicit null must clear the project",
    );
    assert.deepEqual(
      clearedProject.tag_ids,
      [homeTag.id],
      "006-FR-003: clearing the project must not touch the Tags",
    );
    assert.equal(
      (await client.getTask(triaged.id)).project_id,
      null,
      "006-FR-003: the clear must survive a re-read, not just the response",
    );
    ok("006-FR-003 an explicit null clears the project and leaves the Tags alone");

    // 006-FR-017 — a queued change reaches the server at most once. A request
    // that timed out may already have been applied, so the retry carries the
    // SAME key; the server must replay its stored result rather than apply the
    // change a second time. This runs well inside the server's 24-hour replay
    // window, which is the only reason the key can carry the guarantee at all
    // (data-model invariant 10) — it proves at-most-once *inside* the window
    // and nothing about outside it.
    const beforeReplay = await client.getTask(triaged.id);
    const replayKey = key();
    const replayBody = {
      project_id: launch.id,
      expected_revision: beforeReplay.revision,
    };
    const firstSend = await client.updateTask(triaged.id, { ...replayBody }, replayKey);
    const replaySend = await client.updateTask(triaged.id, { ...replayBody }, replayKey);
    assert.equal(
      firstSend.revision,
      beforeReplay.revision + 1,
      "006-FR-017: the first send must advance the revision by one",
    );
    assert.equal(
      replaySend.revision,
      firstSend.revision,
      "006-FR-017: replaying one key must return the stored result, not apply the change twice",
    );
    const afterReplay = await client.getTask(triaged.id);
    assert.equal(
      afterReplay.revision,
      beforeReplay.revision + 1,
      "006-FR-017: after two PATCHes with the same key the revision advanced exactly once",
    );
    assert.equal(
      afterReplay.project_id,
      launch.id,
      "006-FR-017: and project_id is the intended value",
    );
    ok("006-FR-017 two PATCHes with one key advance the revision exactly once");

    // 006-FR-017 — the other 409. The client re-mints a key whenever the
    // payload changes, because a stored key arriving with a different request
    // hash is refused forever. `detail.resource` is the only thing separating
    // this from a stale revision, and the drain branches on exactly that
    // string — so it is asserted against the real server rather than assumed.
    let reuseError: unknown;
    try {
      await client.updateTask(
        triaged.id,
        { project_id: onboarding.id, expected_revision: afterReplay.revision },
        replayKey,
      );
    } catch (error) {
      reuseError = error;
    }
    assert.ok(
      reuseError instanceof ApiError && reuseError.status === 409,
      "006-FR-017: a spent key carrying a changed payload must be refused",
    );
    assert.equal(
      ((reuseError as ApiError).payload as { detail?: { resource?: string } }).detail?.resource,
      "Idempotency-Key",
      "006-FR-017: the refusal must name Idempotency-Key, which is what tells the client to re-mint",
    );
    ok("006-FR-017 a spent key with a changed payload → 409 naming Idempotency-Key");

    // 006-FR-008 — a queued change necessarily carries the revision the person
    // was looking at when they made it, so a rejection is an ordinary outcome
    // of normal use rather than a rare race. This is the 409 the conflict sheet
    // exists for, and the one the person answers.
    let staleError: unknown;
    try {
      await client.updateTask(
        triaged.id,
        { project_id: onboarding.id, expected_revision: beforeReplay.revision },
        key(),
      );
    } catch (error) {
      staleError = error;
    }
    assert.ok(
      staleError instanceof ApiError && staleError.status === 409,
      "006-FR-008: a stale expected_revision on a classification change must be refused, not merged",
    );
    assert.equal(
      ((staleError as ApiError).payload as { detail?: { resource?: string } }).detail?.resource,
      "Task",
      "006-FR-008: the refusal must name Task — the client opens the conflict sheet on this and nothing else",
    );
    assert.equal(
      (await client.getTask(triaged.id)).project_id,
      launch.id,
      "006-FR-008: nothing of the rejected change may have been applied",
    );
    ok("006-FR-008 a stale expected_revision on a classification change → 409, nothing applied");

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

    // --- External agent relay: discovery and the authenticated probe ---
    //
    // Every assertion below goes through the shipped client against the real
    // backend and a real agent socket. The categories are the ones a user acts
    // on differently, so proving the *client* surfaces each distinctly is what
    // makes the connection screen trustworthy (014-FR-002).
    await runAgentConnectionChecks(client, password);

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

/**
 * Drive the four connection-test outcomes a user can act on, end to end.
 *
 * `ready`, `a2a_credentials_rejected`, `a2a_unreachable` and `a2a_not_an_agent`
 * are four different next steps for the owner, and the client has to be able to
 * tell them apart from the real server's answer rather than from a fixture.
 */
async function runAgentConnectionChecks(
  client: ReturnType<typeof createApiClient>,
  password: string,
): Promise<void> {
  const agent = await startFakeAgent({ bearerToken: "integration-agent-token" });
  const noCard = await startFakeAgent({ servesCard: false });
  try {
    const connect = async (name: string, address: string, credential: string) => {
      const created = await client.createAgentConnection(
        {
          name,
          agent_address: address,
          auth_scheme: "bearer",
          credential,
          current_password: password,
        },
        key(),
      );
      assert.equal(created.status, "untested");
      assert.equal(created.agent_address, address);
      assert.equal(created.auth_scheme, "bearer");
      // Registration has no secret to carry, and never the credential.
      assert.ok(!JSON.stringify(created).includes(credential));
      assert.ok(!("inbound_signing_secret" in created));
      return created;
    };

    const readyConnection = await connect(
      "Integration agent",
      agent.origin,
      "integration-agent-token",
    );
    const tested = await client.testAgentConnection(readyConnection.id);
    assert.equal(tested.status, "ready");
    assert.equal(tested.ready_for_handoff, true);
    assert.equal(tested.last_test_error_code, null);
    assert.ok(tested.card, "a ready connection carries the discovered card");
    assert.equal(tested.card?.protocol_version, "1.0");
    assert.equal(tested.guarantee_tier, "best_effort");
    assert.ok(tested.tier_disclosure?.startsWith("Best-effort single start."));
    assert.ok(!JSON.stringify(tested).includes("integration-agent-token"));
    ok("agent connection test reports ready with the discovered card and tier");

    const wrongKey = await connect("Wrong key agent", agent.origin, "not-the-token");
    const rejected = await client.testAgentConnection(wrongKey.id);
    assert.equal(rejected.status, "invalid_credentials");
    assert.equal(rejected.last_test_error_code, "a2a_credentials_rejected");
    assert.equal(rejected.ready_for_handoff, false);
    assert.ok(!JSON.stringify(rejected).includes("not-the-token"));
    ok("a rejected credential is named as such and never echoed");

    const notAnAgent = await connect("Bare socket", noCard.origin, "irrelevant");
    const unsupported = await client.testAgentConnection(notAnAgent.id);
    assert.equal(unsupported.status, "unsupported");
    assert.equal(unsupported.last_test_error_code, "a2a_not_an_agent");
    assert.equal(unsupported.card, null);
    ok("a socket with no agent card reports a2a_not_an_agent, not unreachable");

    // Stopped last so the two live agents above are untouched by it.
    const dead = await startFakeAgent({});
    const deadOrigin = dead.origin;
    dead.stop();
    await new Promise((resolve) => setTimeout(resolve, 300));
    const unreachableConnection = await connect("Dead agent", deadOrigin, "irrelevant");
    const unreachable = await client.testAgentConnection(unreachableConnection.id);
    assert.equal(unreachable.status, "unreachable");
    assert.equal(unreachable.last_test_error_code, "a2a_unreachable");
    ok("an address nothing answers on reports a2a_unreachable");

    const listed = await client.listAgentConnections();
    assert.equal(listed.length, 4);
    assert.ok(!JSON.stringify(listed).includes("integration-agent-token"));
    assert.ok(!JSON.stringify(listed).includes("inbound_signing_secret"));
    ok("no connection read carries a credential or any secret");
  } finally {
    agent.stop();
    noCard.stop();
  }
}

main().catch((error) => {
  console.error("\nIntegration suite FAILED:");
  console.error(error);
  process.exit(1);
});
