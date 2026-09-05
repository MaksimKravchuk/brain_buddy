import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { allure } from "allure-playwright";

type JsonRecord = Record<string, unknown>;
type Task = {
  id: string;
  title: string;
  state: string;
  revision: number;
};
type Project = { id: string; name: string; revision: number };
type Tag = { id: string; name: string; revision: number };
type BrainDumpOperation = {
  id: string;
  status: string;
  revision: number;
  proposals: Array<{
    id: string;
    title: string;
    revision: number;
    deleted: boolean;
    locked_fields: string[];
    user_edited: boolean;
  }>;
  committed_task_ids: string[];
};

const password = "Correct Horse Battery 2026!";
const forbiddenDemoTitles = [
  "Draft the launch announcement",
  "Choose a venue for the offsite",
  "Review Q3 pricing assumptions"
];
const browserDiagnostics = new WeakMap<Page, string[]>();

test.beforeEach(async ({ page }) => {
  const diagnostics: string[] = [];
  browserDiagnostics.set(page, diagnostics);
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      diagnostics.push(`console.${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => diagnostics.push(`pageerror: ${error.message}`));
  page.on("response", (response) => {
    if (response.status() >= 400) {
      diagnostics.push(`response ${response.status()}: ${response.request().method()} ${response.url()}`);
    }
  });
});

test.afterEach(async ({ page }, testInfo) => {
  const diagnostics = browserDiagnostics.get(page) ?? [];
  await testInfo.attach("browser-console-network-diagnostics", {
    body: diagnostics.length ? diagnostics.join("\n") : "No console warnings/errors or HTTP error responses captured.",
    contentType: "text/plain"
  });
});

function unique(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function productLabels(story: string): Promise<void> {
  await allure.epic("BrainBuddy MVP loop");
  await allure.feature("Native tasks and Voice Brain Dump");
  await allure.story(story);
  await allure.owner("brainbuddydev");
}

function assertCondition(condition: unknown, message: string): asserts condition {
  if (!condition) {
    throw new Error(message);
  }
}

function assertArrayLength<T>(items: T[], expected: number, label: string): void {
  assertCondition(items.length === expected, `${label}: expected ${expected}, received ${items.length}`);
}

function assertStringArrayEquals(actual: string[], expected: string[], label: string): void {
  assertCondition(
    JSON.stringify(actual) === JSON.stringify(expected),
    `${label}: expected ${JSON.stringify(expected)}, received ${JSON.stringify(actual)}`
  );
}

function createInvite(): string {
  const composeProject = process.env.BRAIN_BUDDY_E2E_COMPOSE_PROJECT ?? process.env.COMPOSE_PROJECT_NAME;
  const env = { ...process.env };
  if (composeProject) {
    env.COMPOSE_PROJECT_NAME = composeProject;
  }
  return execFileSync("docker", ["compose", "exec", "-T", "backend", "python", "-m", "app.cli", "create-invite"], {
    cwd: "..",
    env,
    encoding: "utf8"
  }).trim();
}

async function expectOk(response: Awaited<ReturnType<Page["request"]["post"]>>, label: string): Promise<void> {
  if (!response.ok()) {
    throw new Error(`${label} failed with ${response.status()} ${await response.text()}`);
  }
}

async function signup(page: Page, label = unique("user")): Promise<{ email: string; password: string }> {
  const email = `${label}@brainbuddy.dev`;
  const response = await page.request.post("/api/auth/signup", {
    data: { email, password, invite_code: createInvite() }
  });
  await expectOk(response, `signup ${email}`);
  return { email, password };
}

async function loginViaUi(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/$/);
}

async function relogin(page: Page, email: string): Promise<void> {
  await page.request.post("/api/auth/logout");
  await page.context().clearCookies();
  await loginViaUi(page, email);
}

async function apiPost<T>(page: Page, path: string, data: JsonRecord, key = unique("idem")): Promise<T> {
  const response = await page.request.post(path, { data, headers: { "Idempotency-Key": key } });
  await expectOk(response, `POST ${path}`);
  return (await response.json()) as T;
}

async function apiPatch<T>(page: Page, path: string, data: JsonRecord, key = unique("idem")): Promise<T> {
  const response = await page.request.patch(path, { data, headers: { "Idempotency-Key": key } });
  await expectOk(response, `PATCH ${path}`);
  return (await response.json()) as T;
}

async function apiGet<T>(page: Page, path: string): Promise<T> {
  const response = await page.request.get(path);
  await expectOk(response, `GET ${path}`);
  return (await response.json()) as T;
}

// Polls manually instead of `expect.poll(...).toBe(...)`: the Allure reporter
// wraps each poll attempt's matcher in its own "Expect toBe" step, and a fast
// attempt that resolves in under 1ms is recorded with equal start/stop
// timestamps and no attachments -- a zero-duration, evidence-less step the
// taxonomy validator correctly rejects as a no-op. Each GET below already
// carries real request/response evidence and duration, and the single
// `assertCondition` below doesn't emit a synthetic Allure step at all.
async function waitForReconciledOperation(page: Page, operationId: string): Promise<BrainDumpOperation> {
  const deadline = Date.now() + 15_000;
  let operation: BrainDumpOperation;
  do {
    operation = await apiGet<BrainDumpOperation>(page, `/api/brain-dump-operations/${operationId}`);
    if (operation.status === "awaiting_confirmation") break;
    await new Promise((resolve) => setTimeout(resolve, 250));
  } while (Date.now() < deadline);
  assertCondition(
    operation.status === "awaiting_confirmation",
    `operation ${operationId} did not reach awaiting_confirmation within 15s (last status: ${operation.status})`
  );
  return operation;
}

function sha256Hex(data: Buffer | string): string {
  return createHash("sha256").update(data).digest("hex");
}

/** Upload one audio chunk and seal it through the real accurate-STT/reconciler
 * pipeline (deterministic in the compose test environment), producing a
 * genuinely reconciled, commit-eligible operation -- the only path production
 * accepts for `commit` (see `BRAIN_DUMP_NOT_RECONCILED` /
 * `BRAIN_DUMP_PROPOSAL_NOT_RECONCILED`). Returns the sealed, awaiting-
 * confirmation projection.
 */
async function sealWithDeterministicAudio(
  page: Page,
  operationId: string,
  audioText: string
): Promise<BrainDumpOperation> {
  const audio = Buffer.from(audioText, "utf-8");
  const digest = sha256Hex(audio);
  const uploadResponse = await page.request.put(`/api/brain-dump-operations/${operationId}/audio/0`, {
    data: audio,
    headers: { "X-Content-SHA256": digest, "Content-Type": "audio/x-brain-buddy-test-text" }
  });
  await expectOk(uploadResponse, `PUT audio/0 for ${operationId}`);
  const uploaded = (await uploadResponse.json()) as BrainDumpOperation;
  const manifestHash = sha256Hex(
    JSON.stringify([{ chunk_number: 0, sha256: digest, size_bytes: audio.length }])
  );
  await apiPost<BrainDumpOperation>(
    page,
    `/api/brain-dump-operations/${operationId}/seal`,
    { expected_revision: uploaded.revision, expected_chunks: 1, manifest_hash: manifestHash },
    unique("seal")
  );
  return waitForReconciledOperation(page, operationId);
}

async function createProject(page: Page, name: string): Promise<Project> {
  return apiPost<Project>(page, "/api/projects", { name, color: "#0ea5e9" });
}

async function createTag(page: Page, name: string): Promise<Tag> {
  return apiPost<Tag>(page, "/api/tags", { name });
}

async function createTask(page: Page, title: string, overrides: JsonRecord = {}): Promise<Task> {
  return apiPost<Task>(page, "/api/tasks", { title, state: "inbox", ...overrides });
}

async function listInboxTasks(page: Page): Promise<Task[]> {
  const payload = (await apiGet<{ items: Task[] }>(page, "/api/tasks?state=inbox"));
  return payload.items;
}

async function installSpeechBoundary(page: Page, media: "granted" | "denied" | "unavailable" = "granted"): Promise<void> {
  await page.addInitScript((mode) => {
    // `new MediaRecorder(stream)` requires a genuine MediaStream instance; a plain object
    // with a getTracks() shim fails Chromium's constructor type check. A canvas capture
    // stream gives real MediaStream/MediaStreamTrack objects without needing microphone
    // hardware or audio-context autoplay permissions.
    function fakeMediaStream(): MediaStream {
      const canvas = document.createElement("canvas");
      canvas.width = 2;
      canvas.height = 2;
      return canvas.captureStream();
    }
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: () =>
          mode === "denied"
            ? Promise.reject(new DOMException("Microphone blocked by test", "NotAllowedError"))
            : Promise.resolve(fakeMediaStream())
      }
    });

    if (mode === "unavailable") {
      delete (window as unknown as { SpeechRecognition?: unknown }).SpeechRecognition;
      delete (window as unknown as { webkitSpeechRecognition?: unknown }).webkitSpeechRecognition;
      return;
    }

    class FakeSpeechRecognition {
      continuous = false;
      interimResults = false;
      lang = "en-US";
      onresult: ((event: { results: Array<{ 0: { transcript: string }; isFinal: boolean }> }) => void) | null = null;
      onerror: ((event: { error: string }) => void) | null = null;
      start(): void {
        (window as unknown as { __brainBuddyRecognition?: FakeSpeechRecognition }).__brainBuddyRecognition = this;
      }
      stop() {}
    }

    (window as unknown as { SpeechRecognition: typeof FakeSpeechRecognition; webkitSpeechRecognition: typeof FakeSpeechRecognition }).SpeechRecognition = FakeSpeechRecognition;
    (window as unknown as { SpeechRecognition: typeof FakeSpeechRecognition; webkitSpeechRecognition: typeof FakeSpeechRecognition }).webkitSpeechRecognition = FakeSpeechRecognition;
    (window as unknown as { __emitSpeech: (text: string, isFinal?: boolean) => void }).__emitSpeech = (text: string, isFinal = true) => {
      const recognition = (window as unknown as { __brainBuddyRecognition?: FakeSpeechRecognition }).__brainBuddyRecognition;
      recognition?.onresult?.({ results: [{ 0: { transcript: text }, isFinal }] });
    };
  }, media);
}

async function installDeterministicSealedAudioBoundary(page: Page, sealedText: string): Promise<void> {
  await page.addInitScript((audioText) => {
    const fakeStream = { getTracks: () => [{ stop() {} }] } as unknown as MediaStream;
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: () => Promise.resolve(fakeStream) }
    });

    class FakeMediaRecorder {
      state: RecordingState = "inactive";
      mimeType = "audio/x-brain-buddy-test-text";
      ondataavailable: ((event: { data: Blob }) => void) | null = null;
      onstop: ((event: Event) => void) | null = null;
      constructor(public stream: MediaStream) {}
      start(): void {
        this.state = "recording";
      }
      pause(): void {
        this.state = "paused";
      }
      resume(): void {
        this.state = "recording";
      }
      stop(): void {
        this.state = "inactive";
        this.ondataavailable?.({
          data: new Blob([audioText], { type: "audio/x-brain-buddy-test-text" })
        });
        this.onstop?.(new Event("stop"));
      }
    }

    class FakeSpeechRecognition {
      continuous = false;
      interimResults = false;
      lang = "en-US";
      onresult: ((event: { results: Array<{ 0: { transcript: string }; isFinal: boolean }> }) => void) | null = null;
      onerror: ((event: { error: string }) => void) | null = null;
      start(): void {
        (window as unknown as { __brainBuddyRecognition?: FakeSpeechRecognition }).__brainBuddyRecognition = this;
      }
      stop(): void {}
    }

    (window as unknown as { MediaRecorder: typeof FakeMediaRecorder }).MediaRecorder = FakeMediaRecorder;
    (window as unknown as { SpeechRecognition: typeof FakeSpeechRecognition; webkitSpeechRecognition: typeof FakeSpeechRecognition }).SpeechRecognition = FakeSpeechRecognition;
    (window as unknown as { SpeechRecognition: typeof FakeSpeechRecognition; webkitSpeechRecognition: typeof FakeSpeechRecognition }).webkitSpeechRecognition = FakeSpeechRecognition;
    (window as unknown as { __emitSpeech: (text: string, isFinal?: boolean) => void }).__emitSpeech = (text: string, isFinal = true) => {
      const recognition = (window as unknown as { __brainBuddyRecognition?: FakeSpeechRecognition }).__brainBuddyRecognition;
      recognition?.onresult?.({ results: [{ 0: { transcript: text }, isFinal }] });
    };
  }, sealedText);
}

async function emitSpeech(page: Page, text: string, isFinal = true): Promise<void> {
  await page.evaluate(
    ({ spokenText, final }) => (window as unknown as { __emitSpeech: (value: string, isFinal: boolean) => void }).__emitSpeech(spokenText, final),
    { spokenText: text, final: isFinal }
  );
}

async function waitForStartedOperation(page: Page): Promise<void> {
  await expect(page.locator("[data-operation-id]")).not.toHaveAttribute("data-operation-id", "new");
}

async function allowSecureCloudTranscription(page: Page): Promise<void> {
  await page.getByRole("checkbox", { name: "Allow secure cloud transcription" }).check();
}

test("native task shell uses real backend counts, filters, reload and relogin persistence", async ({ page }) => {
  await productLabels("Native task shell navigation");

  const account = await test.step("create an isolated authenticated owner with real backend task fixtures", async () => {
    const created = await signup(page, unique("native-shell"));
    const project = await createProject(page, "Launch Plan");
    const tag = await createTag(page, "deep-work");
    await createTask(page, "Collect receipts", { state: "inbox" });
    await createTask(page, "Draft launch note", { state: "next", project_id: project.id, tag_ids: [tag.id] });
    await createTask(page, "Call supplier", { state: "next" });
    return { ...created, project, tag };
  });

  await test.step("open authenticated / through frontend nginx and verify backend counts without demo fixtures", async () => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Next actions" })).toBeVisible();
    await expect(page.getByText("2 tasks")).toBeVisible();
    // Next actions groups by project out of the box; the seeded project task
    // sits in its own group list under a "Launch Plan" heading.
    await expect(page.getByRole("list", { name: "Launch Plan" })).toContainText("Draft launch note");
    for (const title of forbiddenDemoTitles) {
      await expect(page.getByText(title, { exact: true })).toHaveCount(0);
    }
    await expect(page.getByRole("navigation", { name: "Task navigation" })).toContainText("Inbox");
    await expect(page.getByRole("navigation", { name: "Task navigation" })).toContainText("2");
  });

  await test.step("navigate by state, project and tag and survive reload", async () => {
    await page.getByRole("link", { name: /Inbox/ }).click();
    await expect(page.getByRole("heading", { name: "Inbox" })).toBeVisible();
    await expect(page.getByText("Collect receipts")).toBeVisible();

    await page.getByRole("link", { name: "Launch Plan" }).click();
    await expect(page.getByRole("heading", { name: "Launch Plan" })).toBeVisible();
    await expect(page.getByText("Draft launch note")).toBeVisible();

    await page.getByRole("link", { name: "#deep-work" }).click();
    await expect(page.getByRole("heading", { name: "#deep-work" })).toBeVisible();
    await expect(page.getByText("Draft launch note")).toBeVisible();
    await page.reload();
    await expect(page.getByText("Draft launch note")).toBeVisible();
  });

  await test.step("relogin and prove the same filtered backend row is still present", async () => {
    await relogin(page, account.email);
    await page.goto(`/tags/${account.tag.id}`);
    await expect(page.getByRole("heading", { name: "#deep-work" })).toBeVisible();
    await expect(page.getByText("Draft launch note")).toBeVisible();
  });

  await test.step("open the same canonical workspace at 390px without overflow", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Next actions" })).toBeVisible();
    await expect(page.getByText("Draft launch note")).toBeVisible();
    await page.getByRole("button", { name: "Open task navigation" }).click();
    await expect(page.getByRole("dialog", { name: "Task navigation" })).toContainText("Launch Plan");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    assertCondition(overflow <= 0, `390px workspace should not horizontally overflow; overflow=${overflow}`);
  });
});

test("minimal task management creates, edits, moves, completes, reopens and persists", async ({ page }) => {
  await productLabels("Minimal native task management");
  const account = await signup(page, unique("task-management"));

  await test.step("create an Inbox task from the native task shell", async () => {
    await page.goto("/tasks/inbox");
    await page.getByRole("combobox", { name: "New task title" }).fill("Plan dentist visit");
    await page.getByRole("button", { name: "Add task" }).click();
    await expect(page.getByText("Plan dentist visit")).toBeVisible();
  });

  await test.step("edit title and move Inbox to Next from the detail panel", async () => {
    await page.getByRole("link", { name: "Plan dentist visit" }).click();
    const detailTitle = page.getByRole("textbox", { name: "Title", exact: true });
    await detailTitle.fill("Book dentist checkup");
    await detailTitle.press("Enter");
    await expect(page.getByRole("link", { name: "Book dentist checkup" })).toBeVisible();
    await page.getByLabel("List").selectOption("next");
    await expect(page.getByRole("link", { name: "Book dentist checkup" })).toHaveCount(0);
    await page.goto("/tasks/next");
    await expect(page.getByText("Book dentist checkup")).toBeVisible();
  });

  await test.step("complete and reopen the task through the panel list selector", async () => {
    await page.getByRole("button", { name: "Complete Book dentist checkup" }).click();
    await expect(page.getByText("Book dentist checkup")).toHaveCount(0);
    await page.getByRole("checkbox", { name: "Show completed" }).check();
    await expect(page.getByText("Book dentist checkup")).toBeVisible();
    await page.getByRole("link", { name: "Book dentist checkup" }).click();
    await page.getByLabel("List").selectOption("next");
    await expect(page.getByRole("button", { name: "Complete Book dentist checkup" })).toBeVisible();
  });

  await test.step("reload and relogin prove the reopened Next task persisted", async () => {
    await page.reload();
    await expect(page.getByRole("link", { name: "Book dentist checkup" })).toBeVisible();
    await relogin(page, account.email);
    await page.goto("/tasks/next");
    await expect(page.getByText("Book dentist checkup")).toBeVisible();
  });
});

test("012-SC-001 012-SC-003 title completion is responsive and never writes before submit", async ({ page }, testInfo) => {
  await productLabels("Web task title autocomplete");
  await signup(page, unique("autocomplete"));
  const memberResponse = await page.request.get("/api/auth/me");
  await expectOk(memberResponse, "read signed-in member");
  const member = (await memberResponse.json()) as JsonRecord;
  let taskCreates = 0;
  let completionRequests = 0;
  let runtimeAutocompleteEnabled = true;
  let providerAvailable = true;
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname === "/api/tasks") {
      taskCreates += 1;
    }
  });
  await page.goto("/tasks/next");
  const rolloutOffInput = page.getByRole("combobox", { name: "New task title" });
  await rolloutOffInput.fill("Prepare rollout off notes");
  await expect(page.getByRole("checkbox", { name: /Allow/ })).toHaveCount(0);
  assertCondition(completionRequests === 0, "rollout OFF must not discover or generate completions");

  await page.route("**/api/auth/me", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ...member,
        feature_flags: {
          ...(member.feature_flags as JsonRecord),
          task_title_autocomplete: runtimeAutocompleteEnabled
        }
      })
    });
  });
  await page.route("**/api/tasks/title-completion-provider", async (route) => {
    completionRequests += 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ provider: providerAvailable ? "deterministic" : null })
    });
  });
  await page.route("**/api/tasks/title-completions", async (route) => {
    completionRequests += 1;
    const draft = String((route.request().postDataJSON() as JsonRecord).draft);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        request_id: "8f3d2f73-0e55-4f47-9f9b-1a0b6c7a9c6e",
        candidates: [`${draft} today`, `${draft} this week`, `${draft} tomorrow`]
      })
    });
  });
  await page.route("**/api/tasks/title-completions/accepted", async (route) => {
    await route.fulfill({ status: 204, body: "" });
  });

  for (const viewport of [{ width: 390, height: 851 }, { width: 1280, height: 780 }]) {
    await page.setViewportSize(viewport);
    await page.goto("/tasks/next");
    const input = page.getByRole("combobox", { name: "New task title" });
    await input.fill(`Prepare launch notes ${viewport.width}`);
    await page.getByRole("checkbox", { name: /Allow deterministic/ }).check();
    const listbox = page.getByRole("listbox", { name: "Task title suggestions" });
    await expect(listbox.getByRole("option")).toHaveCount(3);
    await testInfo.attach(`autocomplete-${viewport.width}`, {
      body: await page.screenshot({ fullPage: true }),
      contentType: "image/png"
    });
    await input.focus();
    await input.press("Enter");
    await expect(input).toHaveValue(`Prepare launch notes ${viewport.width} today`);
    assertCondition(taskCreates === (viewport.width === 390 ? 0 : 1), "acceptance must not create a Task");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    assertCondition(overflow <= 0, `autocomplete viewport ${viewport.width} must not overflow; overflow=${overflow}`);
    await input.press("Enter");
    const expectedTaskCreates = viewport.width === 390 ? 1 : 2;
    const createDeadline = Date.now() + 2_000;
    while (taskCreates !== expectedTaskCreates && Date.now() < createDeadline) {
      await new Promise((resolve) => setTimeout(resolve, 25));
    }
    assertCondition(
      taskCreates === expectedTaskCreates,
      `submit must create exactly ${expectedTaskCreates} Task(s); observed ${taskCreates}`
    );
  }

  await page.goto("/tasks/next");
  const arbitrationInput = page.getByRole("combobox", { name: "New task title" });
  await expect(page.getByRole("checkbox", { name: /Allow deterministic/ })).toBeVisible();
  const requestsBeforeSmartAdd = completionRequests;
  await arbitrationInput.fill("Call the bank #calls");
  await new Promise((resolve) => setTimeout(resolve, 450));
  assertCondition(
    completionRequests === requestsBeforeSmartAdd,
    "Smart Add token ownership must suppress autocomplete requests"
  );
  await expect(page.getByRole("listbox", { name: "Task title suggestions" })).toHaveCount(0);

  providerAvailable = false;
  await page.reload();
  const unavailableInput = page.getByRole("combobox", { name: "New task title" });
  await unavailableInput.fill("Keep unavailable draft intact");
  await expect(page.getByText("Suggestions unavailable.")).toBeVisible();
  await expect(unavailableInput).toHaveValue("Keep unavailable draft intact");

  runtimeAutocompleteEnabled = false;
  await page.reload();
  const runtimeOffInput = page.getByRole("combobox", { name: "New task title" });
  await runtimeOffInput.fill("Keep runtime off draft intact");
  await expect(page.getByRole("checkbox", { name: /Allow/ })).toHaveCount(0);
  await expect(runtimeOffInput).toHaveValue("Keep runtime off draft intact");
  assertCondition(taskCreates === 2, `runtime OFF must preserve the two submitted Tasks; observed ${taskCreates}`);

});

test("Voice Brain Dump shows a live transcript, reviews the reconciled task and saves exactly one Inbox task", async ({ page }) => {
  await productLabels("Voice Brain Dump happy path");
  await signup(page, unique("voice-happy"));
  await installDeterministicSealedAudioBoundary(page, "untranscribed sealed audio");

  await test.step("capture on mobile without hiding primary controls", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/brain-dump/new");
    await allowSecureCloudTranscription(page);
    await page.getByRole("button", { name: "Record" }).click();
    await waitForStartedOperation(page);
    const transcript = page.getByRole("region", { name: "What you've said · browser preview" });
    await expect(transcript).toContainText("Your words appear here as you speak");
    // A still-forming hypothesis is the live tail beside the microphone, not a
    // settled line of the record. Wait for its upload so the final result for the
    // same sequence cannot overtake it on the server (a stable segment rejects a
    // later differing write at its sequence).
    const interimUpload = page.waitForResponse(
      (response) => response.url().endsWith("/transcript") && response.request().method() === "POST"
    );
    await emitSpeech(page, "buy oat milk", false);
    await interimUpload;
    await expect(page.getByText("buy oat milk", { exact: true })).toBeVisible();
    await expect(transcript).not.toContainText("buy oat milk");
    await emitSpeech(page, "buy oat milk. call dentist", true);
    await expect(transcript).toContainText("buy oat milk. call dentist");
    await expect(transcript.getByRole("listitem")).toHaveCount(1);
    // Raw preview text is a status readout: no draft task card is ever minted from it.
    await expect(page.getByRole("article")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Stop & review" })).toBeVisible();
    const overflow = await page.evaluate(async () => {
      // Preserve this browser-side measurement as a real Allure step rather
      // than a zero-duration reporter placeholder rejected by CI taxonomy.
      await new Promise((resolve) => window.setTimeout(resolve, 10));
      return document.documentElement.scrollWidth - document.documentElement.clientWidth;
    });
    assertCondition(overflow <= 0, `mobile viewport should not horizontally overflow; overflow=${overflow}`);
  });

  await test.step("pause, resume and stop for review", async () => {
    await page.getByRole("button", { name: "Pause" }).click();
    await expect(page.getByText("Paused")).toBeVisible();
    await page.getByRole("button", { name: "Resume" }).click();
    await expect(page.getByText("Recording")).toBeVisible();
    await page.getByRole("button", { name: "Stop & review" }).click();
    // Only the reconciler's reading of the sealed-audio fixture becomes a task;
    // the browser preview text contributes no draft of its own.
    await expect(page.getByRole("heading", { name: "Review 1 task" })).toBeVisible({ timeout: 15_000 });
  });

  await test.step("edit the reconciled draft and prove nothing canonical exists before Save", async () => {
    await expect(page.getByLabel("Task title #1")).toHaveValue("Untranscribed sealed audio");
    await page.getByLabel("Task title #1").fill("Buy oat milk for breakfast");
    await page.keyboard.press("Tab");
    await expect(page.getByText("Edited", { exact: true })).toBeVisible();
    const beforeSave = await listInboxTasks(page);
    assertArrayLength(beforeSave, 0, "Inbox should remain empty before saving reviewed drafts");
  });

  await test.step("save creates exactly one real Inbox task with edited wording", async () => {
    await page.getByRole("button", { name: "Send 1 to inbox" }).click();
    await expect(page.getByRole("heading", { name: "Saved 1 task to Inbox" })).toBeVisible();
    await page.goto("/tasks/inbox");
    await expect(page.getByText("Buy oat milk for breakfast")).toBeVisible();
    const inbox = await listInboxTasks(page);
    assertStringArrayEquals(inbox.map((task) => task.title), ["Buy oat milk for breakfast"], "Inbox titles after saving brain dump");
  });
});

test("Voice Brain Dump shows a mixed-language preview as transcript and reviews only reconciled next actions", async ({ page }) => {
  await productLabels("Voice Brain Dump reconciled review from accurate audio");
  await signup(page, unique("voice-reconcile-clean"));
  await installDeterministicSealedAudioBoundary(
    page,
    "Надо починить BrainBuddy, потом сделать production smoke и написать Наташе"
  );
  let operationId = "";

  await test.step("a stable mixed-language preview is shown as transcript, never as draft tasks", async () => {
    await page.goto("/brain-dump/new");
    await allowSecureCloudTranscription(page);
    await page.getByRole("button", { name: "Record" }).click();
    await waitForStartedOperation(page);
    operationId = (await page.locator("[data-operation-id]").getAttribute("data-operation-id")) ?? "";
    await emitSpeech(
      page,
      "Сделать production smoke. написать Наташе. купить хлеб и молоко. удалить черновик. Починить brain body потом позвонить маме"
    );
    const transcript = page.getByRole("region", { name: "What you've said · browser preview" });
    await expect(transcript).toContainText("Починить brain body потом позвонить маме");
    await expect(page.getByRole("article")).toHaveCount(0);
    const recording = await apiGet<BrainDumpOperation>(page, `/api/brain-dump-operations/${operationId}`);
    assertArrayLength(recording.proposals, 0, "browser preview must not derive proposals");
    assertArrayLength(await listInboxTasks(page), 0, "Inbox before reconciliation");
  });

  await test.step("accurate reconciliation yields exactly the reconciled tasks with nothing left to clean up", async () => {
    await page.getByRole("button", { name: "Stop & review" }).click();
    await expect(page.getByRole("heading", { name: "Review 3 tasks" })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: "Use suggestion" })).toHaveCount(0);
    const reconciled = await apiGet<BrainDumpOperation>(page, `/api/brain-dump-operations/${operationId}`);
    const active = reconciled.proposals.filter((proposal) => !proposal.deleted);
    assertStringArrayEquals(
      active.map((proposal) => proposal.title).sort(),
      ["Починить BrainBuddy", "Сделать production smoke", "Написать Наташе"].sort(),
      "Reconciled active proposal titles"
    );
    await expect(page.getByRole("button", { name: "Send 3 to inbox" })).toBeEnabled();
  });

  await test.step("review edits and deletions are honoured and nothing canonical exists before Save", async () => {
    await page.getByLabel("Task title #1").fill("SMOKE Починить BrainBuddy");
    await page.keyboard.press("Tab");
    await expect(page.getByText("Edited", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Delete Написать Наташе" }).click();
    await expect(page.getByRole("button", { name: "Delete Написать Наташе" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Review 2 tasks" })).toBeVisible();
    const edited = await apiGet<BrainDumpOperation>(page, `/api/brain-dump-operations/${operationId}`);
    const locked = edited.proposals.find((proposal) => proposal.title === "SMOKE Починить BrainBuddy");
    assertCondition(
      locked?.locked_fields.includes("title") && locked.user_edited,
      "a review edit must lock the title on the reconciled proposal"
    );
    assertArrayLength(await listInboxTasks(page), 0, "Inbox before explicit Save");
    await page.getByRole("button", { name: "Discard all" }).click();
  });
});

test("Voice Brain Dump resume and commit idempotency do not create duplicate Inbox tasks", async ({ page }) => {
  await productLabels("Voice Brain Dump idempotency and recovery");
  const account = await signup(page, unique("voice-recovery"));
  await installDeterministicSealedAudioBoundary(page, "untranscribed sealed audio");
  let operationId = "";

  await test.step("pause an active operation, reload it, and resume from the persisted projection", async () => {
    await page.goto("/brain-dump/new");
    await page.getByRole("textbox", { name: "Voice key terms" }).fill("untranscribed sealed audio");
    await allowSecureCloudTranscription(page);
    await page.getByRole("button", { name: "Record" }).click();
    await waitForStartedOperation(page);
    await emitSpeech(page, "write weekly update", true);
    await expect(page.getByRole("region", { name: "What you've said · browser preview" })).toContainText("write weekly update");
    operationId = (await page.locator("[data-operation-id]").getAttribute("data-operation-id")) ?? "";
    assertCondition(/^brain_dump_/.test(operationId), `expected persisted brain dump operation id, received ${operationId}`);
    await page.getByRole("button", { name: "Pause" }).click();
    await expect(page.getByRole("button", { name: "Resume" })).toBeVisible();
    await page.reload();
    await expect(page.getByText("Paused")).toBeVisible();
    await expect(page.getByRole("region", { name: "What you've said · browser preview" })).toContainText("write weekly update");
    await page.getByRole("button", { name: "Resume" }).click();
    await expect(page.getByText("Recording")).toBeVisible();
  });

  await test.step("confirm once, retry commit against completed operation, then verify one committed task after relogin", async () => {
    await page.getByRole("button", { name: "Stop & review" }).click();
    // Only the reconciler's reading of the sealed original audio becomes a draft;
    // the browser preview text never mints one, so there is nothing to delete.
    await expect(page.getByRole("heading", { name: "Review 1 task" })).toBeVisible({ timeout: 15_000 });
    await page.getByLabel("Task title #1").fill("Write weekly update for the team");
    await page.keyboard.press("Tab");
    await expect(page.getByText("Edited", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Send 1 to inbox" }).click();
    await expect(page.getByRole("heading", { name: "Saved 1 task to Inbox" })).toBeVisible();
    const completed = await apiGet<BrainDumpOperation>(page, `/api/brain-dump-operations/${operationId}`);
    assertArrayLength(completed.committed_task_ids, 1, "Committed task ids after first save");
    const retried = await apiPost<BrainDumpOperation>(
      page,
      `/api/brain-dump-operations/${operationId}/commit`,
      { expected_revision: completed.revision },
      unique("retry-commit")
    );
    assertStringArrayEquals(retried.committed_task_ids, completed.committed_task_ids, "Idempotent commit task ids");
    await relogin(page, account.email);
    await page.goto("/tasks/inbox");
    await expect(page.getByText("Write weekly update for the team")).toBeVisible();
    const inbox = await listInboxTasks(page);
    assertStringArrayEquals(
      inbox.map((task) => task.title),
      ["Write weekly update for the team"],
      "Recovered Inbox titles"
    );
  });
});

test("Voice Brain Dump failures are visible and preserve recoverable live sessions", async ({ page }) => {
  await productLabels("Voice Brain Dump failure recovery");

  await test.step("unavailable speech recognition still records original audio and starts a backend operation", async () => {
    await signup(page, unique("voice-unavailable"));
    await installSpeechBoundary(page, "unavailable");
    const startRequests: string[] = [];
    page.on("request", (request) => {
      if (request.method() === "POST" && request.url().includes("/api/brain-dump-operations")) {
        startRequests.push(request.url());
      }
    });
    await page.goto("/brain-dump/new");
    await allowSecureCloudTranscription(page);
    await page.getByRole("button", { name: "Record" }).click();
    await waitForStartedOperation(page);
    assertArrayLength(startRequests, 1, "Unavailable speech recognition should still start one backend operation for original-audio capture");
  });

  await test.step("denied microphone creates no backend operation", async () => {
    const deniedPage = await page.context().newPage();
    await signup(deniedPage, unique("voice-denied"));
    await installSpeechBoundary(deniedPage, "denied");
    const startRequests: string[] = [];
    deniedPage.on("request", (request) => {
      if (request.method() === "POST" && request.url().includes("/api/brain-dump-operations")) {
        startRequests.push(request.url());
      }
    });
    await deniedPage.goto("/brain-dump/new");
    await allowSecureCloudTranscription(deniedPage);
    await deniedPage.getByRole("button", { name: "Record" }).click();
    await expect(deniedPage.getByRole("alert")).toContainText("Microphone");
    assertArrayLength(startRequests, 0, "Denied microphone should not start backend operations");
    await deniedPage.close();
  });

  await test.step("failed transcript, pause, finish, cancel and commit preserve drafts with visible errors", async () => {
    const recoveryPage = await page.context().newPage();
    await signup(recoveryPage, unique("voice-failures"));
    await installSpeechBoundary(recoveryPage);
    await recoveryPage.goto("/brain-dump/new");
    await allowSecureCloudTranscription(recoveryPage);
    await recoveryPage.getByRole("button", { name: "Record" }).click();
    await waitForStartedOperation(recoveryPage);
    await emitSpeech(recoveryPage, "prepare quarterly report", true);
    const transcript = recoveryPage.getByRole("region", { name: "What you've said · browser preview" });
    await expect(transcript).toContainText("prepare quarterly report");
    const operationId = (await recoveryPage.locator("[data-operation-id]").getAttribute("data-operation-id")) ?? "";
    await apiPost<BrainDumpOperation>(
      recoveryPage,
      `/api/brain-dump-operations/${operationId}/transcript`,
      { segments: [{ sequence: 2, text: "external concurrent draft", stability: "stable" }] },
      unique("external-transcript")
    );
    await emitSpeech(recoveryPage, "different browser draft", true);
    await expect(recoveryPage.getByRole("alert")).toBeVisible();
    await expect(transcript).toContainText("prepare quarterly report");

    await recoveryPage.getByRole("button", { name: "Pause" }).click();
    await expect(recoveryPage.getByRole("alert")).toBeVisible();
    await expect(transcript).toContainText("prepare quarterly report");
    await recoveryPage.getByRole("button", { name: "Stop & review" }).click();
    await expect(recoveryPage.getByRole("alert")).toBeVisible();
    await recoveryPage.getByRole("button", { name: "Discard" }).click();
    await expect(recoveryPage.getByRole("alert")).toBeVisible();
    await expect(transcript).toContainText("prepare quarterly report");

    // The stale local projection intentionally rejected several commands above.
    // Resume from the persisted operation route to obtain the current revision,
    // rather than reloading the `/new` route with no operation identifier.
    await recoveryPage.goto(`/brain-dump/${operationId}`);
    await expect(recoveryPage.locator("[data-operation-id]")).toHaveAttribute("data-operation-id", operationId);
    await recoveryPage.getByRole("button", { name: "Stop & review" }).click();
    await expect(recoveryPage.getByRole("heading", { name: /Review/ })).toBeVisible({ timeout: 15_000 });
    const loaded = await apiGet<BrainDumpOperation>(recoveryPage, `/api/brain-dump-operations/${operationId}`);
    await apiPatch<BrainDumpOperation>(
      recoveryPage,
      `/api/brain-dump-operations/${operationId}/proposals/${loaded.proposals[0].id}`,
      { title: "Concurrent edit", expected_revision: loaded.revision },
      unique("external-proposal")
    );
    // The page still holds the pre-edit revision, so Save is refused by the
    // server's optimistic lock (visible error, no task) rather than committing
    // stale state and manufacturing a duplicate task.
    await recoveryPage.getByRole("button", { name: /Send .* to inbox/ }).click();
    await expect(recoveryPage.getByRole("alert")).toBeVisible();
    assertArrayLength(await listInboxTasks(recoveryPage), 0, "a stale-revision save must not create a task");
    await expect(recoveryPage.getByLabel("Task title #1")).toBeVisible();
    await recoveryPage.close();
  });
});

test("owner isolation hides tasks, brain dump operations, drafts and committed linkage from another user", async ({ page }) => {
  await productLabels("Owner isolation");
  await signup(page, unique("owner-a"));
  const task = await createTask(page, "Owner A private task", { state: "inbox" });
  const operation = await apiPost<BrainDumpOperation>(
    page,
    "/api/brain-dump-operations",
    { consent: { microphone: true, external_processing_allowed: true, provider: "openai" } },
    unique("owner-a-start")
  );
  const withTranscript = await apiPost<BrainDumpOperation>(
    page,
    `/api/brain-dump-operations/${operation.id}/transcript`,
    { segments: [{ sequence: 1, text: "owner a private draft", stability: "stable" }] },
    unique("owner-a-transcript")
  );
  // A browser-preview transcript append is a status readout, never a task
  // source: it mints no proposal. Production only ever accepts commit for a
  // genuinely sealed and reconciled batch (`BRAIN_DUMP_NOT_RECONCILED` /
  // `BRAIN_DUMP_PROPOSAL_NOT_RECONCILED` otherwise), so seal real audio through
  // the deterministic accurate-STT/reconciler pipeline to obtain a linked task
  // for the isolation assertions below.
  assertArrayLength(withTranscript.proposals, 0, "a preview transcript append must not derive proposals");
  const sealed = await sealWithDeterministicAudio(page, operation.id, "owner isolation sealed audio");
  const committed = await apiPost<BrainDumpOperation>(
    page,
    `/api/brain-dump-operations/${operation.id}/commit`,
    { expected_revision: sealed.revision },
    unique("owner-a-commit")
  );
  assertCondition(
    committed.committed_task_ids.length > 0,
    "owner A commit must return at least one committed task ID"
  );
  const committedTaskId = committed.committed_task_ids[0];
  const committedTask = await apiGet<Task>(page, `/api/tasks/${committedTaskId}`);
  assertCondition(
    committedTask.title.length > 0,
    "owner A committed task must have a non-empty title"
  );

  await test.step("second owner cannot fetch first owner's task or brain dump operation", async () => {
    const secondPage = await page.context().newPage();
    await signup(secondPage, unique("owner-b"));
    const taskResponse = await secondPage.request.get(`/api/tasks/${task.id}`);
    assertCondition(taskResponse.status() === 404, `second owner task fetch should 404, got ${taskResponse.status()}`);
    const operationResponse = await secondPage.request.get(`/api/brain-dump-operations/${operation.id}`);
    assertCondition(operationResponse.status() === 404, `second owner operation fetch should 404, got ${operationResponse.status()}`);
    const committedTaskResponse = await secondPage.request.get(`/api/tasks/${committedTaskId}`);
    assertCondition(
      committedTaskResponse.status() === 404,
      `second owner committed task fetch should 404, got ${committedTaskResponse.status()}`
    );
    await secondPage.goto("/tasks/inbox");
    await expect(secondPage.getByText("Owner A private task")).toHaveCount(0);
    await expect(secondPage.getByText(committedTask.title)).toHaveCount(0);
    await secondPage.close();
  });
});
