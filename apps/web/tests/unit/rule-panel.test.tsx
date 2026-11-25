import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/(product)/screener/actions", () => ({
  saveSetupAction: vi.fn(async () => ({})),
  forkPresetAction: vi.fn(async () => ({})),
}));

import { RulePanel, type RulePreset } from "@/components/rule-panel";
import type { RuleCheck } from "@/lib/api/rules";

const VALID: RuleCheck = {
  valid: true,
  canonical: "close > sma(close, 200) and rsi(14) < 30",
  hash: "a".repeat(64),
  type: "boolean series",
  warmup_bars: 199,
  warmup_whole_history: false,
  uses: [],
  user_scoped: false,
  error: null,
};

const SCOPED: RuleCheck = {
  ...VALID,
  canonical: 'close > drawing("support").price',
  warmup_bars: 0,
  uses: ["drawings"],
  user_scoped: true,
};

const INVALID: RuleCheck = {
  valid: false,
  canonical: null,
  hash: null,
  type: null,
  warmup_bars: null,
  warmup_whole_history: false,
  uses: [],
  user_scoped: false,
  error: { kind: "syntax", message: "unexpected 'andd'", line: 1, column: 9 },
};

const PRESETS: RulePreset[] = [
  {
    id: 3,
    name: "RSI pullback in an uptrend",
    description: "Source: Connors and Alvarez.",
    rule: "close > sma(close, 200) and rsi(2) < 10",
  },
];

function renderPanel(overrides: Partial<Parameters<typeof RulePanel>[0]> = {}) {
  const check = vi.fn(async (rule: string) => (rule.includes("andd") ? INVALID : VALID));
  render(
    <RulePanel
      rule=""
      mode="met_only"
      carried={[
        ["market", "US"],
        ["sort", "rsi"],
      ]}
      presets={PRESETS}
      signedIn
      clearHref={null}
      check={check}
      {...overrides}
    />,
  );
  return { check };
}

describe("RulePanel (A2.2)", () => {
  it("shows a syntax error at its column and blocks Run and Save", async () => {
    const user = userEvent.setup();
    const { check } = renderPanel();
    await user.type(screen.getByLabelText("Rule text"), "close > andd 1");
    const alert = await screen.findByText("Syntax error at line 1, column 9: unexpected 'andd'");
    expect(alert).toBeVisible();
    // The caret sits under column 9 of the line as typed.
    const status = alert.closest("[role=alert]") as HTMLElement;
    expect(status.querySelector("pre")?.textContent).toBe("close > andd 1\n        ^");
    expect(screen.getByRole("button", { name: "Run" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save as setup" })).toBeDisabled();
    expect(screen.getByLabelText("Rule text")).toHaveAttribute("aria-invalid", "true");
    // Debounced: one check for the settled text, not one per key.
    expect(check).toHaveBeenLastCalledWith("close > andd 1", expect.anything());
    expect(check.mock.calls.length).toBeLessThan(5);
  });

  it("shows the canonical form and warm-up when valid, and enables Save", async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.type(screen.getByLabelText("Rule text"), "rsi() < 30 and close > sma(close, 200)");
    expect(await screen.findByTestId("canonical")).toHaveTextContent(VALID.canonical as string);
    expect(screen.getByText(/Needs 199 daily bars of warm-up/)).toBeVisible();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save as setup" })).toBeEnabled(),
    );
    expect(screen.getByRole("button", { name: "Run" })).toBeEnabled();
  });

  it("notes a user-scoped rule (A3.3): it reads your drawings and runs only for you", async () => {
    const user = userEvent.setup();
    const check = vi.fn(async () => SCOPED);
    renderPanel({ check });
    await user.type(screen.getByLabelText("Rule text"), 'close > drawing("support").price');
    expect(await screen.findByTestId("rule-user-scoped")).toHaveTextContent(
      "Uses your drawings; only you can run it.",
    );
    expect(screen.getByText(/reads drawings/)).toBeVisible();
  });

  it("tells a signed-out visitor to sign in to run a user-scoped rule", async () => {
    const user = userEvent.setup();
    renderPanel({ check: vi.fn(async () => SCOPED), signedIn: false });
    await user.type(screen.getByLabelText("Rule text"), 'close > avwap("swing")');
    expect(await screen.findByTestId("rule-user-scoped")).toHaveTextContent(/sign in to run it/);
  });

  it("says nothing extra for an ordinary rule", async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.type(screen.getByLabelText("Rule text"), "close > open");
    await screen.findByTestId("canonical");
    expect(screen.queryByTestId("rule-user-scoped")).toBeNull();
  });

  it("is a GET form to /screener that carries the other filters (URL state)", () => {
    renderPanel({ rule: "close > open", mode: "all" });
    const textarea = screen.getByLabelText("Rule text") as HTMLTextAreaElement;
    expect(textarea).toHaveValue("close > open");
    expect(textarea.name).toBe("rule");
    const form = textarea.closest("form") as HTMLFormElement;
    expect(form.getAttribute("method")).toBe("GET");
    expect(form.getAttribute("action")).toBe("/screener");
    const hidden = Array.from(form.querySelectorAll("input[type=hidden]")).map((input) => [
      (input as HTMLInputElement).name,
      (input as HTMLInputElement).value,
    ]);
    expect(hidden).toEqual([
      ["market", "US"],
      ["sort", "rsi"],
    ]);
    expect(within(form).getByLabelText("Show all with result")).toBeChecked();
  });

  it("toggles the mode between met only and all", async () => {
    const user = userEvent.setup();
    renderPanel();
    const metOnly = screen.getByLabelText("Met only");
    const all = screen.getByLabelText("Show all with result");
    expect(metOnly).toBeChecked();
    await user.click(all);
    expect(all).toBeChecked();
    expect(metOnly).not.toBeChecked();
    expect((all as HTMLInputElement).name).toBe("rule_mode");
    expect((all as HTMLInputElement).value).toBe("all");
  });

  it("loads a preset into the editor and shows its source", async () => {
    const user = userEvent.setup();
    renderPanel();
    expect(screen.getByRole("button", { name: "Load" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Fork" })).toBeDisabled();
    await user.selectOptions(screen.getByLabelText("Presets"), "3");
    expect(screen.getByTestId("preset-description")).toHaveTextContent("Connors");
    await user.click(screen.getByRole("button", { name: "Load" }));
    expect(screen.getByLabelText("Rule text")).toHaveValue(PRESETS[0].rule);
    expect(screen.getByRole("button", { name: "Fork" })).toBeEnabled();
  });

  it("signed out: no Save or Fork, a sign-in link instead", () => {
    renderPanel({ signedIn: false, rule: "close > open" });
    expect(screen.queryByRole("button", { name: "Save as setup" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Fork" })).toBeNull();
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute(
      "href",
      "/login?callbackUrl=/screener",
    );
  });

  it("offers Clear rule when a rule is applied", () => {
    renderPanel({ rule: "close > open", clearHref: "/screener?market=US" });
    expect(screen.getByRole("link", { name: "Clear rule" })).toHaveAttribute(
      "href",
      "/screener?market=US",
    );
  });
});
