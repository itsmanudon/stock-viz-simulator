import { expect, test } from "@playwright/test";

/**
 * Marketing home coverage.
 *
 * The public page is now driven by live API data (hero panel, ticker strip,
 * product tour, numbers band), so these specs assert on structure and
 * behaviour rather than on any particular price — a reseeded database must not
 * turn the suite red.
 */

test.describe("marketing home", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("hero leads with the product and its constraints", async ({ page }) => {
    await expect(page.getByRole("heading", { level: 1 })).toContainText(
      "Learn the market without risking the money",
    );
    await expect(page.getByRole("link", { name: "Create free account" }).first()).toBeVisible();
    await expect(page.getByRole("link", { name: "Explore markets" })).toBeVisible();

    // The constraints are part of the hero, not buried in the footer.
    await expect(page.getByText("Simulated fills · EOD data")).toBeVisible();
    await expect(page.getByText("No card required")).toBeVisible();
  });

  test("ticker strip renders symbols as links", async ({ page }) => {
    const strip = page.locator(".marquee");
    await expect(strip).toBeVisible();
    // Two halves are rendered for a seamless wrap; the duplicate is aria-hidden
    // so only one set is exposed to assistive tech.
    await expect(strip.locator("a").first()).toHaveAttribute("href", /\/stocks\//);
  });

  test("product tour switches panels by click and arrow key", async ({ page }) => {
    const tablist = page.getByRole("tablist", { name: "Product tour" });
    await expect(tablist).toBeVisible();

    const tabs = tablist.getByRole("tab");
    await expect(tabs.first()).toBeVisible();

    // Clicking a tab selects it and reveals exactly one panel.
    await tabs.first().click();
    await expect(tabs.first()).toHaveAttribute("aria-selected", "true");
    await expect(page.getByRole("tabpanel")).toHaveCount(1);

    // Roving focus: arrow keys move selection and focus together.
    const count = await tabs.count();
    if (count > 1) {
      await tabs.first().press("ArrowRight");
      await expect(tabs.nth(1)).toHaveAttribute("aria-selected", "true");
      await expect(tabs.nth(1)).toBeFocused();
    }
  });

  test("footer states the disclosures as numbered notes", async ({ page }) => {
    const footer = page.getByRole("contentinfo");
    await expect(footer).toBeVisible();

    await expect(footer.getByRole("navigation", { name: "Research" })).toBeVisible();
    await expect(footer.getByRole("navigation", { name: "Project" })).toBeVisible();
    await expect(footer.getByText(/Simulated trading only/)).toBeVisible();
    await expect(footer.getByText(/Not investment advice/)).toBeVisible();
  });
});

test.describe("reduced motion", () => {
  test("no animation runs and no content is gated behind scrolling", async ({ page }) => {
    // `emulateMedia` rather than the `reducedMotion` fixture: the fixture did
    // not reach the page here (`matchMedia(...).matches` stayed false), which
    // silently turns this into a test of the default state.
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");

    expect(
      await page.evaluate(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches),
    ).toBe(true);

    // The ticker must not animate — the stylesheet drops it by name rather than
    // collapsing its duration, which would snap the track to its wrapped
    // position and leave the aria-hidden duplicate on screen.
    const animation = await page
      .locator(".marquee-track")
      .evaluate((el) => getComputedStyle(el).animationName);
    expect(animation).toBe("none");

    // Reveal resolves immediately instead of waiting for an intersection.
    const pending = await page.locator('[data-reveal="pending"]').count();
    expect(pending).toBe(0);

    // The tour must not advance on its own.
    const tabs = page.getByRole("tablist", { name: "Product tour" }).getByRole("tab");
    const selectedBefore = await tabs.first().getAttribute("aria-selected");
    await page.waitForTimeout(7000);
    expect(await tabs.first().getAttribute("aria-selected")).toBe(selectedBefore);
  });
});

test.describe("themes", () => {
  // next-themes runs with `defaultTheme="dark"` and `enableSystem={false}`, so
  // the theme comes from localStorage rather than a media query.
  for (const theme of ["light", "dark"] as const) {
    test(`${theme} mode keeps the product panel dark`, async ({ page }) => {
      await page.addInitScript((value) => {
        window.localStorage.setItem("theme", value);
      }, theme);
      await page.goto("/");

      await expect(page.locator("html")).toHaveClass(
        new RegExp(theme === "dark" ? "dark" : "^(?!.*\\bdark\\b).*$"),
      );

      const shades = await page.evaluate(() => {
        const panel = document.querySelector(".panel-inset") as HTMLElement;
        return {
          body: getComputedStyle(document.body).backgroundColor,
          panel: getComputedStyle(panel).backgroundColor,
        };
      });

      // The whole point of `.panel-inset`: it is the same dark ground in both
      // themes, which is where light mode gets its contrast from.
      expect(shades.panel).toBe("rgb(27, 30, 32)");
      if (theme === "light") {
        expect(shades.body).not.toBe(shades.panel);
      }

      const overflows = await page.evaluate(
        () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
      );
      expect(overflows).toBe(false);
    });
  }
});

test.describe("responsive", () => {
  // 1024-1366 matters as much as the round numbers: the hero panel is cropped
  // with a negative right margin from `lg` up, and an earlier 320/768/1440
  // sample stepped straight over a horizontal scrollbar across that whole band.
  for (const [label, width] of [
    ["small phone", 320],
    ["tablet", 768],
    ["small laptop", 1024],
    ["laptop", 1280],
    ["laptop wide", 1366],
    ["desktop", 1440],
  ] as const) {
    test(`${label} (${width}px) never scrolls horizontally`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/");

      // Full-bleed sections and the oversized display type are the things most
      // likely to push the document wider than the viewport.
      const overflows = await page.evaluate(
        () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
      );
      expect(overflows).toBe(false);

      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expect(page.getByRole("contentinfo")).toBeVisible();
    });
  }
});
