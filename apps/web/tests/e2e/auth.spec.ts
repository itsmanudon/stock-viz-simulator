import { expect, test } from "@playwright/test";

test("sign up creates an account and starts the session", async ({ page }) => {
  const email = `e2e+${Date.now()}@example.com`;

  await page.goto("/signup");
  await page.getByLabel("Name").fill("E2E Tester");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("testpassword1");
  await page.getByRole("button", { name: "Sign up" }).click();

  // signupAction redirects to "/" after signing in
  await page.waitForURL("/");

  // Navigating to /portfolio works — the page auto-creates the $100k portfolio
  await page.goto("/portfolio");
  await expect(page.getByText("$100,000.00")).toBeVisible({ timeout: 10_000 });
});

test("protected route redirects unauthenticated users to sign-in page", async ({ page }) => {
  await page.goto("/portfolio");
  await expect(page).toHaveURL(/sign-in-required/);
});
