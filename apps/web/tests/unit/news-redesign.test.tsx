import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import { NewsFeed } from "@/components/news/news-feed";
import { NewsSearchShortcut } from "@/components/news/news-search-shortcut";
import type { NewsFeedItem } from "@/lib/api/news";
import { newsCommandsFor } from "@/lib/command-palette";
import {
  activeFilterCount,
  groupByDay,
  groupStories,
  headlineWords,
  newsApiParams,
  newsHref,
  parseNewsQuery,
  signedPct,
  similarity,
  sparkPath,
  sparkPoint,
  toggled,
} from "@/lib/news-view";

function item(id: string, at: string, overrides: Partial<NewsFeedItem> = {}): NewsFeedItem {
  return {
    id,
    tickers: ["AAPL"],
    title: `Headline ${id}`,
    url: `https://news.example.test/${id}`,
    source: "Reuters",
    published_at: null,
    available_at: at,
    sentiment: null,
    sentiment_model: null,
    topic: null,
    reactions: [],
    ...overrides,
  };
}

describe("news URL state", () => {
  it("parses filters and drops what it does not know", () => {
    const q = parseNewsQuery({
      q: "  earnings guidance ",
      tickers: "aapl,msft,AAPL",
      sentiment: "positive,bullish,unscored",
      scope: "nope",
      from: "2026-11-01",
      to: "26/11/2026",
      lens: "mine",
    });
    expect(q.q).toBe("earnings guidance");
    expect(q.tickers).toEqual(["AAPL", "MSFT"]);
    expect(q.sentiment).toEqual(["positive", "unscored"]);
    expect(q.scope).toBe("symbols");
    expect(q.from).toBe("2026-11-01");
    expect(q.to).toBeNull();
    expect(q.lens).toBe("mine");
  });

  it("reads the old page's ?view=market as the market scope", () => {
    expect(parseNewsQuery({ view: "market" }).scope).toBe("market");
  });

  it("writes stable URLs and resets paging on any change", () => {
    const q = parseNewsQuery({ tickers: "AAPL", cursor: "abc", sentiment: "negative" });
    expect(newsHref(q)).toBe("/news?tickers=AAPL&sentiment=negative");
    expect(newsHref(q, { cursor: "next" })).toBe(
      "/news?tickers=AAPL&sentiment=negative&cursor=next",
    );
    expect(newsHref(parseNewsQuery({}))).toBe("/news");
    expect(newsHref(q, { lens: "mine" })).toBe("/news?lens=mine&sentiment=negative");
  });

  it("toggles chips and counts active filters", () => {
    expect(toggled(["a", "b"], "a")).toEqual(["b"]);
    expect(toggled(["a"], "b")).toEqual(["a", "b"]);
    expect(activeFilterCount(parseNewsQuery({}))).toBe(0);
    expect(
      activeFilterCount(
        parseNewsQuery({ q: "x", tickers: "A", from: "2026-01-01", to: "2026-02-01" }),
      ),
    ).toBe(3);
  });

  it("sends the lens's tickers to the API and never market scope with tickers", () => {
    const q = parseNewsQuery({ lens: "mine", scope: "market" });
    const params = newsApiParams(q, ["AAPL", "INFY.NS"], 40);
    expect(params.get("tickers")).toBe("AAPL,INFY.NS");
    expect(params.get("scope")).toBe("symbols");
    expect(params.get("limit")).toBe("40");
  });
});

describe("stories", () => {
  it("compares headline words, ignoring stopwords and punctuation", () => {
    const a = headlineWords("Apple beats estimates as iPhone sales jump");
    const b = headlineWords("Apple beats estimates, iPhone sales jump 8%");
    expect(similarity(a, b)).toBeGreaterThan(0.6);
    expect(similarity(a, headlineWords("Microsoft cloud growth slows"))).toBe(0);
  });

  it("groups the same story on the same day and tickers, newest leading", () => {
    const items = [
      item("1", "2026-11-03T14:00:00", { title: "Apple beats estimates as iPhone sales jump" }),
      item("2", "2026-11-03T13:00:00", {
        title: "Apple beats estimates, iPhone sales jump",
        source: "Bloomberg",
      }),
      item("3", "2026-11-03T12:00:00", { title: "Apple faces EU probe over App Store" }),
      // Same words and day, other tickers: a new story.
      item("5", "2026-11-03T11:00:00", {
        title: "Apple beats estimates as iPhone sales jump",
        tickers: ["MSFT"],
      }),
      // Same words, another day: a new story.
      item("4", "2026-11-02T12:00:00", { title: "Apple beats estimates as iPhone sales jump" }),
    ];
    const stories = groupStories(items);
    expect(stories.map((s) => [s.lead.id, s.others.map((o) => o.id)])).toEqual([
      ["1", ["2"]],
      ["3", []],
      ["5", []],
      ["4", []],
    ]);

    const days = groupByDay(stories);
    expect(days.map((d) => d.date)).toEqual(["2026-11-03", "2026-11-02"]);
    // The day's tone counts every headline, grouped ones too.
    expect(days[0].tone.unscored).toBe(4);
  });
});

describe("geometry and figures", () => {
  it("draws a sparkline inside its box and finds the reaction point", () => {
    expect(sparkPath([1, 3, 2], 44, 16)).toBe("M2.0 14.0 L22.0 2.0 L42.0 8.0");
    expect(sparkPath([5], 44, 16)).toBe("");
    expect(sparkPoint([1, 3, 2], 1, 44, 16)).toEqual({ x: 22, y: 2 });
    expect(sparkPoint([1, 3], 5, 44, 16)).toBeNull();
  });

  it("writes signed percentages with a real minus", () => {
    expect(signedPct(1.234)).toBe("+1.23%");
    expect(signedPct(-3.1)).toBe("−3.10%");
    expect(signedPct(0)).toBe("0.00%");
    expect(signedPct(null)).toBe("—");
  });

  it("offers News: TICKER commands for the palette's symbol matches", () => {
    const commands = newsCommandsFor(["AAPL", "MSFT", "INFY.NS", "TCS.NS"]);
    expect(commands.map((c) => c.label)).toEqual(["News: AAPL", "News: MSFT", "News: INFY.NS"]);
    expect(commands[2].href).toBe("/news?tickers=INFY.NS");
  });
});

describe("NewsFeed", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.useFakeTimers();
  });
  afterEach(() => vi.useRealTimers());

  const feed = () => {
    const items = [
      item("n1", "2026-11-04T15:00:00", {
        title: "Apple beats estimates as iPhone sales jump",
        sentiment: "positive",
        reactions: [
          {
            ticker: "AAPL",
            session_date: "2026-11-04",
            change_pct: 2.41,
            closes: [100, 101, 103.4],
            reaction_index: 2,
          },
        ],
      }),
      item("n2", "2026-11-04T14:00:00", {
        title: "Apple beats estimates, iPhone sales jump",
        source: "Bloomberg",
      }),
      item("n3", "2026-11-02T10:00:00", { title: "Apple faces EU probe", sentiment: "negative" }),
    ];
    return groupByDay(groupStories(items));
  };

  it("shows each move with its session and says it is not a cause", () => {
    render(<NewsFeed days={feed()} isFirstPage />);
    const chip = screen.getByTestId("news-reaction");
    expect(chip).toHaveTextContent("AAPL");
    expect(chip).toHaveTextContent("▲ +2.41%");
    expect(chip.getAttribute("title")).toMatch(/first session after this headline/);
    expect(chip.getAttribute("title")).toMatch(/Association, not cause/);
    expect(screen.getByTestId("news-story-more")).toHaveTextContent("+1 more source");
    expect(screen.getAllByRole("link", { name: /opens the original/ })[0]).toHaveAttribute(
      "rel",
      "noopener noreferrer",
    );
  });

  it("marks headlines newer than the last visit, then remembers this one", () => {
    window.localStorage.setItem("stockviz:news-last-seen", "2026-11-03T00:00:00");
    render(<NewsFeed days={feed()} isFirstPage />);
    expect(screen.getByTestId("news-new-banner")).toHaveTextContent("2 new since your last visit");
    expect(screen.getAllByTestId("news-new-dot")).toHaveLength(1); // the story's lead only
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(window.localStorage.getItem("stockviz:news-last-seen")).toBe("2026-11-04T15:00:00");
  });

  it("leaves the marker alone on older pages", () => {
    window.localStorage.setItem("stockviz:news-last-seen", "2026-11-03T00:00:00");
    render(<NewsFeed days={feed()} isFirstPage={false} />);
    expect(screen.queryByTestId("news-new-banner")).toBeNull();
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(window.localStorage.getItem("stockviz:news-last-seen")).toBe("2026-11-03T00:00:00");
  });

  it("moves between headlines with j and k", () => {
    render(<NewsFeed days={feed()} isFirstPage />);
    const rows = document.querySelectorAll<HTMLElement>("[data-news-row]");
    fireEvent.keyDown(window, { key: "j" });
    expect(document.activeElement).toBe(rows[0]);
    fireEvent.keyDown(window, { key: "j" });
    expect(document.activeElement).toBe(rows[1]);
    fireEvent.keyDown(window, { key: "k" });
    expect(document.activeElement).toBe(rows[0]);
    expect(within(rows[1]).getByText("Apple faces EU probe")).toBeInTheDocument();
  });
});

describe("NewsSearchShortcut", () => {
  it("focuses the headline search on / and keeps the key from the palette", () => {
    const palette = vi.fn();
    window.addEventListener("keydown", palette);
    render(
      <>
        <input id="news-q" aria-label="Search Headlines" />
        <NewsSearchShortcut />
      </>,
    );
    fireEvent.keyDown(document.body, { key: "/" });
    expect(document.activeElement).toBe(screen.getByLabelText("Search Headlines"));
    expect(palette).not.toHaveBeenCalled();
    // Typing "/" in a field is just a character.
    fireEvent.keyDown(screen.getByLabelText("Search Headlines"), { key: "/" });
    expect(palette).toHaveBeenCalledTimes(1);
    window.removeEventListener("keydown", palette);
  });
});
