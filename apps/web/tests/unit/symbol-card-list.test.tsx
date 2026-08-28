import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CardSortBar, type SymbolCardData, SymbolCardList } from "@/components/symbol-card-list";

const rows: SymbolCardData[] = [
  {
    ticker: "AAPL",
    name: "Apple Inc.",
    price: "$188.38",
    changePct: -7.29,
    changeLabel: "-7.29%",
    metrics: [
      { label: "RSI 14", value: "25.2" },
      { label: "52w Low", value: "$165.00" },
      { label: "52w High", value: "$259.02" },
    ],
  },
  {
    ticker: "BAC",
    name: "Bank of America Corporation",
    price: "$35.58",
    changePct: 3.46,
    changeLabel: "+3.46%",
  },
];

describe("SymbolCardList", () => {
  it("renders one linked card per symbol", () => {
    render(<SymbolCardList rows={rows} />);

    expect(screen.getByRole("link", { name: /AAPL/ })).toHaveAttribute("href", "/stocks/AAPL");
    expect(screen.getByRole("link", { name: /BAC/ })).toHaveAttribute("href", "/stocks/BAC");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("tints the change pill by direction", () => {
    render(<SymbolCardList rows={rows} />);

    expect(screen.getByText("-7.29%")).toHaveClass("bg-negative-soft");
    expect(screen.getByText("+3.46%")).toHaveClass("bg-positive-soft");
  });

  it("keeps every table figure available rather than dropping columns", () => {
    render(<SymbolCardList rows={rows} />);
    const card = screen.getByRole("link", { name: /AAPL/ });

    for (const text of ["25.2", "$165.00", "$259.02", "$188.38"]) {
      expect(within(card).getByText(text)).toBeVisible();
    }
  });

  it("renders an em dash when a symbol has no price", () => {
    render(<SymbolCardList rows={[{ ...rows[1], price: null, changeLabel: null }]} />);
    expect(screen.getByText("—")).toBeVisible();
  });
});

describe("CardSortBar", () => {
  const options = [
    { key: "ticker", label: "Ticker", href: "/markets?sort=ticker&dir=desc" },
    { key: "price", label: "Price", href: "/markets?sort=price&dir=desc" },
  ];

  it("marks the active sort and shows its direction", () => {
    render(<CardSortBar options={options} activeKey="price" direction="asc" />);

    const active = screen.getByRole("link", { name: /Price/ });
    expect(active).toHaveAttribute("aria-current", "true");
    expect(active).toHaveTextContent("↑");
    expect(screen.getByRole("link", { name: "Ticker" })).not.toHaveAttribute("aria-current");
  });

  it("links each option so sorting works without JavaScript", () => {
    render(<CardSortBar options={options} activeKey="ticker" direction="desc" />);
    expect(screen.getByRole("link", { name: "Price" })).toHaveAttribute(
      "href",
      "/markets?sort=price&dir=desc",
    );
  });
});
