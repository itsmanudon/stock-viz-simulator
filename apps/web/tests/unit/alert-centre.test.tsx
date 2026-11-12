import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AlertForm } from "@/components/alert-form";
import { AlertsBell, POLL_INTERVAL_MS } from "@/components/alerts-bell";
import {
  distanceToTargetPct,
  matchesAlertView,
  parseNotificationCategory,
  previewRule,
} from "@/lib/alert-rules";

vi.mock("@/app/(product)/(authed)/alerts/actions", () => ({
  createAlertAction: vi.fn(async () => ({})),
}));
vi.mock("@/app/(product)/(authed)/notifications/actions", () => ({
  markAllNotificationsReadAction: vi.fn(),
}));

describe("alert rule helpers (Phase 7.3)", () => {
  it("measures the distance to a target from the close", () => {
    expect(distanceToTargetPct("100", "110")).toBeCloseTo(10);
    expect(distanceToTargetPct("100", "95")).toBeCloseTo(-5);
    expect(distanceToTargetPct(null, "95")).toBeNull();
  });

  it("files rules under the right tab", () => {
    const fired = { triggered_at: "2026-11-12T22:30:00", repeat: "once" };
    expect(matchesAlertView(fired, "active")).toBe(false);
    expect(matchesAlertView({ ...fired, repeat: "every_cross" }, "active")).toBe(true);
    expect(matchesAlertView({ triggered_at: null, paused: true }, "active")).toBe(false);
    expect(matchesAlertView({ triggered_at: null, paused: true }, "all")).toBe(true);
  });

  it("previews each kind in words", () => {
    expect(previewRule({ kind: "price", ticker: "AAPL", direction: "below", target: "180" })).toBe(
      "When AAPL closes below 180, once.",
    );
    expect(
      previewRule({
        kind: "technical",
        ticker: "INFY.NS",
        indicator: "rsi_14",
        op: "below",
        value: "30",
        repeat: "every_cross",
      }), // fmt
    ).toBe("When INFY.NS's rsi_14 crosses below 30, every time it happens.");
    expect(previewRule({ kind: "news", ticker: "AAPL", sentiment: "negative" })).toBe(
      "When new negative AAPL news arrives from Aegis, once.",
    );
    expect(parseNotificationCategory("order")).toBe("order");
    expect(parseNotificationCategory("bogus")).toBe("");
  });
});

describe("AlertForm (UX-2)", () => {
  it("finds a symbol, shows its close and date, and the distance to the target", () => {
    render(
      <AlertForm
        ticker=""
        variant="inline"
        symbols={[
          {
            ticker: "AAPL",
            name: "Apple",
            currency: "USD",
            last_close: "200",
            last_close_at: "2026-11-12T00:00:00",
          },
        ]} // fmt
      />,
    );
    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "aapl" } });
    expect(screen.getByTestId("alert-close")).toHaveTextContent(
      "Stored close $200.00 on Nov 12, 2026.",
    );
    fireEvent.change(screen.getByLabelText("Target (USD)"), { target: { value: "210" } });
    expect(screen.getByTestId("alert-distance")).toHaveTextContent("5.00% above the stored close.");
    expect(screen.getByTestId("alert-preview")).toHaveTextContent(
      "When AAPL closes above 210, once.",
    );
    fireEvent.change(screen.getByLabelText("Alert me on"), { target: { value: "portfolio" } });
    expect(screen.queryByLabelText("Symbol")).toBeNull();
  });
});

describe("AlertsBell (RS-11)", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("keeps the last count when a poll fails, and stops while the tab is hidden", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ unread: 3, latest: [] })))
      .mockResolvedValueOnce(new Response("down", { status: 503 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<AlertsBell enabled />);
    await act(async () => {});
    expect(screen.getByTestId("bell-count")).toHaveTextContent("3");

    await act(async () => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS);
    });
    expect(screen.getByTestId("bell-count")).toHaveTextContent("3");
    expect(screen.getByRole("button")).toHaveAttribute(
      "title",
      "3 unread notifications (couldn't refresh; showing the last count)",
    );

    Object.defineProperty(document, "hidden", { configurable: true, value: true });
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      vi.advanceTimersByTime(POLL_INTERVAL_MS * 3);
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    Object.defineProperty(document, "hidden", { configurable: true, value: false });
  });
});
