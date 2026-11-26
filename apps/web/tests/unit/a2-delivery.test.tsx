import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AlertForm, type AlertSetup } from "@/components/alert-form";
import { NotificationChannelsPanel } from "@/components/notification-channels-panel";
import { NotifyToggle } from "@/components/saved-screens";
import { ScreenChanges, screenChanges } from "@/components/screen-changes";
import { previewRule } from "@/lib/alert-rules";
import type { NotificationChannel } from "@/lib/api/notifications";

vi.mock("@/app/(product)/(authed)/alerts/actions", () => ({
  createAlertAction: vi.fn(async () => ({})),
}));
vi.mock("@/app/(product)/screener/actions", () => ({
  saveScreenAction: vi.fn(async () => ({})),
  deleteScreenAction: vi.fn(async () => undefined),
  toggleScreenNotifyAction: vi.fn(async () => ({ on: true })),
}));
vi.mock("@/app/(product)/(authed)/settings/notification-actions", () => ({
  saveChannelAction: vi.fn(async () => ({})),
  testChannelAction: vi.fn(async () => ({})),
}));

const SETUPS: AlertSetup[] = [
  { versionId: 11, name: "My breakout", version: 2, canonical: "close > 100", preset: false },
  {
    versionId: 3,
    name: "Minervini trend template",
    version: 1,
    canonical: "close > sma(close, 200)",
    preset: true,
  },
];

describe("AlertForm rule kind (A2.3)", () => {
  it("offers your setups and presets and shows the chosen rule", () => {
    render(<AlertForm ticker="AAPL" setups={SETUPS} variant="inline" />);
    fireEvent.change(screen.getByLabelText("Alert me on"), { target: { value: "rule" } });
    const picker = screen.getByLabelText("Saved setup") as HTMLSelectElement;
    expect(picker.name).toBe("setup_version_id");
    const groups = within(picker).getAllByRole("group");
    expect(groups.map((g) => g.getAttribute("label"))).toEqual(["Your setups", "Presets"]);
    fireEvent.change(picker, { target: { value: "11" } });
    expect(screen.getByTestId("alert-setup-rule").textContent).toBe("close > 100");
    expect(screen.getByTestId("alert-preview").textContent).toContain(
      "When AAPL meets My breakout (v2) after not meeting it, once.",
    );
    // The other kinds still render their fields.
    fireEvent.change(screen.getByLabelText("Alert me on"), { target: { value: "price" } });
    expect(screen.getByLabelText(/Target/)).toBeTruthy();
  });

  it("points to /setups when there are none", () => {
    render(<AlertForm ticker="AAPL" variant="inline" />);
    fireEvent.change(screen.getByLabelText("Alert me on"), { target: { value: "rule" } });
    expect(screen.getByTestId("alert-no-setups").querySelector("a")?.getAttribute("href")).toBe(
      "/setups",
    );
  });

  it("words a draft with no setup", () => {
    expect(previewRule({ kind: "rule", ticker: "AAPL" })).toBe("Pick a saved setup.");
  });
});

describe("saved screen notify toggle (A2.3)", () => {
  const base = { created_at: "2026-11-25T00:00:00", updated_at: "2026-11-25T00:00:00" };

  it("shows for a screen with a rule, checked when subscribed", () => {
    render(
      <NotifyToggle
        screen={{
          ...base,
          id: 4,
          name: "Breakouts",
          query: "rule=close+%3E+100",
          notify_on_change: true,
        }}
      />,
    );
    const box = screen.getByLabelText("Notify me when members of Breakouts change");
    expect((box as HTMLInputElement).checked).toBe(true);
  });

  it("is absent for a screen without a rule", () => {
    const { container } = render(
      <NotifyToggle screen={{ ...base, id: 5, name: "Plain", query: "market=US" }} />,
    );
    expect(container.textContent).toBe("");
  });
});

describe("screen changes on /notifications (A2.3)", () => {
  it("lists entries and exits as links", () => {
    render(<ScreenChanges data={{ entries: ["BBB"], exits: ["AAA", "CCC"] }} />);
    expect(screen.getByText("Entered (1)")).toBeTruthy();
    expect(screen.getByText("Left (2)")).toBeTruthy();
    expect(screen.getByRole("link", { name: "BBB" }).getAttribute("href")).toBe("/stocks/BBB");
    expect(screenChanges({ entries: [], exits: [] })).toBeNull();
    expect(screenChanges(null)).toBeNull();
  });
});

describe("Settings notifications panel (A2.3)", () => {
  const channels: NotificationChannel[] = [
    {
      channel: "webhook",
      enabled: true,
      available: true,
      configured: true,
      url: "https://example.com/hook",
      secret_set: true,
      muted_categories: ["order"],
    },
    {
      channel: "email",
      enabled: false,
      available: false,
      configured: false,
      secret_set: false,
      muted_categories: [],
    },
    {
      channel: "telegram",
      enabled: false,
      available: true,
      configured: false,
      secret_set: false,
      chat_id: null,
      muted_categories: [],
    },
  ];

  it("keeps the secret write-only and marks unavailable channels", () => {
    render(
      <NotificationChannelsPanel
        channels={channels}
        categories={["alert", "order", "screen"]}
        accountEmail="me@example.com"
      />,
    );
    const secret = screen.getByLabelText(/Signing secret/) as HTMLInputElement;
    expect(secret.value).toBe("");
    expect(secret.placeholder).toBe("set");
    expect(screen.getByLabelText(/Signing secret/).closest("div")?.textContent).toContain(
      "(set; leave blank to keep it)",
    );
    expect(screen.getByTestId("channel-email-unavailable").textContent).toBe(
      "Not available on this server.",
    );
    expect(screen.queryByRole("alert")).toBeNull();
    // Muted categories start unticked; Telegram explains the chat id.
    const webhook = screen.getByRole("region", { name: "Webhook" });
    const orders = within(webhook).getByLabelText("Orders") as HTMLInputElement;
    expect(orders.checked).toBe(false);
    expect((within(webhook).getByLabelText("Alerts") as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText(/paste your numeric chat id/)).toBeTruthy();
    // Send test needs a saved channel.
    const telegram = screen.getByRole("region", { name: "Telegram" });
    expect(
      (within(telegram).getByRole("button", { name: "Send test" }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(
      (within(webhook).getByRole("button", { name: "Send test" }) as HTMLButtonElement).disabled,
    ).toBe(false);
  });
});
