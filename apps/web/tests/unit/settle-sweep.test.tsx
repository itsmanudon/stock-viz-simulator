import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const KEY = "stockviz:order-status";

/** The component keeps a per-page-load snapshot, so load it fresh per test. */
async function load() {
  vi.resetModules();
  return (await import("@/components/settle-sweep")).SettleSweep;
}

describe("SettleSweep", () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => window.localStorage.clear());

  it("plays once for an order last seen pending that is now filled", async () => {
    window.localStorage.setItem(KEY, JSON.stringify({ "7": "pending" }));
    const SettleSweep = await load();
    const { container } = render(
      <SettleSweep orderId={7} status="filled">
        <span>Filled</span>
      </SettleSweep>,
    );
    expect(container.querySelector("[data-settled]")).not.toBeNull();
    expect(JSON.parse(window.localStorage.getItem(KEY) ?? "{}")["7"]).toBe("filled");
  });

  it("plays on both copies of an order rendered twice on one page", async () => {
    window.localStorage.setItem(KEY, JSON.stringify({ "7": "pending" }));
    const SettleSweep = await load();
    const { container } = render(
      <>
        <SettleSweep orderId={7} status="filled">
          <span>table</span>
        </SettleSweep>
        <SettleSweep orderId={7} status="filled">
          <span>card</span>
        </SettleSweep>
      </>,
    );
    expect(container.querySelectorAll("[data-settled]")).toHaveLength(2);
  });

  it("stays still for an order first seen filled, or still pending", async () => {
    const SettleSweep = await load();
    const { container } = render(
      <>
        <SettleSweep orderId={8} status="filled">
          <span>new</span>
        </SettleSweep>
        <SettleSweep orderId={9} status="pending">
          <span>waiting</span>
        </SettleSweep>
      </>,
    );
    expect(container.querySelector("[data-settled]")).toBeNull();
  });

  it("does not play again on the next visit", async () => {
    window.localStorage.setItem(KEY, JSON.stringify({ "7": "filled" }));
    const SettleSweep = await load();
    const { container } = render(
      <SettleSweep orderId={7} status="filled">
        <span>Filled</span>
      </SettleSweep>,
    );
    expect(container.querySelector("[data-settled]")).toBeNull();
  });
});
