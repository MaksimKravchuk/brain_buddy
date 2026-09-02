import { expect, test } from "../allure.fixtures";
import { loginThroughUi, mintInvite, password, signupThroughUi } from "./gtdHelpers";

const operatorEmail = process.env.BRAIN_BUDDY_ADMIN_EMAIL;
const operatorPassword = process.env.BRAIN_BUDDY_ADMIN_PASSWORD ?? password;

type FocusSnapshot = {
  outlineStyle: string;
  outlineWidth: string;
  outlineColor: string;
  outlineOffset: string;
  boxShadow: string;
  forcedColorAdjust: string;
  rect: { x: number; y: number; width: number; height: number };
  viewport: { width: number; height: number };
};

function contrastRatio(first: [number, number, number], second: [number, number, number]): number {
  const relativeLuminance = (rgb: [number, number, number]) =>
    rgb.reduce((sum, channel, index) => {
      const normalized = channel / 255;
      const linear = normalized <= 0.03928 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
      return sum + linear * [0.2126, 0.7152, 0.0722][index];
    }, 0);
  const lighter = Math.max(relativeLuminance(first), relativeLuminance(second));
  const darker = Math.min(relativeLuminance(first), relativeLuminance(second));
  return (lighter + 0.05) / (darker + 0.05);
}

async function assertRenderedFocus(page: import("@playwright/test").Page, forcedColors: boolean): Promise<void> {
  const trigger = page.getByRole("button", { name: /Account menu/ });
  await expect(trigger).toBeVisible();

  await trigger.click();
  await trigger.click();
  const pointerSnapshot = await trigger.evaluate((element) => {
    const style = getComputedStyle(element);
    return { outlineStyle: style.outlineStyle, boxShadow: style.boxShadow };
  });
  expect(pointerSnapshot.outlineStyle).not.toBe("solid");
  expect(pointerSnapshot.boxShadow).not.toContain("#075985");

  await page.getByRole("button", { name: "Brain dump" }).focus();
  const unfocusedClip = await trigger.boundingBox();
  if (!unfocusedClip) throw new Error("account trigger geometry missing before keyboard focus");
  const unfocusedPixels = await page.screenshot({
    clip: { x: unfocusedClip.x - 6, y: unfocusedClip.y - 6, width: unfocusedClip.width + 12, height: unfocusedClip.height + 12 }
  });
  await page.getByRole("button", { name: "Brain dump" }).press("Tab");
  await expect(trigger).toBeFocused();
  const snapshot = await trigger.evaluate((element): FocusSnapshot => {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return {
      outlineStyle: style.outlineStyle,
      outlineWidth: style.outlineWidth,
      outlineColor: style.outlineColor,
      outlineOffset: style.outlineOffset,
      boxShadow: style.boxShadow,
      forcedColorAdjust: style.forcedColorAdjust,
      rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
      viewport: { width: window.innerWidth, height: window.innerHeight },
    };
  });

  expect(snapshot.outlineStyle).toBe("solid");
  expect(parseFloat(snapshot.outlineWidth)).toBeGreaterThanOrEqual(forcedColors ? 2 : 3);
  expect(parseFloat(snapshot.outlineOffset)).toBeGreaterThanOrEqual(3);
  expect(snapshot.rect.width).toBeGreaterThan(0);
  expect(snapshot.rect.height).toBeGreaterThan(0);
  expect(snapshot.rect.x - parseFloat(snapshot.outlineOffset)).toBeGreaterThanOrEqual(0);
  expect(snapshot.rect.y - parseFloat(snapshot.outlineOffset)).toBeGreaterThanOrEqual(0);
  expect(snapshot.rect.x + snapshot.rect.width + parseFloat(snapshot.outlineOffset)).toBeLessThanOrEqual(snapshot.viewport.width);
  expect(snapshot.rect.y + snapshot.rect.height + parseFloat(snapshot.outlineOffset)).toBeLessThanOrEqual(snapshot.viewport.height);
  if (forcedColors) {
    expect(snapshot.outlineColor).not.toBe("transparent");
    expect(snapshot.outlineColor).not.toBe("rgb(7, 89, 133)");
    expect(snapshot.forcedColorAdjust).toBe("auto");
  } else {
    expect(snapshot.outlineColor).toBe("rgb(7, 89, 133)");
    expect(snapshot.boxShadow).not.toContain("7, 89, 133");
  }

  const focusedClip = await trigger.boundingBox();
  if (!focusedClip) throw new Error("account trigger geometry missing after keyboard focus");
  const focusedPixels = await page.screenshot({
    clip: { x: focusedClip.x - 6, y: focusedClip.y - 6, width: focusedClip.width + 12, height: focusedClip.height + 12 }
  });
  expect(focusedPixels).not.toEqual(unfocusedPixels);

  const pixelEvidence = await page.evaluate(() => {
    const element = document.querySelector<HTMLButtonElement>('button[aria-label^="Account menu"]');
    if (!element) throw new Error("account trigger missing");
    const rect = element.getBoundingClientRect();
    const readBackground = (x: number, y: number): string => {
      const adjacent = document.elementFromPoint(x, y);
      return adjacent ? getComputedStyle(adjacent).backgroundColor : "transparent";
    };
    return {
      rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
      above: readBackground(Math.round(rect.x + rect.width / 2), Math.max(0, Math.round(rect.y - 4))),
      below: readBackground(Math.round(rect.x + rect.width / 2), Math.min(window.innerHeight - 1, Math.round(rect.y + rect.height + 4))),
      left: readBackground(Math.max(0, Math.round(rect.x - 4)), Math.round(rect.y + rect.height / 2)),
      right: readBackground(Math.min(window.innerWidth - 1, Math.round(rect.x + rect.width + 4)), Math.round(rect.y + rect.height / 2)),
    };
  });
  const ringColor = forcedColors ? ([0, 0, 0] as [number, number, number]) : ([7, 89, 133] as [number, number, number]);
  const rgb = (value: string): [number, number, number] => {
    const match = value.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/);
    if (!match) throw new Error(`adjacent color was not an RGB value: ${value}`);
    const alpha = match[4] === undefined ? 1 : Number(match[4]);
    return [0, 1, 2].map((index) => Math.round(Number(match[index + 1]) * alpha + 255 * (1 - alpha))) as [number, number, number];
  };
  for (const adjacent of [pixelEvidence.above, pixelEvidence.below, pixelEvidence.left, pixelEvidence.right]) {
    expect(contrastRatio(ringColor, rgb(adjacent)), `adjacent ${adjacent}`).toBeGreaterThanOrEqual(3);
  }
}

test.describe("account trigger rendered keyboard focus", () => {
  test("E2E-SHELL-FOCUS-01 renders focus-visible on the real task inbox account trigger", async ({ page }, testInfo) => {
    const email = `focus-tasks-${testInfo.project.name}-${Date.now()}@example.com`;
    await signupThroughUi(page, email, await mintInvite());
    await page.goto("/tasks/inbox");
    await expect(page.getByRole("heading", { name: "Inbox" })).toBeVisible();
    await test.step("verify keyboard and pointer rendered focus states", async () => {
      await assertRenderedFocus(page, false);
    });
  });

  test("E2E-SHELL-FOCUS-02 renders an explicit forced-colors indicator on the real task inbox trigger", async ({ page }, testInfo) => {
    const email = `focus-forced-colors-${testInfo.project.name}-${Date.now()}@example.com`;
    const browser = page.context().browser();
    if (!browser) throw new Error("Chromium browser is required for forced-colors rendering");
    const forcedContext = await browser.newContext({
      baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:5173",
      forcedColors: "active",
    });
    const forcedPage = await forcedContext.newPage();
    try {
      await signupThroughUi(forcedPage, email, await mintInvite());
      await forcedPage.goto("/tasks/inbox");
      await expect(forcedPage.getByRole("heading", { name: "Inbox" })).toBeVisible();
      await test.step("verify the Chromium forced-colors rendering contract", async () => {
        await assertRenderedFocus(forcedPage, true);
      });
    } finally {
      await forcedContext.close();
    }
  });

  test("E2E-SHELL-FOCUS-03 covers the configured operator account trigger on admin", async ({ page }) => {
    test.skip(!operatorEmail, "BRAIN_BUDDY_ADMIN_EMAIL is required for the configured-operator route");
    if (!operatorEmail) return;
    await page.goto("/login");
    await page.getByLabel("Email").fill(operatorEmail);
    await page.getByLabel("Password").fill(operatorPassword);
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.goto("/admin");
    await expect(page.getByRole("heading", { name: /Users|Admin/ }).first()).toBeVisible();
    await test.step("verify the same real AppShell trigger on admin", async () => {
      await assertRenderedFocus(page, false);
    });
  });
});
