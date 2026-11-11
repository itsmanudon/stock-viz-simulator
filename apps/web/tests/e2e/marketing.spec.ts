import { expect, test } from "@playwright/test";

/**
 * Marketing home coverage.
 *
 * The public page is driven by live API data (hero panel and phone, movers,
 * rankings), so these specs assert on structure and behaviour rather than on
 * any particular price — a reseeded database must not turn the suite red.
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

  test("hero phone screens can be switched with the dots", async ({ page }) => {
    // With motion, scrolling the dots into view starts the pinned hero, whose
    // panel covers the phone mid-animation by design; on a slow runner the
    // click raced it and timed out (PR #94). The dots are the same control
    // without motion, so check them where the hero does not pin.
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.reload();
    const dots = page.getByRole("button", { name: /^Show the .* screen$/ });
    if ((await dots.count()) < 2) test.skip(true, "Only one phone screen without stored bars");
    await dots.nth(1).click();
    await expect(dots.nth(1)).toHaveAttribute("aria-pressed", "true");
  });

  test("movers link each card to its stock page", async ({ page }) => {
    const research = page.getByRole("link", { name: /^Research / });
    await expect(research.first()).toHaveAttribute("href", /\/stocks\//);
  });

  test("FAQ answers open and close", async ({ page }) => {
    const question = page.getByText("Where do the prices come from?");
    const details = page.locator("details", { has: question });
    await expect(details).not.toHaveAttribute("open", "");
    await question.click();
    await expect(details).toHaveAttribute("open", "");
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

test("on a phone the paper-trading copy is one plain section", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  // The pinned version lives in the hero on wide screens; here it must appear
  // once, as a section, and nothing pins.
  const heading = page.getByRole("heading", { name: /A broker is real money/ });
  await expect(heading).toHaveCount(1);
  await expect(heading).toBeVisible();
  expect(await page.locator(".pin-spacer").count()).toBe(0);
});

test.describe("reduced motion", () => {
  test("no animation runs and no content is gated behind scrolling", async ({ page }) => {
    // `emulateMedia` rather than the `reducedMotion` fixture: the fixture did
    // not reach the page here (`matchMedia(...).matches` stayed false), which
    // silently turns this into a test of the default state.
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");

    expect(
      await page.evaluate(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches),
    ).toBe(true);

    // Nothing pins, and the paper-trading copy is a plain visible section.
    expect(await page.locator(".pin-spacer").count()).toBe(0);
    await expect(page.getByRole("heading", { name: /A broker is real money/ })).toBeVisible();

    // Reveal resolves as soon as it hydrates instead of waiting for an
    // intersection. Auto-waiting: the server HTML is "pending" until then, and
    // a one-shot count raced hydration once the page got lighter.
    await expect(page.locator('[data-reveal="pending"]')).toHaveCount(0);
    for (const section of await page.locator("[data-reveal]").all()) {
      await expect(section).toHaveCSS("transition-delay", "0s");
      await expect(section).toHaveCSS("opacity", "1");
    }

    // Every "fill shows its work" step is lit, and every movers card and
    // heading is at full strength without scrolling.
    for (const step of await page.locator("[data-step]").all()) {
      await expect(step).toHaveAttribute("data-on", "true");
    }
    for (const item of await page.locator("[data-motion-item]").all()) {
      await expect(item).toHaveCSS("opacity", "1");
    }

    // The hero phone must not change screen on its own.
    const label = page.locator("[aria-live=polite]").first();
    const before = await label.textContent();
    await page.waitForTimeout(6000);
    expect(await label.textContent()).toBe(before);
  });
});

test.describe("themes", () => {
  // next-themes runs with `defaultTheme="dark"` and `enableSystem={false}`, so
  // the theme comes from localStorage rather than a media query.
  //
  // `.panel-inset` follows the theme: a white panel in light mode, and the
  // Aurora navy marketing panel (`--marketing-panel: #0b101b`) in dark mode.
  const PANEL_BG = {
    light: "rgb(255, 255, 255)",
    dark: "rgb(11, 16, 27)",
  } as const;

  for (const theme of ["light", "dark"] as const) {
    test(`${theme} mode grounds the product panel in the theme palette`, async ({ page }) => {
      await page.addInitScript((value) => {
        window.localStorage.setItem("theme", value);
      }, theme);
      await page.goto("/");

      await expect(page.locator("html")).toHaveClass(
        new RegExp(theme === "dark" ? "dark" : "^(?!.*\\bdark\\b).*$"),
      );

      const panel = await page.evaluate(() => {
        const el = document.querySelector(".panel-inset") as HTMLElement;
        return getComputedStyle(el).backgroundColor;
      });
      expect(panel).toBe(PANEL_BG[theme]);

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

test.describe("product pages", () => {
  for (const [slug, name, heading] of [
    ["paper-trading", "Paper trading", /Trade the market/],
    ["research", "Research", /Find it, test it/],
    ["replay", "Replay", /Trade a past stretch/],
  ] as const) {
    test(`${name} has its own title and fits a phone and a desktop`, async ({ page }) => {
      for (const width of [320, 1440]) {
        await page.setViewportSize({ width, height: 900 });
        await page.goto(`/product/${slug}`);
        await expect(page).toHaveTitle(`${name} | StockViz`);
        await expect(page.getByRole("heading", { level: 1 })).toContainText(heading);
        const overflows = await page.evaluate(
          () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
        );
        expect(overflows).toBe(false);
      }
    });
  }

  test("the header links the product pages", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto("/");
    const nav = page.getByRole("navigation", { name: "Public" });
    await nav.getByRole("link", { name: "Replay" }).click();
    await expect(page).toHaveURL(/\/product\/replay$/);
  });

  test("news has no product page until the Aegis feed lands", async ({ page }) => {
    const response = await page.goto("/product/news");
    expect(response?.status()).toBe(404);
  });
});

test.describe("sign-in pages and leaderboard", () => {
  for (const [path, heading] of [
    ["/login", "Sign in"],
    ["/signup", "Create your account"],
    ["/sign-in-required", "Sign in required"],
  ] as const) {
    test(`${path} has one top-level heading (audit A2)`, async ({ page }) => {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(heading);
    });
  }

  test("on a phone the sign-in form comes before the pitch (audit P2)", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/login");
    const email = await page.getByLabel("Email").boundingBox();
    const pitch = await page
      .getByRole("heading", { name: "A trading workspace where mistakes are free" })
      .boundingBox();
    expect(email && pitch && email.y < pitch.y).toBe(true);
    // The field is on the first screen, not half a screen down.
    expect(email && email.y < 844).toBe(true);
  });

  test("the leaderboard puts its top three on a podium", async ({ page }) => {
    await page.goto("/leaderboard");
    const podium = page.getByRole("list", { name: "Top three traders" });
    if ((await podium.count()) === 0) test.skip(true, "Fewer than three public profiles");
    await expect(podium.getByRole("listitem")).toHaveCount(3);
  });
});
