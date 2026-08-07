import { expect, test } from "../allure.fixtures";

import { mintInvite, password, signupThroughUi, uniqueEmail } from "./gtdHelpers";

const newPassword = "E2E-rotated-password-456";

async function openAccountSettings(page: import("@playwright/test").Page, email: string): Promise<void> {
  await page.getByRole("button", { name: `Account menu for ${email}` }).click();
  await page.getByRole("menuitem", { name: "Account settings" }).click();
  await expect(page.getByRole("heading", { name: "Account settings" })).toBeVisible();
}

function sectionByHeading(page: import("@playwright/test").Page, name: string) {
  return page.locator("section").filter({ has: page.getByRole("heading", { name, exact: true }) });
}

test.describe("account & data rights acceptance", () => {
  test("E2E-ACCT-01 profile rename, password rotation, and the new sign-out control", async ({ page }, testInfo) => {
    const email = uniqueEmail("account-profile", testInfo);
    await signupThroughUi(page, email, await mintInvite());

    await test.step("set a display name from account settings", async () => {
      await openAccountSettings(page, email);
      const profile = sectionByHeading(page, "Profile");
      await profile.getByLabel("Display name").fill("E2E Tester");
      await profile.getByRole("button", { name: "Save profile" }).click();
      await expect(profile.getByText("Profile saved.")).toBeVisible();
    });

    await test.step("rotate the password with re-authentication", async () => {
      const section = sectionByHeading(page, "Password");
      await section.getByLabel("Current password", { exact: true }).fill(password);
      await section.getByLabel("New password", { exact: true }).fill(newPassword);
      await section.getByLabel("Confirm new password").fill(newPassword);
      await section.getByRole("button", { name: "Change password" }).click();
      await expect(section.getByText(/other devices have been signed out/i)).toBeVisible();
    });

    await test.step("sign out through the account menu", async () => {
      await page.getByRole("button", { name: `Account menu for ${email}` }).click();
      await page.getByRole("menuitem", { name: "Sign out" }).click();
      await expect(page).toHaveURL(/\/login$/);
    });

    await test.step("sign back in with the rotated password", async () => {
      await page.getByLabel("Email").fill(email);
      await page.getByLabel("Password").fill(newPassword);
      await page.getByRole("button", { name: "Sign in" }).click();
      await expect(page.getByRole("heading", { name: "Next actions" })).toBeVisible();
    });
  });

  test("E2E-ACCT-02 data export downloads the GDPR archive", async ({ page }, testInfo) => {
    const email = uniqueEmail("account-export", testInfo);
    await signupThroughUi(page, email, await mintInvite());
    await openAccountSettings(page, email);

    await test.step("download the export archive", async () => {
      const downloadPromise = page.waitForEvent("download");
      await page.getByRole("button", { name: /download my data/i }).click();
      const download = await downloadPromise;
      // A bare sync expect records a zero-duration Allure step with no
      // evidence, which the taxonomy validator rejects; attach the actual
      // filename as evidence and assert with an explicit throw instead.
      const filename = download.suggestedFilename();
      await testInfo.attach("export-filename", { body: filename, contentType: "text/plain" });
      if (!/^brain-buddy-export-.+\.zip$/.test(filename)) {
        throw new Error(`Unexpected export filename: ${filename}`);
      }
      await expect(page.getByText(/download started/i)).toBeVisible();
    });
  });

  test("E2E-ACCT-03 deletion request explains the grace period and a login cancels it", async ({ page }, testInfo) => {
    const email = uniqueEmail("account-delete", testInfo);
    await signupThroughUi(page, email, await mintInvite());
    await openAccountSettings(page, email);

    await test.step("request deletion through the confirmation dialog", async () => {
      await sectionByHeading(page, "Danger zone").getByRole("button", { name: /delete account/i }).click();
      const dialog = page.getByRole("dialog");
      await expect(dialog.getByRole("heading", { name: "Delete your account?" })).toBeVisible();
      await dialog.getByLabel("Confirm with your password").fill(password);
      await dialog.getByRole("button", { name: "Delete my account" }).click();
    });

    await test.step("land on login with the scheduled purge notice", async () => {
      await expect(page).toHaveURL(/\/login$/);
      await expect(page.getByRole("status")).toContainText(/permanently deleted on/i);
    });

    await test.step("logging back in cancels the deletion", async () => {
      await page.getByLabel("Email").fill(email);
      await page.getByLabel("Password").fill(password);
      await page.getByRole("button", { name: "Sign in" }).click();
      await expect(page.getByText(/scheduled account deletion has been cancelled/i)).toBeVisible();
      await page.getByRole("button", { name: "Dismiss deletion notice" }).click();
      await expect(page.getByText(/scheduled account deletion has been cancelled/i)).toHaveCount(0);
    });
  });

  test("E2E-ACCT-04 privacy policy is reachable without an account", async ({ page }) => {
    await test.step("open /privacy signed out", async () => {
      await page.goto("/privacy");
      await expect(page).toHaveURL(/\/privacy$/);
      await expect(page.getByRole("heading", { name: "Privacy policy" })).toBeVisible();
      await expect(page.getByText("brainbuddy_session")).toBeVisible();
    });
    await test.step("the login page links to it", async () => {
      await page.goto("/login");
      await page.getByRole("link", { name: "Privacy policy" }).click();
      await expect(page).toHaveURL(/\/privacy$/);
    });
  });
});
