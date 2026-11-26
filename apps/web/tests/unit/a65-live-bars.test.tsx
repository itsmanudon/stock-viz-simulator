import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PriceChart } from "@/components/price-chart";

import type { Bar } from "@/lib/api/types";

import {
  type LiveBarEvent,
  liveStatusText,
  liveStreamUrl,
  mergeLiveBar,
  parseLiveBar,
} from "@/lib/live-bars";

const NY = "America/New_York";

function bar(ts: string, closed: string, extra: Partial<Bar> = {}): Bar {
  return {
    ts,
    closed_at: closed,
    open: "10",
    high: "11",
    low: "9",
    close: "10.5",
    volume: 100,
    feed: "iex",
    badge: "IEX only",
    minutes: 1,
    session_date: "2026-01-06",
    ...extra,
  };
}

function ev(ts: string, closed: string, over: Partial<LiveBarEvent> = {}): LiveBarEvent {
  return {
    ticker: "AAPL",
    feed: "iex",
    badge: "IEX only",
    interval: "1m",
    ts,
    closed_at: closed,
    open: "10.5",
    high: "12",
    low: "8",
    close: "11",
    volume: 7,
    replayed: false,
    ...over,
  };
}

describe("mergeLiveBar", () => {
  const one = [bar("2026-01-06T15:00:00Z", "2026-01-06T15:01:00Z")];

  it("appends the next minute on a 1-minute chart and keeps the length", () => {
    const next = mergeLiveBar(one, ev("2026-01-06T15:01:00Z", "2026-01-06T15:02:00Z"), "1m", NY);
    expect(next).toHaveLength(1);
    expect(next[0]).toMatchObject({ ts: "2026-01-06T15:01:00Z", close: "11", volume: 7 });
    expect(next[0].session_date).toBe("2026-01-06");
  });

  it("replaces the newest minute when it comes again and ignores older ones", () => {
    const same = mergeLiveBar(one, ev("2026-01-06T15:00:00Z", "2026-01-06T15:01:00Z"), "1m", NY);
    expect(same[0].close).toBe("11");
    expect(mergeLiveBar(one, ev("2026-01-06T14:59:00Z", "2026-01-06T15:00:00Z"), "1m")).toBe(one);
  });

  it("ignores another feed's bars", () => {
    const other = ev("2026-01-06T15:01:00Z", "2026-01-06T15:02:00Z", { feed: "replayed" });
    expect(mergeLiveBar(one, other, "1m")).toBe(one);
  });

  it("folds a minute into the open 5-minute bar, once", () => {
    const five = [bar("2026-01-06T15:00:00Z", "2026-01-06T15:05:00Z", { minutes: 2 })];
    // 15:01 is already in the server's bar (2 minutes held).
    expect(mergeLiveBar(five, ev("2026-01-06T15:01:00Z", "2026-01-06T15:02:00Z"), "5m")).toBe(five);
    const merged = mergeLiveBar(five, ev("2026-01-06T15:02:00Z", "2026-01-06T15:03:00Z"), "5m");
    expect(merged[0]).toMatchObject({
      ts: "2026-01-06T15:00:00Z",
      high: "12",
      low: "8",
      close: "11",
      volume: 107,
      minutes: 3,
      partial: true,
    });
    const closing = mergeLiveBar(merged, ev("2026-01-06T15:04:00Z", "2026-01-06T15:05:00Z"), "5m");
    expect(closing[0].partial).toBe(false);
  });

  it("opens the next bucket from the newest bar's close, or a new session's at its time", () => {
    const five = [bar("2026-01-06T15:00:00Z", "2026-01-06T15:05:00Z", { minutes: 5 })];
    const later = mergeLiveBar(five, ev("2026-01-06T15:11:00Z", "2026-01-06T15:12:00Z"), "5m");
    expect(later[0]).toMatchObject({
      ts: "2026-01-06T15:10:00Z",
      closed_at: "2026-01-06T15:15:00Z",
      partial: true,
    });
    const nextDay = mergeLiveBar(
      five,
      ev("2026-01-07T14:30:00Z", "2026-01-07T14:31:00Z"),
      "5m",
      NY,
    );
    expect(nextDay[0]).toMatchObject({ ts: "2026-01-07T14:30:00Z", session_date: "2026-01-07" });
  });

  it("does nothing on a daily chart or with no bars", () => {
    expect(mergeLiveBar(one, ev("2026-01-06T15:01:00Z", "2026-01-06T15:02:00Z"), "1d")).toBe(one);
    expect(mergeLiveBar([], ev("2026-01-06T15:01:00Z", "2026-01-06T15:02:00Z"), "1m")).toEqual([]);
  });
});

describe("parsing and words", () => {
  it("parses a stream event and refuses junk", () => {
    const raw = JSON.stringify(ev("2026-01-06T15:01:00Z", "2026-01-06T15:02:00Z"));
    expect(parseLiveBar(raw)?.ticker).toBe("AAPL");
    expect(parseLiveBar("{")).toBeNull();
    expect(parseLiveBar(JSON.stringify({ ticker: "AAPL" }))).toBeNull();
  });

  it("builds the stream URL", () => {
    expect(liveStreamUrl("http://api.test/", "TCS.NS")).toBe(
      "http://api.test/v1/stream/bars?tickers=TCS.NS",
    );
  });

  it("never calls a replayed stream live", () => {
    const at = "2026-01-06T15:02:00Z";
    expect(liveStatusText("live", at, true, NY)).toBe("Replayed stream, not live: last bar 10:02.");
    expect(liveStatusText("live", at, false, NY)).toBe("Live: last bar 10:02.");
    expect(liveStatusText("offline", null, false, NY)).toMatch(/offline/);
    expect(liveStatusText("waiting", null, false, NY)).toMatch(/Live updates on/);
  });
});

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("next-themes", () => ({ useTheme: () => ({ resolvedTheme: "dark" }) }));
vi.mock("lightweight-charts", async () => (await import("../stubs/lightweight-charts")).lwc);

class FakeEventSource {
  static last: FakeEventSource | null = null;
  url: string;
  listeners: Record<string, ((e: MessageEvent<string>) => void)[]> = {};
  closed = false;
  constructor(url: string) {
    this.url = url;
    FakeEventSource.last = this;
  }
  addEventListener(name: string, fn: (e: MessageEvent<string>) => void) {
    this.listeners[name] = [...(this.listeners[name] ?? []), fn];
  }
  removeEventListener() {}
  close() {
    this.closed = true;
  }
  emit(name: string, data = "") {
    for (const fn of this.listeners[name] ?? []) fn({ data } as MessageEvent<string>);
  }
}

describe("PriceChart live updates (A6.5)", () => {
  beforeEach(async () => {
    (await import("../stubs/lightweight-charts")).resetLwc();
    vi.stubGlobal("EventSource", FakeEventSource);
  });
  afterEach(() => vi.unstubAllGlobals());

  const bars = [
    bar("2026-01-06T15:00:00Z", "2026-01-06T15:01:00Z", { feed: "replayed", badge: "Replayed" }),
  ];

  it("streams bars into an intraday chart and says a replay is not live", () => {
    render(
      <PriceChart
        bars={bars}
        interval="1m"
        timeZone={NY}
        sourceFeed="replayed"
        liveTicker="AAPL"
      />,
    );
    const source = FakeEventSource.last;
    expect(source?.url).toMatch(/\/v1\/stream\/bars\?tickers=AAPL$/);
    expect(screen.getByTestId("chart-live-status").dataset.status).toBe("connecting");
    act(() => source?.emit("open"));
    expect(screen.getByTestId("chart-live-status")).toHaveTextContent(/Live updates on/);
    const event = ev("2026-01-06T15:01:00Z", "2026-01-06T15:02:00Z", {
      feed: "replayed",
      badge: "Replayed",
      replayed: true,
    });
    act(() => source?.emit("bar", JSON.stringify(event)));
    const status = screen.getByTestId("chart-live-status");
    expect(status.dataset.status).toBe("live");
    expect(status).toHaveTextContent("Replayed stream, not live: last bar 10:02.");
    expect(screen.getByTestId("chart-source-badge")).toHaveTextContent("Replayed");
    act(() => source?.emit("error"));
    expect(screen.getByTestId("chart-live-status")).toHaveTextContent(/offline/);
  });

  it("opens no stream on a daily chart or without a ticker", () => {
    FakeEventSource.last = null;
    render(<PriceChart bars={bars} interval="1d" liveTicker="AAPL" />);
    render(<PriceChart bars={bars} interval="1m" timeZone={NY} sourceFeed="iex" />);
    expect(FakeEventSource.last).toBeNull();
    expect(screen.queryByTestId("chart-live-status")).toBeNull();
  });
});
