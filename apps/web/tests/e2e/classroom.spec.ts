import { expect, test } from "@playwright/test";

// A10.2 (M12.1): the classroom is signed-in only.
test("the classroom asks guests to sign in", async ({ page }) => {
  await page.goto("/classroom");
  await expect(page).toHaveURL(/sign-in-required/);
});
