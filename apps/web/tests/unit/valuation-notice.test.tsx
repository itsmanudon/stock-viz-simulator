import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ValuationNotice } from "@/components/valuation-notice";

describe("ValuationNotice (audit LG-13)", () => {
  it("lists what the value leaves out", () => {
    render(
      <ValuationNotice
        warnings={[
          {
            code: "no_close",
            subject: "MSFT",
            message: "MSFT has no stored close, so the holding is valued at 0.",
          },
        ]}
      />,
    );

    expect(screen.getByRole("note", { name: "Portfolio value is incomplete" })).toBeVisible();
    expect(screen.getByText(/MSFT has no stored close/)).toBeVisible();
  });

  it("renders nothing for a complete value or an older API", () => {
    const { container, rerender } = render(<ValuationNotice warnings={[]} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<ValuationNotice warnings={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });
});
