import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
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
  proposals: Array<{ id: string; title: string; revision: number }>;
  committed_task_ids: string[];
};

const password = "Correct Horse Battery 2026!";

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
  await expect(page).toHaveURL(/\/tasks\/next$/);
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

async function emitSpeech(page: Page, text: string, isFinal = true): Promise<void> {
  await page.evaluate(
    ({ spokenText, final }) => (window as unknown as { __emitSpeech: (value: string, isFinal: boolean) => void }).__emitSpeech(spokenText, final),
    { spokenText: text, final: isFinal }
  );
}

async function waitForStartedOperation(page: Page): Promise<void> {
  await expect(page.locator("[data-operation-id]")).not.toHaveAttribute("data-operation-id", "new");
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

  await test.step("open /tasks/next through frontend nginx and verify backend counts and rows", async () => {
    await page.goto("/tasks/next");
    await expect(page.getByRole("heading", { name: "Next actions" })).toBeVisible();
    await expect(page.getByText("2 tasks")).toBeVisible();
    await expect(page.getByRole("list", { name: "Tasks" })).toContainText("Draft launch note");
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
});

test("minimal task management creates, edits, moves, completes, reopens and persists", async ({ page }) => {
  await productLabels("Minimal native task management");
  const account = await signup(page, unique("task-management"));

  await test.step("create an Inbox task from the native task shell", async () => {
    await page.goto("/tasks/inbox");
    await page.getByRole("textbox", { name: "New task title" }).fill("Plan dentist visit");
    await page.getByRole("button", { name: "Add task" }).click();
    await expect(page.getByText("Plan dentist visit")).toBeVisible();
  });

  await test.step("edit title and move Inbox to Next", async () => {
    await page.getByRole("button", { name: "Edit Plan dentist visit" }).click();
    await page.getByRole("textbox", { name: "Task title", exact: true }).fill("Book dentist checkup");
    await page.getByRole("button", { name: "Save task title" }).click();
    await expect(page.getByText("Book dentist checkup")).toBeVisible();
    await page.getByRole("button", { name: "Move Book dentist checkup to Next" }).click();
    await expect(page.getByText("Book dentist checkup")).toHaveCount(0);
    await page.goto("/tasks/next");
    await expect(page.getByText("Book dentist checkup")).toBeVisible();
  });

  await test.step("complete and reopen the task", async () => {
    await page.getByRole("button", { name: "Complete Book dentist checkup" }).click();
    await expect(page.getByText("Book dentist checkup")).toHaveCount(0);
    await page.getByRole("checkbox", { name: "Show terminal tasks" }).check();
    await expect(page.getByText("Book dentist checkup")).toBeVisible();
    await page.getByRole("link", { name: "Book dentist checkup" }).click();
    await page.getByRole("button", { name: "Reopen to Next" }).click();
    await expect(page.getByRole("button", { name: "Complete Book dentist checkup" })).toBeVisible();
  });

  await test.step("reload and relogin prove the reopened Next task persisted", async () => {
    await page.reload();
    await expect(page.getByText("Book dentist checkup")).toBeVisible();
    await relogin(page, account.email);
    await page.goto("/tasks/next");
    await expect(page.getByText("Book dentist checkup")).toBeVisible();
  });
});

test("Voice Brain Dump records provisional cards, reviews edits/deletes and saves exactly one Inbox task", async ({ page }) => {
  await productLabels("Voice Brain Dump happy path");
  await signup(page, unique("voice-happy"));
  await installSpeechBoundary(page);

  await test.step("capture on mobile without hiding primary controls", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/brain-dump/new");
    await page.getByRole("button", { name: "Record" }).click();
    await waitForStartedOperation(page);
    await emitSpeech(page, "buy oat milk", false);
    await expect(page.getByRole("article", { name: "Draft task 1: Buy oat milk" })).toBeVisible();
    await expect(page.getByText("Wording still changing")).toBeVisible();
    await emitSpeech(page, "buy oat milk. call dentist", true);
    await expect(page.getByRole("article", { name: "Draft task 1: Buy oat milk" })).toBeVisible();
    await expect(page.getByRole("article", { name: "Draft task 2: Call dentist" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Stop & review" })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    assertCondition(overflow <= 0, `mobile viewport should not horizontally overflow; overflow=${overflow}`);
  });

  await test.step("pause, resume and stop for review", async () => {
    await page.getByRole("button", { name: "Pause" }).click();
    await expect(page.getByText("Paused")).toBeVisible();
    await page.getByRole("button", { name: "Resume" }).click();
    await expect(page.getByText("Recording")).toBeVisible();
    await page.getByRole("button", { name: "Stop & review" }).click();
    // Accurate STT reconciles the sealed original audio independently of the browser
    // preview text; since the E2E capture stream carries no recognizable speech, it
    // surfaces one additional placeholder draft alongside the two speech-derived drafts.
    await expect(page.getByRole("heading", { name: "Review 3 tasks" })).toBeVisible();
  });

  await test.step("edit one draft, delete two drafts and prove nothing canonical exists before Save", async () => {
    await page.getByLabel("Task title #1").fill("Buy oat milk for breakfast");
    await page.keyboard.press("Tab");
    await expect(page.getByText("Edited")).toBeVisible();
    await page.getByRole("button", { name: "Delete Call dentist" }).click();
    await expect(page.getByText("Call dentist")).toHaveCount(0);
    await page.getByRole("button", { name: "Delete Untranscribed sealed audio" }).click();
    await expect(page.getByText("Untranscribed sealed audio")).toHaveCount(0);
    const beforeSave = await listInboxTasks(page);
    assertArrayLength(beforeSave, 0, "Inbox should remain empty before saving reviewed drafts");
  });

  await test.step("save creates exactly one real Inbox task with edited wording", async () => {
    await page.getByRole("button", { name: "Save 1 to inbox" }).click();
    await expect(page.getByRole("heading", { name: "Saved 1 task to Inbox" })).toBeVisible();
    await page.goto("/tasks/inbox");
    await expect(page.getByText("Buy oat milk for breakfast")).toBeVisible();
    const inbox = await listInboxTasks(page);
    assertStringArrayEquals(inbox.map((task) => task.title), ["Buy oat milk for breakfast"], "Inbox titles after saving brain dump");
  });
});

test("Voice Brain Dump resume and commit idempotency do not create duplicate Inbox tasks", async ({ page }) => {
  await productLabels("Voice Brain Dump idempotency and recovery");
  const account = await signup(page, unique("voice-recovery"));
  await installSpeechBoundary(page);
  let operationId = "";

  await test.step("pause an active operation, reload it, and resume from the persisted projection", async () => {
    await page.goto("/brain-dump/new");
    await page.getByRole("button", { name: "Record" }).click();
    await waitForStartedOperation(page);
    await emitSpeech(page, "write weekly update", true);
    await expect(page.getByRole("article", { name: "Draft task 1: Write weekly update" })).toBeVisible();
    operationId = (await page.locator("[data-operation-id]").getAttribute("data-operation-id")) ?? "";
    assertCondition(/^brain_dump_/.test(operationId), `expected persisted brain dump operation id, received ${operationId}`);
    await page.getByRole("button", { name: "Pause" }).click();
    await expect(page.getByRole("button", { name: "Resume" })).toBeVisible();
    await page.reload();
    await expect(page.getByText("Paused")).toBeVisible();
    await expect(page.getByRole("article", { name: "Draft task 1: Write weekly update" })).toBeVisible();
    await page.getByRole("button", { name: "Resume" }).click();
    await expect(page.getByText("Recording")).toBeVisible();
  });

  await test.step("confirm once, retry commit against completed operation, then verify one committed task after relogin", async () => {
    await page.getByRole("button", { name: "Stop & review" }).click();
    // Accurate STT reconciles the sealed original audio in addition to the browser
    // preview-derived draft; delete the placeholder before saving so committed state
    // still reflects exactly one recovered task.
    await expect(page.getByRole("heading", { name: "Review 2 tasks" })).toBeVisible();
    await page.getByRole("button", { name: "Delete Untranscribed sealed audio" }).click();
    await expect(page.getByRole("heading", { name: "Review 1 task" })).toBeVisible();
    await page.getByRole("button", { name: "Save 1 to inbox" }).click();
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
    await expect(page.getByText("Write weekly update")).toBeVisible();
    const inbox = await listInboxTasks(page);
    assertStringArrayEquals(inbox.map((task) => task.title), ["Write weekly update"], "Recovered Inbox titles");
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
    await recoveryPage.getByRole("button", { name: "Record" }).click();
    await waitForStartedOperation(recoveryPage);
    await emitSpeech(recoveryPage, "prepare quarterly report", true);
    await expect(recoveryPage.getByRole("article", { name: "Draft task 1: Prepare quarterly report" })).toBeVisible();
    const operationId = (await recoveryPage.locator("[data-operation-id]").getAttribute("data-operation-id")) ?? "";
    await apiPost<BrainDumpOperation>(
      recoveryPage,
      `/api/brain-dump-operations/${operationId}/transcript`,
      { segments: [{ sequence: 2, text: "external concurrent draft", stability: "stable" }] },
      unique("external-transcript")
    );
    await emitSpeech(recoveryPage, "different browser draft", true);
    await expect(recoveryPage.getByRole("alert")).toBeVisible();
    await expect(recoveryPage.getByRole("article", { name: "Draft task 1: Prepare quarterly report" })).toBeVisible();

    await recoveryPage.getByRole("button", { name: "Pause" }).click();
    await expect(recoveryPage.getByRole("alert")).toBeVisible();
    await expect(recoveryPage.getByRole("article", { name: "Draft task 1: Prepare quarterly report" })).toBeVisible();
    await recoveryPage.getByRole("button", { name: "Stop & review" }).click();
    await expect(recoveryPage.getByRole("alert")).toBeVisible();
    await recoveryPage.getByRole("button", { name: "Discard" }).click();
    await expect(recoveryPage.getByRole("alert")).toBeVisible();
    await expect(recoveryPage.getByRole("article", { name: "Draft task 1: Prepare quarterly report" })).toBeVisible();

    await recoveryPage.reload();
    await recoveryPage.getByRole("button", { name: "Stop & review" }).click();
    await expect(recoveryPage.getByRole("heading", { name: /Review/ })).toBeVisible();
    const loaded = await apiGet<BrainDumpOperation>(recoveryPage, `/api/brain-dump-operations/${operationId}`);
    await apiPatch<BrainDumpOperation>(
      recoveryPage,
      `/api/brain-dump-operations/${operationId}/proposals/${loaded.proposals[0].id}`,
      { title: "Concurrent edit", expected_revision: loaded.revision },
      unique("external-proposal")
    );
    await recoveryPage.getByRole("button", { name: /Save .* to inbox/ }).click();
    await expect(recoveryPage.getByRole("alert")).toBeVisible();
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
    { consent: { microphone: true, external_processing_allowed: false } },
    unique("owner-a-start")
  );
  const withDraft = await apiPost<BrainDumpOperation>(
    page,
    `/api/brain-dump-operations/${operation.id}/transcript`,
    { segments: [{ sequence: 1, text: "owner a private draft", stability: "stable" }] },
    unique("owner-a-transcript")
  );
  const awaiting = await apiPost<BrainDumpOperation>(
    page,
    `/api/brain-dump-operations/${operation.id}/finish`,
    { expected_revision: withDraft.revision },
    unique("owner-a-finish")
  );
  const committed = await apiPost<BrainDumpOperation>(
    page,
    `/api/brain-dump-operations/${operation.id}/commit`,
    { expected_revision: awaiting.revision },
    unique("owner-a-commit")
  );

  await test.step("second owner cannot fetch first owner's task or brain dump operation", async () => {
    const secondPage = await page.context().newPage();
    await signup(secondPage, unique("owner-b"));
    const taskResponse = await secondPage.request.get(`/api/tasks/${task.id}`);
    assertCondition(taskResponse.status() === 404, `second owner task fetch should 404, got ${taskResponse.status()}`);
    const operationResponse = await secondPage.request.get(`/api/brain-dump-operations/${operation.id}`);
    assertCondition(operationResponse.status() === 404, `second owner operation fetch should 404, got ${operationResponse.status()}`);
    const committedTaskResponse = await secondPage.request.get(`/api/tasks/${committed.committed_task_ids[0]}`);
    assertCondition(
      committedTaskResponse.status() === 404,
      `second owner committed task fetch should 404, got ${committedTaskResponse.status()}`
    );
    await secondPage.goto("/tasks/inbox");
    await expect(secondPage.getByText("Owner A private task")).toHaveCount(0);
    await expect(secondPage.getByText("Owner a private draft")).toHaveCount(0);
    await secondPage.close();
  });
});
