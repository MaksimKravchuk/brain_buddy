import { chromium } from "../../../frontend/node_modules/@playwright/test/index.mjs";
import { mkdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const prototypePath = path.join(here, "prototype.html");
const prototypeUrl = new URL(`file://${prototypePath}`);
const outputDir = path.join(here, "screenshots");

const screens = [
  "workspace",
  "task",
  "thinking",
  "capture",
  "review",
  "confirmed",
  "weekly"
];
const viewports = [
  { label: "desktop", width: 1440, height: 900 },
  { label: "375", width: 375, height: 812 },
  { label: "430", width: 430, height: 932 }
];

const html = await readFile(prototypePath, "utf8");
for (const required of [
  'viewport-fit=cover',
  'env(safe-area-inset-top)',
  'env(safe-area-inset-bottom)',
  'prefers-reduced-motion',
  'aria-live="polite"',
  'min-width: 44px',
  'min-height: 44px'
]) {
  if (!html.includes(required)) throw new Error(`Static validation: missing ${required}`);
}
for (const forbidden of ["setInterval(", "fake percentage", "live transcript"]) {
  if (html.includes(forbidden)) throw new Error(`Static validation: forbidden ${forbidden}`);
}
console.log("static validation: responsive, safe-area, reduced-motion, aria-live, and touch-target contracts present");

await mkdir(outputDir, { recursive: true });
const browser = await chromium.launch({ headless: true });

for (const screen of screens) {
  for (const viewport of viewports) {
    const page = await browser.newPage({
      viewport: { width: viewport.width, height: viewport.height },
      deviceScaleFactor: 1,
      reducedMotion: "reduce"
    });
    const errors = [];
    page.on("console", message => {
      if (message.type() === "error") errors.push(message.text());
    });
    page.on("pageerror", error => errors.push(error.message));

    prototypeUrl.search = `?screen=${screen}`;
    await page.goto(prototypeUrl.href, { waitUntil: "load" });
    await page.screenshot({
      path: path.join(outputDir, `${screen}-${viewport.label}.png`),
      fullPage: false,
      animations: "disabled"
    });

    const dimensions = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth
    }));
    if (dimensions.scrollWidth > dimensions.clientWidth) {
      throw new Error(`${screen}-${viewport.label}: horizontal overflow ${dimensions.scrollWidth} > ${dimensions.clientWidth}`);
    }
    if (viewport.width < 500) {
      const undersized = await page.locator("button:visible, select:visible, a:visible").evaluateAll(elements =>
        elements.map(element => {
          const rect = element.getBoundingClientRect();
          return { label: element.getAttribute("aria-label") || element.textContent?.trim(), width: rect.width, height: rect.height };
        }).filter(size => size.width < 44 || size.height < 44)
      );
      if (undersized.length) throw new Error(`${screen}-${viewport.label}: undersized targets ${JSON.stringify(undersized)}`);
    }
    if (errors.length) throw new Error(`${screen}-${viewport.label}: ${errors.join("; ")}`);
    console.log(`${screen}-${viewport.label}: ${viewport.width}x${viewport.height}, clean console, no overflow${viewport.width < 500 ? ", touch targets ≥44px" : ""}`);
    await page.close();
  }
}

const journey = await browser.newPage({ viewport: { width: 375, height: 812 }, reducedMotion: "reduce" });
const journeyErrors = [];
journey.on("console", message => { if (message.type() === "error") journeyErrors.push(message.text()); });
journey.on("pageerror", error => journeyErrors.push(error.message));
prototypeUrl.search = "?screen=workspace";
await journey.goto(prototypeUrl.href, { waitUntil: "load" });

for (const landmark of ["banner", "main", "navigation"]) {
  if (!(await journey.getByRole(landmark).count())) throw new Error(`Journey: missing ${landmark} landmark`);
}
await journey.getByRole("button", { name: "Brain Dump", exact: true }).click();
if (!(await journey.getByRole("heading", { name: "Tasks from this session" }).isVisible())) throw new Error("Journey: Brain Dump did not open capture");
if ((await journey.getByRole("listitem").count()) !== 4) throw new Error("Journey: capture does not show four proposals");
const captureMainText = await journey.getByRole("main").innerText();
const forbiddenCaptureCopy = /\b(timer|transcript|pipeline|analysis|coaching|recommendation|destination|tree|CRT|weekly review)\b/i;
if (forbiddenCaptureCopy.test(captureMainText)) throw new Error(`Journey: capture exposes forbidden concept: ${captureMainText.match(forbiddenCaptureCopy)?.[0]}`);
if (!/Nothing is saved while you record/.test(captureMainText)) throw new Error("Journey: capture does not state that output is unsaved");
for (let index = 1; index <= 4; index += 1) {
  const card = journey.getByRole("listitem").nth(index - 1);
  for (const marker of [`#${index}`, "Wording still changing", "Provisional"]) {
    if (!(await card.getByText(marker, { exact: true }).isVisible())) throw new Error(`Journey: proposal ${index} missing ${marker}`);
  }
}
await journey.getByRole("button", { name: "Stop & review", exact: true }).click();
if (!(await journey.getByRole("heading", { name: "Review before saving" }).isVisible())) throw new Error("Journey: Stop & review did not open separate review");
if ((await journey.getByRole("textbox").count()) !== 4) throw new Error("Journey: review is not a four-item editor");
await journey.getByRole("textbox").first().fill("Book the dentist for Tuesday at 9");
await journey.getByRole("button", { name: "Remove", exact: true }).nth(1).click();
if ((await journey.getByRole("textbox").count()) !== 3) throw new Error("Journey: remove did not update proposal set");
const confirm = journey.getByRole("button", { name: "Confirm 3 to Inbox", exact: true });
if (!(await confirm.isVisible())) throw new Error("Journey: explicit confirmation action is missing");
await confirm.click();
if (!(await journey.getByRole("heading", { name: "3 tasks added to Inbox" }).isVisible())) throw new Error("Journey: explicit confirmation did not reach result");
await journey.getByRole("button", { name: "Return to Next actions", exact: true }).click();
if (!(await journey.getByRole("heading", { name: "Next actions" }).isVisible())) throw new Error("Journey: completion did not return to workspace");

await journey.getByRole("button", { name: /Fix onboarding drop-off/ }).click();
await journey.getByRole("button", { name: "Open Thinking / CRT", exact: true }).click();
if (!(await journey.getByRole("heading", { name: "Fix onboarding drop-off" }).isVisible())) throw new Error("Journey: task-scoped Thinking did not open");
if (!(await journey.getByText("Thinking / CRT · attached to task", { exact: true }).isVisible())) throw new Error("Journey: Thinking is not visibly task-scoped");

prototypeUrl.search = "?screen=workspace";
await journey.goto(prototypeUrl.href);
await journey.getByRole("button", { name: /Review/ }).last().click();
if (!(await journey.getByRole("heading", { name: /Review your system/ }).isVisible())) throw new Error("Journey: Weekly Review entry did not open");
const weeklyText = await journey.getByRole("main").innerText();
for (const required of ["persisted async-operation contract", "Voice and model stages may propose", "without explicit confirmation"]) {
  if (!weeklyText.includes(required)) throw new Error(`Journey: Weekly Review missing ${required}`);
}
if (journeyErrors.length) throw new Error(`Journey console errors: ${journeyErrors.join("; ")}`);
console.log("click journey: workspace → capture → review/edit/remove → explicit confirm → workspace; task → Thinking; Weekly Review entry passed");

await journey.close();
await browser.close();
