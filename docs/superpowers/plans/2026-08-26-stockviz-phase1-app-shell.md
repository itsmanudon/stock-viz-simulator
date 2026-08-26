# StockViz Phase 1 Application Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a responsive public/product layout split and calm financial-workstation shell without redesigning existing product pages.

**Architecture:** Keep the root layout limited to document-level providers and the global skip link. Route-group layouts own either the public website shell or the guest-capable product shell, while the existing URL-based authentication boundary continues to protect personal routes. The product shell composes a tested navigation model, responsive desktop/mobile navigation, real symbol search, existing utilities, semantic design tokens, and reusable page-width primitives.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript 6, Tailwind CSS 4, shadcn/Radix primitives, Lucide React, Vitest, Testing Library, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-26-stockviz-phase1-app-shell-design.md`

## Global Constraints

- Preserve guest access to Markets, stock detail, Screener, Compare, Backtest, Recommendations, News, and Leaderboard.
- Preserve authentication requirements for Portfolio, Trade, Orders, Trade history, Watchlist, Settings, and alert actions.
- Keep all existing URLs stable; route-group names must not enter URLs.
- Do not change backend/API behavior or chart implementations.
- Do not substantially redesign existing product pages.
- Add no large dependency; use the existing `radix-ui`, `lucide-react`, Tailwind, and shadcn stack.
- Keep server components as the default; client boundaries are limited to pathname state, mobile dialog state, theme state, alerts, and symbol search.
- Gold is limited to brand, active/selected state, focus, and primary actions. Positive and negative values use semantic green and red tokens.
- The desktop sidebar is 224px at `lg` and above; below `lg` navigation uses an accessible drawer.
- The product workspace has no traditional footer.
- Preserve the skip link, landmarks, keyboard navigation, visible focus, contrast, and reduced-motion behavior.
- Approved TDD exception: CSS token declarations and mechanical route moves are configuration changes. Verify them with real layout/component rendering, lint, typecheck, production build, and Playwright where available; do not add source-text/change-detector tests.
- Work only in `D:\Github Repos\stock-viz-simulator\logs\worktrees\redesign-ui-phase1-app-shell` on `redesign/ui-phase1-app-shell`.

## File Map

### New focused units

- `apps/web/lib/app-navigation.ts` — typed navigation data and pure route-matching helpers.
- `apps/web/components/app-navigation.tsx` — shared desktop/drawer navigation renderer using `usePathname`.
- `apps/web/components/app-sidebar.tsx` — desktop brand, EOD context, and navigation landmark.
- `apps/web/components/app-mobile-nav.tsx` — Radix dialog/drawer state and responsive navigation.
- `apps/web/components/global-ticker-search.tsx` — debounced accessible symbol combobox and keyboard shortcut.
- `apps/web/components/top-utility-bar.tsx` — search plus existing alert/theme/account controls.
- `apps/web/components/app-shell.tsx` — product shell composition and main landmark.
- `apps/web/components/public-header.tsx` — reduced marketing navigation and workspace/auth entry.
- `apps/web/components/page-frame.tsx` — workstation/content/narrow width variants.
- `apps/web/app/(public)/layout.tsx` — website header/main/footer composition.
- `apps/web/app/(product)/layout.tsx` — session-aware product shell composition.
- `apps/web/app/(product)/dashboard/page.tsx` — lightweight product-domain entry.
- `apps/web/tests/unit/app-navigation.test.ts` — route-domain behavior.
- `apps/web/tests/unit/global-ticker-search.test.tsx` — typeahead and keyboard behavior.
- `apps/web/tests/unit/app-shell.test.tsx` — shell landmarks, active navigation, and drawer behavior.
- `apps/web/tests/unit/route-shells.test.tsx` — real public/product layout landmark behavior after relocation.
- `apps/web/tests/e2e/app-shell.spec.ts` — guest shell and mobile navigation integration.

### Modified or relocated units

- `apps/web/app/layout.tsx` — remove website chrome; keep document, providers, and skip link.
- `apps/web/app/globals.css` — semantic tokens, fonts, page widths, focus, and reduced motion.
- `apps/web/components/account-menu.tsx` — update relocated auth-action import and compact focus styling.
- `apps/web/components/alert-form.tsx`, `alerts-bell.tsx`, `option-trade-form.tsx`, `options-positions.tsx`, `trade-form.tsx`, `watchlist-toggle.tsx` — update relocated action imports only.
- `apps/web/components/theme-toggle.tsx` — normalized utility-bar label and icon treatment.
- `apps/web/components/site-footer.tsx` — retain for public shell only.
- `apps/web/proxy.ts` — preserve the current protected URL list and comments.
- Existing route directories move under `(public)` or `(product)` without changing page internals.
- Existing outer product `container` classes remain; product-main CSS removes only their desktop max-width so pages gain workspace width without a page redesign.

---

### Task 1: Typed navigation model and active-route mapping

**Files:**
- Create: `apps/web/lib/app-navigation.ts`
- Create: `apps/web/tests/unit/app-navigation.test.ts`

**Interfaces:**
- Produces: `NavigationItem`, `NavigationGroup`, `APP_NAVIGATION`, `pathMatches(pathname, prefixes)`, `getActiveNavigation(pathname)`.
- `getActiveNavigation` returns `{ groupHref: string | null; itemHref: string | null }`.
- Later shell components consume the exact exported navigation array and helpers.

- [ ] **Step 1: Write the failing route-mapping tests**

```ts
import { describe, expect, it } from "vitest";

import { APP_NAVIGATION, getActiveNavigation, pathMatches } from "@/lib/app-navigation";

describe("pathMatches", () => {
  it("matches a route and its descendants without matching a sibling prefix", () => {
    expect(pathMatches("/stocks/AAPL", ["/stocks"])).toBe(true);
    expect(pathMatches("/marketplace", ["/markets"])).toBe(false);
  });
});

describe("getActiveNavigation", () => {
  it.each([
    ["/dashboard", "/dashboard", "/dashboard"],
    ["/markets", "/markets", "/markets"],
    ["/stocks/AAPL", "/screener", null],
    ["/compare?tickers=AAPL", "/screener", "/compare"],
    ["/backtest", "/trade", "/backtest"],
    ["/orders/42", "/trade", "/orders"],
    ["/watchlist", "/portfolio", "/watchlist"],
    ["/trades", "/portfolio", "/trades"],
    ["/leaderboard", "/leaderboard", "/leaderboard"],
  ])("maps %s to its owning domain", (pathname, groupHref, itemHref) => {
    expect(getActiveNavigation(pathname)).toEqual({ groupHref, itemHref });
  });

  it("returns no active route for public pages", () => {
    expect(getActiveNavigation("/login")).toEqual({ groupHref: null, itemHref: null });
  });

  it("defines six top-level product domains", () => {
    expect(APP_NAVIGATION.map((group) => group.label)).toEqual([
      "Home",
      "Markets",
      "Research",
      "Trade",
      "Portfolio",
      "Community",
    ]);
  });
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/app-navigation.test.ts`

Expected: FAIL because `@/lib/app-navigation` does not exist.

- [ ] **Step 3: Implement the navigation model**

```ts
export type NavigationItem = {
  label: string;
  href: string;
  matches: readonly string[];
};

export type NavigationGroup = NavigationItem & {
  items?: readonly NavigationItem[];
};

export const APP_NAVIGATION: readonly NavigationGroup[] = [
  { label: "Home", href: "/dashboard", matches: ["/dashboard"] },
  { label: "Markets", href: "/markets", matches: ["/markets"] },
  {
    label: "Research",
    href: "/screener",
    matches: ["/screener", "/compare", "/recommendations", "/news", "/stocks"],
    items: [
      { label: "Screener", href: "/screener", matches: ["/screener"] },
      { label: "Compare", href: "/compare", matches: ["/compare"] },
      { label: "Recommendations", href: "/recommendations", matches: ["/recommendations"] },
      { label: "News", href: "/news", matches: ["/news"] },
    ],
  },
  {
    label: "Trade",
    href: "/trade",
    matches: ["/trade", "/orders", "/backtest"],
    items: [
      { label: "Trade ticket", href: "/trade", matches: ["/trade"] },
      { label: "Orders", href: "/orders", matches: ["/orders"] },
      { label: "Backtest", href: "/backtest", matches: ["/backtest"] },
    ],
  },
  {
    label: "Portfolio",
    href: "/portfolio",
    matches: ["/portfolio", "/watchlist", "/trades"],
    items: [
      { label: "Overview", href: "/portfolio", matches: ["/portfolio"] },
      { label: "Watchlist", href: "/watchlist", matches: ["/watchlist"] },
      { label: "Trade history", href: "/trades", matches: ["/trades"] },
    ],
  },
  {
    label: "Community",
    href: "/leaderboard",
    matches: ["/leaderboard"],
    items: [{ label: "Leaderboard", href: "/leaderboard", matches: ["/leaderboard"] }],
  },
] as const;

export function pathMatches(pathname: string, prefixes: readonly string[]): boolean {
  const path = pathname.split(/[?#]/, 1)[0];
  return prefixes.some((prefix) => path === prefix || path.startsWith(`${prefix}/`));
}

export function getActiveNavigation(pathname: string): {
  groupHref: string | null;
  itemHref: string | null;
} {
  const group = APP_NAVIGATION.find((entry) => pathMatches(pathname, entry.matches));
  if (!group) return { groupHref: null, itemHref: null };
  const item = group.items?.find((entry) => pathMatches(pathname, entry.matches));
  return { groupHref: group.href, itemHref: item?.href ?? (group.items ? null : group.href) };
}
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/app-navigation.test.ts`

Expected: PASS with all route cases.

- [ ] **Step 5: Commit the navigation model**

```powershell
git add apps/web/lib/app-navigation.ts apps/web/tests/unit/app-navigation.test.ts
git commit -m "feat(web): define workstation navigation model"
```

### Task 2: Real global ticker search

**Files:**
- Create: `apps/web/components/global-ticker-search.tsx`
- Create: `apps/web/tests/unit/global-ticker-search.test.tsx`
- Reuse unchanged: `apps/web/lib/api/symbols.ts`

**Interfaces:**
- Consumes: `searchSymbols(query: string, limit?: number): Promise<Symbol[]>`.
- Produces: `GlobalTickerSearch({ search?, debounceMs? })` with optional injected search function for deterministic tests.
- Navigation target: `/stocks/${encodeURIComponent(symbol.ticker)}`.

- [ ] **Step 1: Write failing tests for blank input, results, keyboard selection, stale requests, errors, and the shortcut**

```tsx
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GlobalTickerSearch } from "@/components/global-ticker-search";
import type { Symbol } from "@/lib/api/types";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const symbol = (ticker: string, name: string): Symbol => ({
  ticker,
  name,
  sector: "Technology",
  exchange: "NASDAQ",
  currency: "USD",
  is_active: true,
});

describe("GlobalTickerSearch", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    push.mockReset();
  });
  afterEach(() => vi.useRealTimers());

  it("does not search blank input", async () => {
    const search = vi.fn().mockResolvedValue([]);
    render(<GlobalTickerSearch search={search} debounceMs={20} />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "   " } });
    await act(() => vi.advanceTimersByTimeAsync(20));
    expect(search).not.toHaveBeenCalled();
  });

  it("shows matching symbols and supports keyboard selection", async () => {
    const search = vi.fn().mockResolvedValue([symbol("AAPL", "Apple Inc.")]);
    render(<GlobalTickerSearch search={search} debounceMs={20} />);
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "app" } });
    await act(() => vi.advanceTimersByTimeAsync(20));
    expect(await screen.findByRole("option", { name: /AAPL.*Apple Inc/i })).toBeVisible();
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(push).toHaveBeenCalledWith("/stocks/AAPL");
  });

  it("keeps the newest response when requests resolve out of order", async () => {
    let resolveFirst!: (value: Symbol[]) => void;
    const first = new Promise<Symbol[]>((resolve) => { resolveFirst = resolve; });
    const search = vi.fn()
      .mockReturnValueOnce(first)
      .mockResolvedValueOnce([symbol("MSFT", "Microsoft")]);
    render(<GlobalTickerSearch search={search} debounceMs={20} />);
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "app" } });
    await act(() => vi.advanceTimersByTimeAsync(20));
    fireEvent.change(input, { target: { value: "mic" } });
    await act(() => vi.advanceTimersByTimeAsync(20));
    expect(await screen.findByText("Microsoft")).toBeVisible();
    await act(async () => resolveFirst([symbol("AAPL", "Apple Inc.")]));
    expect(screen.queryByText("Apple Inc.")).not.toBeInTheDocument();
  });

  it("shows a retryable unavailable state and focuses with Ctrl+K", async () => {
    const search = vi.fn().mockRejectedValue(new Error("offline"));
    render(<GlobalTickerSearch search={search} debounceMs={20} />);
    const input = screen.getByRole("combobox");
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(input).toHaveFocus();
    fireEvent.change(input, { target: { value: "aapl" } });
    await act(() => vi.advanceTimersByTimeAsync(20));
    expect(await screen.findByText("Search unavailable")).toBeVisible();
  });
});
```

- [ ] **Step 2: Run the focused search test and verify RED**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/global-ticker-search.test.tsx`

Expected: FAIL because `GlobalTickerSearch` does not exist.

- [ ] **Step 3: Implement the accessible debounced combobox**

Implement a client component with this public shape and state machine:

```tsx
"use client";

type SearchFn = typeof searchSymbols;

export function GlobalTickerSearch({
  search = searchSymbols,
  debounceMs = 200,
}: {
  search?: SearchFn;
  debounceMs?: number;
}) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const requestRef = useRef(0);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Symbol[]>([]);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");

  useEffect(() => {
    const onShortcut = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onShortcut);
    return () => window.removeEventListener("keydown", onShortcut);
  }, []);

  useEffect(() => {
    const normalized = query.trim();
    const requestId = ++requestRef.current;
    setActiveIndex(-1);
    if (!normalized) {
      setResults([]);
      setStatus("idle");
      return;
    }
    const timeout = window.setTimeout(async () => {
      setStatus("loading");
      try {
        const next = await search(normalized, 8);
        if (requestRef.current !== requestId) return;
        setResults(next);
        setStatus("ready");
      } catch {
        if (requestRef.current !== requestId) return;
        setResults([]);
        setStatus("error");
      }
    }, debounceMs);
    return () => window.clearTimeout(timeout);
  }, [debounceMs, query, search]);

  const select = (result: Symbol) => {
    setQuery("");
    setResults([]);
    setStatus("idle");
    router.push(`/stocks/${encodeURIComponent(result.ticker)}`);
  };

  // Render a Search icon, combobox input, truthful Ctrl/⌘K hint, and a
  // role=listbox overlay. ArrowDown/ArrowUp wraps inside results, Enter calls
  // select(), and Escape clears the result overlay without fabricating data.
}
```

The final render must include `aria-autocomplete="list"`, `aria-expanded`, `aria-controls`, `aria-activedescendant`, a live status region, unique option IDs, ticker in monospace, company/exchange metadata, and neutral error/empty states.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/global-ticker-search.test.tsx`

Expected: PASS for all search and keyboard cases.

- [ ] **Step 5: Run the existing symbol API tests**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/symbols-search.test.ts tests/unit/global-ticker-search.test.tsx`

Expected: PASS; blank API queries still short-circuit and the UI uses the real endpoint contract.

- [ ] **Step 6: Commit the search behavior**

```powershell
git add apps/web/components/global-ticker-search.tsx apps/web/tests/unit/global-ticker-search.test.tsx
git commit -m "feat(web): add global ticker search"
```

### Task 3: Shared navigation renderer, desktop sidebar, and mobile drawer

**Files:**
- Create: `apps/web/components/app-navigation.tsx`
- Create: `apps/web/components/app-sidebar.tsx`
- Create: `apps/web/components/app-mobile-nav.tsx`
- Create: `apps/web/tests/unit/app-shell.test.tsx`
- Reuse for public shell only: `apps/web/components/mobile-nav.tsx`

**Interfaces:**
- Consumes: `APP_NAVIGATION` and `getActiveNavigation` from Task 1.
- Produces: `AppNavigation({ onNavigate? })`, `AppSidebar()`, and `AppMobileNav()`.
- `AppMobileNav` uses the existing `radix-ui` package's `Dialog` namespace and owns only open/close state.

- [ ] **Step 1: Write failing navigation-renderer and drawer tests**

```tsx
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppMobileNav } from "@/components/app-mobile-nav";
import { AppSidebar } from "@/components/app-sidebar";

let pathname = "/compare";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));

describe("AppSidebar", () => {
  it("groups product destinations and marks both active domain and route", () => {
    render(<AppSidebar />);
    const nav = screen.getByRole("navigation", { name: "Product" });
    expect(within(nav).getAllByRole("link", { name: "Research" })[0]).toHaveAttribute(
      "data-active",
      "true",
    );
    expect(within(nav).getByRole("link", { name: "Compare" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByText("EOD data")).toBeVisible();
  });
});

describe("AppMobileNav", () => {
  beforeEach(() => { pathname = "/markets"; });

  it("opens an accessible drawer and closes on Escape", () => {
    render(<AppMobileNav />);
    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    expect(screen.getByRole("dialog", { name: "Product navigation" })).toBeVisible();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Product navigation" })).not.toBeInTheDocument();
  });

  it("closes after selecting a destination", () => {
    render(<AppMobileNav />);
    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    fireEvent.click(screen.getByRole("link", { name: "Screener" }));
    expect(screen.queryByRole("dialog", { name: "Product navigation" })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the focused shell test and verify RED**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/app-shell.test.tsx`

Expected: FAIL because the three navigation components do not exist.

- [ ] **Step 3: Implement `AppNavigation` with active states and icons**

```tsx
"use client";

const ICONS: Record<string, LucideIcon> = {
  Home: House,
  Markets: ChartCandlestick,
  Research: SearchCode,
  Trade: ArrowLeftRight,
  Portfolio: BriefcaseBusiness,
  Community: Users,
} as const;

export function AppNavigation({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const active = getActiveNavigation(pathname);
  return (
    <nav aria-label="Product" className="space-y-1">
      {APP_NAVIGATION.map((group) => {
        const Icon = ICONS[group.label];
        const groupActive = active.groupHref === group.href;
        return (
          <div key={group.href} className="nav-domain">
            <Link
              href={group.href}
              data-active={groupActive || undefined}
              aria-current={groupActive && !group.items ? "page" : undefined}
              onClick={onNavigate}
            >
              <Icon aria-hidden />
              <span>{group.label}</span>
            </Link>
            {group.items ? (
              <div className="nav-children">
                {group.items.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    aria-current={active.itemHref === item.href ? "page" : undefined}
                    onClick={onNavigate}
                  >
                    {item.label}
                  </Link>
                ))}
              </div>
            ) : null}
          </div>
        );
      })}
    </nav>
  );
}
```

Use restrained Lucide icons only on top-level domains. Apply the gold ledger marker with a pseudo-element or an absolutely positioned 2px span only when `data-active=true`; child active state uses gold text plus `aria-current`, not a pill.

- [ ] **Step 4: Implement desktop and mobile wrappers**

`AppSidebar` renders a `hidden lg:flex` 224px `<aside>`, StockViz brand linked to `/dashboard`, the truthful `EOD data` context label, and `AppNavigation`.

`AppMobileNav` uses `Dialog.Root`, `Dialog.Trigger`, `Dialog.Portal`, `Dialog.Overlay`, `Dialog.Content`, `Dialog.Title`, and `Dialog.Close` from `radix-ui`. It renders from the left, is `lg:hidden`, exposes the accessible names in the tests, includes the same brand/context/navigation, and calls `setOpen(false)` through `AppNavigation.onNavigate`.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/app-navigation.test.ts tests/unit/app-shell.test.tsx`

Expected: PASS; desktop and drawer navigation share route data and accessible state.

- [ ] **Step 6: Commit responsive product navigation**

```powershell
git add apps/web/components/app-navigation.tsx apps/web/components/app-sidebar.tsx apps/web/components/app-mobile-nav.tsx apps/web/tests/unit/app-shell.test.tsx
git commit -m "feat(web): add responsive product navigation"
```

### Task 4: Product utility bar and shell composition

**Files:**
- Create: `apps/web/components/top-utility-bar.tsx`
- Create: `apps/web/components/app-shell.tsx`
- Modify: `apps/web/tests/unit/app-shell.test.tsx`
- Modify: `apps/web/components/theme-toggle.tsx`
- Modify: `apps/web/components/account-menu.tsx`
- Modify: `apps/web/components/alerts-bell.tsx`

**Interfaces:**
- Consumes: `AppSidebar`, `AppMobileNav`, `GlobalTickerSearch`, `AlertsBell`, `ThemeToggle`, and `AccountMenu`.
- Produces: `TopUtilityBar({ signedIn: boolean })` and `AppShell({ children, signedIn })`.

- [ ] **Step 1: Add a failing shell-composition test**

Mock the async account menu and alert polling at module boundaries, then append:

```tsx
vi.mock("@/components/account-menu", () => ({ AccountMenu: () => <button>Account menu</button> }));
vi.mock("@/components/alerts-bell", () => ({ AlertsBell: () => <button>Alerts</button> }));

it("renders a single workstation main landmark without a website footer", () => {
  render(<AppShell signedIn={true}><h1>Markets</h1></AppShell>);
  expect(screen.getByRole("main")).toHaveAttribute("id", "main");
  expect(screen.getByRole("combobox", { name: "Search tickers and companies" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Alerts" })).toBeVisible();
  expect(screen.queryByRole("contentinfo")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/app-shell.test.tsx`

Expected: FAIL because `AppShell` and `TopUtilityBar` do not exist.

- [ ] **Step 3: Implement the utility bar and shell**

```tsx
export function TopUtilityBar({ signedIn }: { signedIn: boolean }) {
  return (
    <header className="sticky top-0 z-30 flex h-13 items-center gap-2 border-b border-border-muted bg-background/92 px-3 backdrop-blur lg:px-5">
      <AppMobileNav />
      <div className="min-w-0 max-w-xl flex-1"><GlobalTickerSearch /></div>
      <div className="ml-auto flex items-center gap-1">
        <AlertsBell enabled={signedIn} />
        <ThemeToggle />
        <AccountMenu />
      </div>
    </header>
  );
}

export function AppShell({ children, signedIn }: { children: React.ReactNode; signedIn: boolean }) {
  return (
    <div className="min-h-screen bg-background lg:grid lg:grid-cols-[14rem_minmax(0,1fr)]">
      <AppSidebar />
      <div className="min-w-0">
        <TopUtilityBar signedIn={signedIn} />
        <main id="main" tabIndex={-1} className="workspace-main min-w-0">{children}</main>
      </div>
    </div>
  );
}
```

Normalize all utility controls to 36px desktop/40px mobile targets, use tokenized neutral hover/focus states, give the theme button the explicit label `Toggle color theme`, and preserve existing alert/account behavior.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/app-shell.test.tsx tests/unit/global-ticker-search.test.tsx`

Expected: PASS with one main landmark and no product footer.

- [ ] **Step 5: Commit shell composition**

```powershell
git add apps/web/components/top-utility-bar.tsx apps/web/components/app-shell.tsx apps/web/components/theme-toggle.tsx apps/web/components/account-menu.tsx apps/web/components/alerts-bell.tsx apps/web/tests/unit/app-shell.test.tsx
git commit -m "feat(web): compose workstation utility shell"
```

### Task 5: Public/product route-group separation

**Files:**
- Create: `apps/web/tests/unit/route-shells.test.tsx`
- Create: `apps/web/app/(public)/layout.tsx`
- Create: `apps/web/app/(product)/layout.tsx`
- Modify: `apps/web/app/layout.tsx`
- Move: `apps/web/app/page.tsx` → `apps/web/app/(public)/page.tsx`
- Move: `apps/web/app/(auth)` → `apps/web/app/(public)/(auth)`
- Move: `apps/web/app/sign-in-required` → `apps/web/app/(public)/sign-in-required`
- Move under `apps/web/app/(product)/`: `markets`, `stocks`, `screener`, `compare`, `recommendations`, `news`, `backtest`, `leaderboard`, and `(authed)`.
- Modify action imports in: `account-menu.tsx`, `alert-form.tsx`, `alerts-bell.tsx`, `option-trade-form.tsx`, `options-positions.tsx`, `trade-form.tsx`, `watchlist-toggle.tsx`.

**Interfaces:**
- Public URLs remain `/`, `/login`, `/signup`, and `/sign-in-required`.
- Product URLs remain `/markets`, `/stocks/[ticker]`, `/screener`, `/compare`, `/recommendations`, `/news`, `/backtest`, `/leaderboard`, `/portfolio`, `/watchlist`, `/trade`, `/orders`, `/trades`, and `/settings`.
- Product layout calls `auth()` and passes `Boolean(session?.user?.id)` to `AppShell`.

- [ ] **Step 1: Write a failing real-layout test at the intended route-group imports**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ProductLayout from "@/app/(product)/layout";
import PublicLayout from "@/app/(public)/layout";

vi.mock("@/auth", () => ({ auth: vi.fn().mockResolvedValue(null) }));
vi.mock("@/components/account-menu", () => ({ AccountMenu: () => <button>Account</button> }));
vi.mock("@/components/alerts-bell", () => ({ AlertsBell: () => null }));
vi.mock("@/components/theme-toggle", () => ({ ThemeToggle: () => <button>Theme</button> }));

describe("route shell ownership", () => {
  it("renders public content with website footer", async () => {
    render(await PublicLayout({ children: <h1>Welcome</h1> }));
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
    expect(screen.getByRole("contentinfo")).toBeVisible();
  });

  it("renders product content with workstation navigation and no footer", async () => {
    render(await ProductLayout({ children: <h1>Markets</h1> }));
    expect(screen.getByRole("navigation", { name: "Product" })).toBeVisible();
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
    expect(screen.queryByRole("contentinfo")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the topology test and verify RED**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/route-shells.test.tsx`

Expected: FAIL because the intended public/product layout modules do not yet exist.

- [ ] **Step 3: Move route directories without changing URL-visible names**

Use Git-aware moves for the directories listed above. Keep `api`, `error.tsx`, `global-error.tsx`, and `not-found.tsx` at root. Do not edit individual product page composition during the move.

- [ ] **Step 4: Reduce the root layout to document concerns**

```tsx
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen bg-background text-foreground antialiased">
        <Providers>
          <a href="#main" className="skip-link">Skip to main content</a>
          {children}
        </Providers>
      </body>
    </html>
  );
}
```

- [ ] **Step 5: Add the product layout**

```tsx
import { auth } from "@/auth";
import { AppShell } from "@/components/app-shell";

export default async function ProductLayout({ children }: { children: React.ReactNode }) {
  const session = await auth();
  return <AppShell signedIn={Boolean(session?.user?.id)}>{children}</AppShell>;
}
```

- [ ] **Step 6: Add the public layout and update relocated action imports**

The public layout renders `PublicHeader`, `<main id="main" tabIndex={-1}>`, and `SiteFooter`. Temporarily import the existing `SiteHeader` until Task 7 replaces it with `PublicHeader`. Update action imports to:

```ts
@/app/(public)/(auth)/actions
@/app/(product)/(authed)/alerts/actions
@/app/(product)/(authed)/trade/actions
@/app/(product)/(authed)/trade/options-actions
@/app/(product)/(authed)/watchlist/actions
```

- [ ] **Step 7: Run topology, typecheck, and unit tests**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/route-shells.test.tsx`

Expected: PASS.

Run: `pnpm.cmd --filter @stockviz/web typecheck`

Expected: PASS with all relocated imports resolved.

Run: `pnpm.cmd --filter @stockviz/web test`

Expected: all unit tests PASS.

- [ ] **Step 8: Commit the route split**

```powershell
git add apps/web/app apps/web/components apps/web/tests/unit/route-shells.test.tsx
git commit -m "refactor(web): separate public and product shells"
```

### Task 6: Semantic design tokens and width foundations

**Files:**
- Modify: `apps/web/app/globals.css`
- Create: `apps/web/components/page-frame.tsx`

**Interfaces:**
- Produces Tailwind colors: `surface-elevated`, `surface-secondary`, `surface-hover`, `border-muted`, `text-secondary`, `text-tertiary`, `positive`, `negative`, and `warning`, while preserving shadcn tokens.
- Produces `PageFrame({ width: "workstation" | "content" | "narrow", className?, children })`.

- [ ] **Step 1: Replace the minimal token set with the approved semantic palette**

Define complete light and dark `:root`/`.dark` OKLCH values for background, foreground, card, popover, primary, secondary, muted, accent, destructive, border, input, ring, surface hierarchy, text hierarchy, positive, negative, and warning. Map every token through `@theme inline`. Set `--radius: 0.375rem`, a system UI sans stack, a platform monospace/data stack, tabular financial numerals, a high-contrast `.skip-link`, direct-child workspace container override, and `.page-frame-*` width classes.

Use these fixed anchors from the spec: graphite `#0C0E12/#F5F6F8`, instrument surface `#13161C/#FFFFFF`, secondary `#1A1E26/#ECEFF3`, gold `#D3A83F`, positive `#2BA477`, negative `#D75D63`.

Add:

```css
*:focus-visible {
  outline: 2px solid var(--ring);
  outline-offset: 2px;
}

.workspace-main > .container {
  width: 100%;
  max-width: none;
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    scroll-behavior: auto !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

- [ ] **Step 2: Add the page-width primitive**

```tsx
const widths = {
  workstation: "page-frame-workstation",
  content: "page-frame-content",
  narrow: "page-frame-narrow",
} as const;

export function PageFrame({
  width = "content",
  className,
  children,
}: React.PropsWithChildren<{ width?: keyof typeof widths; className?: string }>) {
  return <div className={cn(widths[width], className)}>{children}</div>;
}
```

- [ ] **Step 3: Verify the configuration through the real shell, lint, and typecheck**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/app-shell.test.tsx`

Expected: PASS.

Run: `pnpm.cmd --filter @stockviz/web lint`

Expected: PASS with Biome accepting the new component and CSS.

Run: `pnpm.cmd --filter @stockviz/web typecheck`

Expected: PASS with every mapped semantic utility recognized by TypeScript consumers.

- [ ] **Step 4: Commit design foundations**

```powershell
git add apps/web/app/globals.css apps/web/components/page-frame.tsx
git commit -m "style(web): establish workstation design tokens"
```

### Task 7: Refined public header and lightweight workspace home

**Files:**
- Create: `apps/web/components/public-header.tsx`
- Create: `apps/web/app/(product)/dashboard/page.tsx`
- Modify: `apps/web/app/(public)/layout.tsx`
- Modify: `apps/web/tests/unit/app-shell.test.tsx`
- Delete: `apps/web/components/site-header.tsx`

**Interfaces:**
- Produces: `PublicHeader()` server component and `/dashboard` page.
- Public header links: `/markets`, `/screener`, `/backtest`; signed-in CTA `/dashboard`; signed-out CTA `/signup`; theme and account remain reachable.

- [ ] **Step 1: Add failing public-shell and workspace-home tests**

Mock `auth()` and `AccountMenu`, then assert the public header has only the reduced product entry links and that the dashboard exposes all six domains:

```tsx
it("keeps marketing navigation concise", async () => {
  render(await PublicHeader());
  const nav = screen.getByRole("navigation", { name: "Public" });
  expect(within(nav).getAllByRole("link")).toHaveLength(3);
  expect(screen.queryByRole("link", { name: "Orders" })).not.toBeInTheDocument();
});

it("orients the workspace around product domains", () => {
  render(<DashboardPage />);
  expect(screen.getByRole("heading", { name: "Your research workspace" })).toBeVisible();
  for (const name of ["Markets", "Research", "Trade", "Portfolio", "Community"]) {
    expect(screen.getByRole("link", { name: new RegExp(name, "i") })).toBeVisible();
  }
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/app-shell.test.tsx`

Expected: FAIL because `PublicHeader` and the dashboard page do not exist.

- [ ] **Step 3: Implement the reduced public header**

Use the existing StockViz mark and a 56px public header. Render three neutral links (`Markets`, `Research`, `Backtest`), `ThemeToggle`, `AccountMenu`, and one gold primary CTA selected from the real session. Pass the same three links to the existing compact `MobileNav`; it remains public-only and retains its current accessible trigger and Radix keyboard behavior.

- [ ] **Step 4: Implement the lightweight dashboard**

Use `PageFrame width="workstation"`. Render a compact title/description and a divided list/grid of domain links with plain-language descriptions:

```tsx
const destinations = [
  ["Markets", "/markets", "Scan the tracked universe and daily movement."],
  ["Research", "/screener", "Screen, compare, and review market context."],
  ["Trade", "/trade", "Place simulated trades and review pending orders."],
  ["Portfolio", "/portfolio", "Track positions, performance, and watchlists."],
  ["Community", "/leaderboard", "Compare public paper portfolios."],
] as const;
```

Do not add decorative KPI cards or backend calls. Use dividers, typography, and one gold directional affordance.

- [ ] **Step 5: Replace `SiteHeader` in the public layout and remove it**

Update `(public)/layout.tsx` to import `PublicHeader`. Confirm no imports reference `site-header.tsx`, then delete the obsolete eleven-peer-link component.

- [ ] **Step 6: Run focused tests and full web checks**

Run: `pnpm.cmd --filter @stockviz/web test -- tests/unit/app-shell.test.tsx tests/unit/route-shells.test.tsx`

Expected: PASS.

Run: `pnpm.cmd --filter @stockviz/web typecheck`

Expected: PASS.

Run: `pnpm.cmd --filter @stockviz/web lint`

Expected: PASS.

- [ ] **Step 7: Commit public/product entry points**

```powershell
git add apps/web/components/public-header.tsx apps/web/components/site-header.tsx apps/web/app/(public)/layout.tsx apps/web/app/(product)/dashboard/page.tsx apps/web/tests/unit/app-shell.test.tsx
git commit -m "feat(web): add focused public and workspace entry points"
```

### Task 8: Integration coverage and complete verification

**Files:**
- Create: `apps/web/tests/e2e/app-shell.spec.ts`
- Modify only if assertions require stable accessible names: existing shell components.
- Modify: `docs/superpowers/plans/2026-08-26-stockviz-phase1-app-shell.md` to mark executed checkboxes.

**Interfaces:**
- Produces e2e coverage for the guest product shell, public footer separation, active navigation, utility controls, and mobile drawer.

- [ ] **Step 1: Write the e2e shell tests before any integration fixes**

```ts
import { expect, test } from "@playwright/test";

test("guest research routes use the product shell without a website footer", async ({ page }) => {
  await page.goto("/markets");
  await expect(page.getByRole("navigation", { name: "Product" })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Search tickers and companies" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Markets" }).first()).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(page.getByRole("contentinfo")).toHaveCount(0);
});

test("public pages keep concise website chrome", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("navigation", { name: "Public" })).toBeVisible();
  await expect(page.getByRole("contentinfo")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Product" })).toHaveCount(0);
});

test("mobile product navigation exposes the same hierarchy", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/screener");
  await page.getByRole("button", { name: "Open navigation" }).click();
  const drawer = page.getByRole("dialog", { name: "Product navigation" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole("link", { name: "Compare" })).toBeVisible();
});
```

- [ ] **Step 2: Run unit, lint, and typecheck gates first**

Run: `pnpm.cmd --filter @stockviz/web test`

Expected: all web unit tests PASS.

Run: `pnpm.cmd --filter @stockviz/web lint`

Expected: PASS.

Run: `pnpm.cmd --filter @stockviz/web typecheck`

Expected: PASS.

- [ ] **Step 3: Run repository-wide backend regression gates**

Run: `uv --directory apps/api run pytest`

Expected: all API tests PASS; no backend behavior changed.

Run: `pnpm.cmd lint`

Expected: web Biome and API Ruff PASS.

Run: `pnpm.cmd typecheck`

Expected: web TypeScript and API Pyright PASS.

- [ ] **Step 4: Run the production build**

Run: `pnpm.cmd build`

Expected: Next.js production build exits 0 and lists all unchanged URL paths plus `/dashboard`.

- [ ] **Step 5: Run Playwright when prerequisites are available**

First verify PostgreSQL/API readiness using the documented setup. If they are available, run:

`pnpm.cmd e2e`

Expected: existing auth/markets/trade specs and the new app-shell spec PASS.

If prerequisites are absent, record the exact failing prerequisite or command output; do not claim e2e passed.

- [ ] **Step 6: Perform visual QA when a browser connection is available**

Inspect `/`, `/login`, `/markets`, `/stocks/AAPL`, `/screener`, `/portfolio`, `/trade`, and `/backtest` at 1440px, 1280px, and 390px in dark and light themes. Capture screenshots for desktop and mobile. Check sidebar proportion, active states, content width, table space, header height, footer separation, contrast, focus visibility, and document-level overflow.

The current session has no connected browser. If that remains true, record screenshots as unavailable rather than substituting unreviewed images.

- [ ] **Step 7: Review the final diff against every completion criterion**

Run:

```powershell
git diff --check origin/dev...HEAD
git status --short
git diff --stat origin/dev...HEAD
git log --oneline origin/dev..HEAD
```

Confirm public/product separation, six-domain navigation, no product footer, both theme token sets, mobile drawer, real search, stable URLs, preserved auth, and no page-level redesign.

- [ ] **Step 8: Commit integration coverage and plan completion**

```powershell
git add apps/web/tests/e2e/app-shell.spec.ts docs/superpowers/plans/2026-08-26-stockviz-phase1-app-shell.md
git commit -m "test(web): verify phase 1 application shell"
```

- [ ] **Step 9: Record final Git state for handoff**

Run:

```powershell
git rev-parse --show-toplevel
git branch --show-current
git rev-parse origin/dev
git rev-parse HEAD
git status --short --branch
```

Use these exact values in the final Summary, Architecture, Files changed, UX decisions, Verification, Screenshots, Git state, Remaining issues, and Recommended Phase 2 sections.
