import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SentimentBadge } from "@/components/sentiment-badge";

describe("SentimentBadge", () => {
  it("shows the mixed label Aegis emits (audit AG-4)", () => {
    render(<SentimentBadge sentiment="mixed" />);
    const badge = screen.getByLabelText("Sentiment: Mixed");
    expect(badge).toHaveTextContent("Mixed");
    expect(badge.className).toContain("bg-warning-soft");
  });

  it("renders nothing without a label", () => {
    const { container } = render(<SentimentBadge sentiment={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
