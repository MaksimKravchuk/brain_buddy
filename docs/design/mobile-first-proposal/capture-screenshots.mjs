import { chromium } from "../../../frontend/node_modules/@playwright/test/index.mjs";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const prototypeUrl = new URL(`file://${path.join(here, "prototype.html")}`);
const outputDir = path.join(here, "screenshots");

const captures = [
  { name: "01-brain-dump-active-375.png", screen: "recording", width: 375, height: 812 },
  { name: "02-brain-dump-active-430.png", screen: "recording", width: 430, height: 932 },
  { name: "03-brain-dump-paused-375.png", screen: "paused", width: 375, height: 812 },
  { name: "08-brain-dump-finished-430.png", screen: "finished", width: 430, height: 932 },
  { name: "04-weekly-review-queue-375.png", screen: "weekly-queue", width: 375, height: 812 },
  { name: "05-weekly-review-crt-promotion-430.png", screen: "weekly-detail", width: 430, height: 932 },
  { name: "06-crt-focused-tree-430.png", screen: "crt", width: 430, height: 932 },
  { name: "07-desktop-brain-dump-1440.png", screen: "desktop", width: 1440, height: 960 }
];

await mkdir(outputDir, { recursive: true });
const browser = await chromium.launch({ headless: true });

for (const capture of captures) {
  const page = await browser.newPage({
    viewport: { width: capture.width, height: capture.height },
    deviceScaleFactor: 1
  });
  const errors = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));

  prototypeUrl.search = `?screen=${capture.screen}`;
  await page.goto(prototypeUrl.href, { waitUntil: "load" });
  await page.screenshot({ path: path.join(outputDir, capture.name), fullPage: false });

  const horizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth
  );
  if (horizontalOverflow) {
    throw new Error(`${capture.name}: horizontal page overflow`);
  }
  if (errors.length) {
    throw new Error(`${capture.name}: ${errors.join("; ")}`);
  }
  console.log(`${capture.name}: ${capture.width}x${capture.height}, no console errors or horizontal overflow`);
  await page.close();
}

// Exercise the critical clickable path and focus semantics, not only screenshot routes.
const journey = await browser.newPage({ viewport: { width: 375, height: 812 } });
prototypeUrl.search = "?screen=idle";
await journey.goto(prototypeUrl.href);
const emptyListVisible = await journey
  .getByRole("heading", { name: "Your task list will grow here" })
  .isVisible();
if (!emptyListVisible) throw new Error("Brain Dump empty-list state is missing");
await journey.getByRole("button", { name: "Start recording" }).click();
const activeTasks = await journey.getByRole("listitem").count();
if (activeTasks !== 4) throw new Error(`Expected 4 active session tasks, found ${activeTasks}`);
const forbiddenActiveCopy = await journey
  .getByText(/live transcript|chunks uploaded|routing|CRT promotion/i)
  .count();
if (forbiddenActiveCopy) throw new Error("Active capture exposes transcript or pipeline UI");
await journey.getByRole("button", { name: "Pause" }).click();
if (!(await journey.getByText("Paused · 4 tasks").isVisible())) {
  throw new Error("Paused state is not exposed as text");
}
await journey.getByRole("button", { name: "Resume" }).click();
await journey.getByRole("button", { name: "Finish" }).click();
await journey.getByRole("button", { name: "Review tasks" }).click();
await journey.getByRole("button", { name: "Review 3 actions" }).click();
await journey.getByRole("button", { name: "Confirm selected" }).click();
const finalHeading = await journey.getByRole("heading", { name: "3 of 4 actions completed" }).isVisible();
if (!finalHeading) throw new Error("Critical Brain Dump journey did not reach partial-result state");
console.log("click journey: empty session → recording → paused → resumed → finished → review → result passed");
await journey.close();

const reviewJourney = await browser.newPage({ viewport: { width: 430, height: 932 } });
prototypeUrl.search = "?screen=weekly-queue";
await reviewJourney.goto(prototypeUrl.href);
await reviewJourney.getByRole("button", { name: "Review next item" }).click();
await reviewJourney.getByRole("button", { name: "Promote to CRT", exact: true }).click();
const treeHeading = await reviewJourney
  .getByRole("heading", { name: "Release quality", exact: true })
  .isVisible();
if (!treeHeading) throw new Error("Weekly Review journey did not reach CRT promotion preview");
console.log("click journey: Weekly Review queue → item detail → CRT promotion preview passed");
await reviewJourney.close();

await browser.close();
