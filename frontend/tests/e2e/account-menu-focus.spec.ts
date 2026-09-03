import assert from "node:assert/strict";

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

function rgb(value: string): [number, number, number] {
  const match = value.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/);
  if (!match) throw new Error(`rendered color was not an RGB value: ${value}`);
  const alpha = match[4] === undefined ? 1 : Number(match[4]);
  if (!Number.isFinite(alpha) || alpha <= 0) throw new Error(`rendered color was transparent: ${value}`);
  return [0, 1, 2].map((index) => Math.round(Number(match[index + 1]) * alpha + 255 * (1 - alpha))) as [number, number, number];
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
  assert.notEqual(pointerSnapshot.outlineStyle, "solid", "pointer focus must not render the keyboard outline");
  assert(!pointerSnapshot.boxShadow.includes("#075985"), "pointer focus must not render the keyboard focus color");

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

  assert.equal(snapshot.outlineStyle, "solid", "keyboard focus must render a solid outline");
  assert(parseFloat(snapshot.outlineWidth) >= (forcedColors ? 2 : 3), "keyboard outline must meet the minimum width");
  assert(parseFloat(snapshot.outlineOffset) >= 3, "keyboard outline must remain visually separated from the trigger");
  assert(snapshot.rect.width > 0, "account trigger must have rendered width");
  assert(snapshot.rect.height > 0, "account trigger must have rendered height");
  assert(snapshot.rect.x - parseFloat(snapshot.outlineOffset) >= 0, "focus outline must remain inside the left viewport edge");
  assert(snapshot.rect.y - parseFloat(snapshot.outlineOffset) >= 0, "focus outline must remain inside the top viewport edge");
  assert(
    snapshot.rect.x + snapshot.rect.width + parseFloat(snapshot.outlineOffset) <= snapshot.viewport.width,
    "focus outline must remain inside the right viewport edge"
  );
  assert(
    snapshot.rect.y + snapshot.rect.height + parseFloat(snapshot.outlineOffset) <= snapshot.viewport.height,
    "focus outline must remain inside the bottom viewport edge"
  );
  if (forcedColors) {
    assert.notEqual(snapshot.outlineColor, "transparent", "forced-colors outline must be visible");
    assert.notEqual(snapshot.outlineColor, "rgb(7, 89, 133)", "forced-colors outline must use the system color");
    assert.equal(snapshot.forcedColorAdjust, "auto", "forced-colors rendering must remain under browser control");

    const forcedFocusRule = await page.evaluate(() => {
      const findForcedColorRule = (rules: CSSRuleList): CSSStyleDeclaration | null => {
        for (const rule of Array.from(rules)) {
          if (rule instanceof CSSStyleRule && rule.selectorText === ".account-menu-trigger:focus-visible") {
            return rule.style;
          }
        }
        return null;
      };

      for (const sheet of Array.from(document.styleSheets)) {
        for (const rule of Array.from(sheet.cssRules)) {
          if (rule instanceof CSSMediaRule && rule.conditionText.includes("forced-colors")) {
            const style = findForcedColorRule(rule.cssRules);
            if (style) {
              return {
                outlineStyle: style.getPropertyValue("outline-style"),
                outlineWidth: style.getPropertyValue("outline-width"),
                outlineColor: style.getPropertyValue("outline-color"),
              };
            }
          }
        }
      }
      return null;
    });
    assert(forcedFocusRule, "forced-colors stylesheet focus rule must be present");
    assert.equal(forcedFocusRule.outlineStyle, "solid", "forced-colors stylesheet must define a solid focus outline");
    assert.equal(forcedFocusRule.outlineWidth, "2px", "forced-colors stylesheet must define a 2px focus outline");
    assert.notEqual(forcedFocusRule.outlineColor, "", "forced-colors stylesheet must define a focus color");
    assert.notEqual(forcedFocusRule.outlineColor, "#075985", "forced-colors stylesheet must not use the normal focus color");
  } else {
    assert.equal(snapshot.outlineColor, "rgb(7, 89, 133)", "normal focus must render the design-token outline color");
    assert(!snapshot.boxShadow.includes("7, 89, 133"), "normal focus evidence must come from the outline, not a shadow");
  }

  const focusedClip = await trigger.boundingBox();
  if (!focusedClip) throw new Error("account trigger geometry missing after keyboard focus");
  const focusedPixels = await page.screenshot({
    clip: { x: focusedClip.x - 6, y: focusedClip.y - 6, width: focusedClip.width + 12, height: focusedClip.height + 12 }
  });
  assert.notDeepEqual(focusedPixels, unfocusedPixels, "focused and unfocused trigger pixels must differ");

  const pixelEvidence = await page.evaluate(() => {
    const element = document.querySelector<HTMLButtonElement>('button[aria-label^="Account menu"]');
    if (!element) throw new Error("account trigger missing");
    const rect = element.getBoundingClientRect();
    const readBackground = (x: number, y: number): string => {
      let adjacent = document.elementFromPoint(x, y);
      while (adjacent) {
        const background = getComputedStyle(adjacent).backgroundColor;
        const alpha = background.match(/rgba?\(\d+,\s*\d+,\s*\d+(?:,\s*([\d.]+))?\)/)?.[1];
        if (alpha === undefined || Number(alpha) > 0) return background;
        adjacent = adjacent.parentElement;
      }
      throw new Error(`no opaque rendered background at ${x},${y}`);
    };
    return {
      rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
      above: readBackground(Math.round(rect.x + rect.width / 2), Math.max(0, Math.round(rect.y - 4))),
      below: readBackground(Math.round(rect.x + rect.width / 2), Math.min(window.innerHeight - 1, Math.round(rect.y + rect.height + 4))),
      left: readBackground(Math.max(0, Math.round(rect.x - 4)), Math.round(rect.y + rect.height / 2)),
      right: readBackground(Math.min(window.innerWidth - 1, Math.round(rect.x + rect.width + 4)), Math.round(rect.y + rect.height / 2)),
    };
  });
  const ringColor = forcedColors ? rgb(snapshot.outlineColor) : ([7, 89, 133] as [number, number, number]);
  for (const adjacent of [pixelEvidence.above, pixelEvidence.below, pixelEvidence.left, pixelEvidence.right]) {
    assert(contrastRatio(ringColor, rgb(adjacent)) >= 3, `focus outline must have at least 3:1 contrast against ${adjacent}`);
  }
}

async function assertAccountMenuJourney(page: import("@playwright/test").Page): Promise<void> {
  const trigger = page.getByRole("button", { name: /Account menu/ });
  const menu = page.getByRole("menu", { name: "Account" });
  const accountSettings = page.getByRole("menuitem", { name: "Account settings" });
  const connectedAgents = page.getByRole("menuitem", { name: "Connected agents" });

  await expect(trigger).toBeFocused();
  await trigger.press("Enter");
  await expect(menu).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(accountSettings).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(connectedAgents).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(accountSettings).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();
  await expect(trigger).toBeFocused();

  await trigger.press("Space");
  await expect(menu).toBeVisible();
  await page.locator("main").click({ position: { x: 4, y: 4 } });
  await expect(menu).toBeHidden();
}

test.describe("account trigger rendered keyboard focus", () => {
  test("E2E-SHELL-FOCUS-01 renders focus-visible on the real task inbox account trigger", async ({ page }, testInfo) => {
    const email = `focus-tasks-${testInfo.project.name}-${Date.now()}@example.com`;
    await signupThroughUi(page, email, await mintInvite());
    await page.goto("/tasks/inbox");
    await expect(page.getByRole("heading", { name: "Inbox" })).toBeVisible();
    await test.step("verify keyboard and pointer rendered focus states", async () => {
      await assertRenderedFocus(page, false);
      await page.screenshot({ path: testInfo.outputPath("tasks-normal-focus.png") });
      await assertAccountMenuJourney(page);
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
        await forcedPage.screenshot({ path: testInfo.outputPath("tasks-forced-colors-focus.png") });
        await assertAccountMenuJourney(forcedPage);
      });
    } finally {
      await forcedContext.close();
    }
  });

  test("E2E-SHELL-FOCUS-03 covers the configured operator account trigger on admin", async ({ page }, testInfo) => {
    test.skip(!operatorEmail, "BRAIN_BUDDY_ADMIN_EMAIL is required for the configured-operator route");
    if (!operatorEmail) return;
    await loginThroughUi(page, operatorEmail, operatorPassword);
    await page.goto("/admin");
    await expect(page.getByRole("heading", { name: /Users|Admin/ }).first()).toBeVisible();
    await test.step("verify the same real AppShell trigger on admin", async () => {
      await assertRenderedFocus(page, false);
      await page.screenshot({ path: testInfo.outputPath("admin-normal-focus.png") });
      await assertAccountMenuJourney(page);
    });
  });

  test("E2E-SHELL-FOCUS-04 covers the configured operator account trigger on admin in forced colors", async ({ page }, testInfo) => {
    test.skip(!operatorEmail, "BRAIN_BUDDY_ADMIN_EMAIL is required for the configured-operator route");
    if (!operatorEmail) return;
    const browser = page.context().browser();
    if (!browser) throw new Error("Chromium browser is required for forced-colors rendering");
    const forcedContext = await browser.newContext({
      baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:5173",
      forcedColors: "active",
    });
    const forcedPage = await forcedContext.newPage();
    try {
      await loginThroughUi(forcedPage, operatorEmail, operatorPassword);
      await forcedPage.goto("/admin");
      await expect(forcedPage.getByRole("heading", { name: /Users|Admin/ }).first()).toBeVisible();
      await assertRenderedFocus(forcedPage, true);
      await forcedPage.screenshot({ path: testInfo.outputPath("admin-forced-colors-focus.png") });
      await assertAccountMenuJourney(forcedPage);
    } finally {
      await forcedContext.close();
    }
  });
});
