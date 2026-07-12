import { chromium } from "../../../frontend/node_modules/@playwright/test/index.mjs";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const prototypeUrl = new URL(`file://${path.join(here, "prototype.html")}`);
const outputDir = path.join(here, "screenshots");

const states = [
  ["recording", "active"],
  ["review", "review"],
  ["add-text", "add-text"],
  ["saved", "saved"]
];
const captures = states.flatMap(([screen, label], stateIndex) => [
  { name: `${String(stateIndex * 2 + 1).padStart(2, "0")}-brain-dump-${label}-375.png`, screen, width: 375, height: 812 },
  { name: `${String(stateIndex * 2 + 2).padStart(2, "0")}-brain-dump-${label}-430.png`, screen, width: 430, height: 932 }
]);

await mkdir(outputDir, { recursive: true });
const browser = await chromium.launch({ headless: true });

for (const capture of captures) {
  const page = await browser.newPage({
    viewport: { width: capture.width, height: capture.height },
    deviceScaleFactor: 1
  });
  const errors = [];
  page.on("console", message => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", error => errors.push(error.message));

  prototypeUrl.search = `?screen=${capture.screen}`;
  await page.goto(prototypeUrl.href, { waitUntil: "load" });
  await page.screenshot({ path: path.join(outputDir, capture.name), fullPage: false });

  const horizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth
  );
  if (horizontalOverflow) throw new Error(`${capture.name}: horizontal page overflow`);
  if (errors.length) throw new Error(`${capture.name}: ${errors.join("; ")}`);
  console.log(`${capture.name}: ${capture.width}x${capture.height}, no console errors or horizontal overflow`);
  await page.close();
}

const journey = await browser.newPage({ viewport: { width: 375, height: 812 } });
prototypeUrl.search = "?screen=recording";
await journey.goto(prototypeUrl.href);

const forbiddenCopy = /current reality|\bCRT\b|problem analysis|recommend|subtask|complex task|destination|routing|suggested next|task type|promotion/i;
if (await journey.getByText(forbiddenCopy).count()) {
  throw new Error("Brain Dump prototype exposes out-of-scope planning concepts");
}
for (let index = 1; index <= 4; index += 1) {
  const card = journey.getByRole("listitem").nth(index - 1);
  for (const label of [`#${index}`, "Wording still changing", "Provisional"]) {
    if (!(await card.getByText(label, { exact: true }).isVisible())) {
      throw new Error(`Active draft ${index} is missing ${label}`);
    }
  }
}
for (const control of ["Cancel", "Stop", "Review"]) {
  if (!(await journey.getByRole("button", { name: control, exact: true }).isVisible())) {
    throw new Error(`Capture is missing ${control}`);
  }
}

await journey.getByRole("button", { name: "Review", exact: true }).click();
if ((await journey.getByRole("textbox").count()) !== 4) throw new Error("Review is not a plain four-item editor");
for (const outcome of ["Add voice", "Add text", "Save session"]) {
  if (!(await journey.getByRole("button", { name: outcome, exact: true }).isVisible())) {
    throw new Error(`Review is missing ${outcome}`);
  }
}
await journey.getByRole("textbox").first().fill("Call the dentist on Tuesday morning");
await journey.getByRole("button", { name: "Delete", exact: true }).nth(1).click();
if ((await journey.getByRole("textbox").count()) !== 3) throw new Error("Delete did not remove one draft");

await journey.getByRole("button", { name: "Add text", exact: true }).click();
await journey.getByLabel("Task wording").fill("Buy milk on the way home");
await journey.getByRole("button", { name: "Add to session", exact: true }).click();
if ((await journey.getByRole("textbox").count()) !== 4) throw new Error("Text addition did not append one draft");
await journey.getByRole("button", { name: "Add voice", exact: true }).click();
if (!(await journey.getByText("Recording", { exact: true }).isVisible())) throw new Error("Add voice did not return to capture");
await journey.getByRole("button", { name: "Stop", exact: true }).click();
await journey.getByRole("button", { name: "Save session", exact: true }).click();
if (!(await journey.getByRole("heading", { name: "4 tasks sent to RTM Inbox" }).isVisible())) {
  throw new Error("Save session did not reach the RTM Inbox result");
}
if (await journey.getByText(forbiddenCopy).count()) {
  throw new Error("Saved path exposes out-of-scope planning concepts");
}
console.log("click journey: capture → edit/delete → add text → add voice → save to RTM Inbox passed");
await journey.close();
await browser.close();
