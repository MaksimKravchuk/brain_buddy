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

const forbiddenCopy = /add by text|add text|type one|task label|problem label|current reality|\bCRT\b|planning|recommend|subtask|analysis|suggested next|task type/i;
const bodyCopy = await journey.locator("body").innerText();
if (forbiddenCopy.test(bodyCopy)) throw new Error("Capture exposes forbidden copy");
if ((await journey.getByRole("textbox").count()) !== 0) throw new Error("Capture exposes a text input");
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
if ((await journey.getByRole("textbox").count()) !== 4) throw new Error("Review is not a four-draft inline editor");
for (const outcome of ["Return to voice capture", "Save session"]) {
  if (!(await journey.getByRole("button", { name: outcome, exact: true }).isVisible())) {
    throw new Error(`Review is missing ${outcome}`);
  }
}
if (forbiddenCopy.test(await journey.locator("body").innerText())) throw new Error("Review exposes forbidden copy");
await journey.getByRole("textbox").first().fill("Call the dentist on Tuesday morning");
await journey.getByRole("button", { name: "Delete", exact: true }).nth(1).click();
if ((await journey.getByRole("textbox").count()) !== 3) throw new Error("Delete did not remove one draft");
await journey.getByRole("button", { name: "Return to voice capture", exact: true }).click();
if (!(await journey.getByText("Listening", { exact: true }).isVisible())) throw new Error("Return did not reopen voice capture");
if ((await journey.getByRole("textbox").count()) !== 0) throw new Error("Voice capture exposes a text input after return");
await journey.getByRole("button", { name: "Stop", exact: true }).click();
await journey.getByRole("button", { name: "Save session", exact: true }).click();
if (!(await journey.getByRole("heading", { name: "3 drafts sent to RTM Inbox" }).isVisible())) {
  throw new Error("Save session did not reach the RTM Inbox result");
}
if (forbiddenCopy.test(await journey.locator("body").innerText())) throw new Error("Saved result exposes forbidden copy");
console.log("click journey: voice capture → inline edit/delete → voice capture → save to RTM Inbox passed");
await journey.close();
await browser.close();
