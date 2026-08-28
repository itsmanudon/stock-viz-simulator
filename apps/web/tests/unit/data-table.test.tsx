import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { NumericCell, SortableHead, TableToolbar, toneForValue } from "@/components/data-table";
import { StatusBadge } from "@/components/status-badge";
import { Table, TableBody, TableHeader, TableRow } from "@/components/ui/table";

function inRow(cell: React.ReactNode) {
  return render(
    <Table>
      <TableBody>
        <TableRow>{cell}</TableRow>
      </TableBody>
    </Table>,
  );
}

describe("toneForValue", () => {
  it("maps sign to tone and treats missing data as neutral", () => {
    expect(toneForValue(1.5)).toBe("positive");
    expect(toneForValue(-1.5)).toBe("negative");
    expect(toneForValue(0)).toBe("neutral");
    expect(toneForValue(null)).toBe("neutral");
    expect(toneForValue(Number.NaN)).toBe("neutral");
  });
});

describe("NumericCell", () => {
  it("colours by the sign of signedBy, using tokens rather than raw palette classes", () => {
    const { container } = inRow(<NumericCell signedBy={2.4}>+2.40%</NumericCell>);
    const cell = container.querySelector("td");

    expect(cell).toHaveClass("text-positive");
    expect(cell?.className).not.toMatch(/text-(green|red)-\d/);
  });

  it("uses the negative token for losses", () => {
    const { container } = inRow(<NumericCell signedBy={-2.4}>-2.40%</NumericCell>);
    expect(container.querySelector("td")).toHaveClass("text-negative");
  });

  it("leaves untinted figures neutral when no sign is given", () => {
    const { container } = inRow(<NumericCell>$188.38</NumericCell>);
    const cell = container.querySelector("td");

    expect(cell).toHaveClass("text-foreground");
    expect(cell).not.toHaveClass("text-positive");
  });

  it("renders an em dash in muted text for missing values", () => {
    const { container } = inRow(<NumericCell signedBy={null}>{null}</NumericCell>);
    const cell = container.querySelector("td");

    expect(cell).toHaveTextContent("—");
    expect(cell).toHaveClass("text-text-tertiary");
  });

  it("marks cells as financial so tabular numerals apply", () => {
    const { container } = inRow(<NumericCell>1,234.50</NumericCell>);
    expect(container.querySelector("td")).toHaveAttribute("data-financial");
  });
});

describe("SortableHead", () => {
  function head(direction: "asc" | "desc" | null) {
    return render(
      <Table>
        <TableHeader>
          <TableRow>
            <SortableHead href="/markets?sort=price&dir=asc" label="Price" direction={direction} />
          </TableRow>
        </TableHeader>
      </Table>,
    );
  }

  it("reports the active sort direction to assistive tech", () => {
    const { container, rerender } = head("asc");
    expect(container.querySelector("th")).toHaveAttribute("aria-sort", "ascending");

    rerender(
      <Table>
        <TableHeader>
          <TableRow>
            <SortableHead href="/markets?sort=price&dir=asc" label="Price" direction="desc" />
          </TableRow>
        </TableHeader>
      </Table>,
    );
    expect(container.querySelector("th")).toHaveAttribute("aria-sort", "descending");
  });

  it("reports 'none' for a column that isn't the active sort", () => {
    const { container } = head(null);
    expect(container.querySelector("th")).toHaveAttribute("aria-sort", "none");
  });

  it("links to the next sort state so it works without JavaScript", () => {
    head("asc");
    expect(screen.getByRole("link", { name: "Price" })).toHaveAttribute(
      "href",
      "/markets?sort=price&dir=asc",
    );
  });
});

describe("TableToolbar", () => {
  it("keeps controls and actions in separate groups", () => {
    render(
      <TableToolbar actions={<button type="button">Add</button>}>
        <span>12 matches</span>
      </TableToolbar>,
    );

    expect(screen.getByText("12 matches")).toBeVisible();
    expect(screen.getByRole("button", { name: "Add" })).toBeVisible();
  });

  it("omits the actions group entirely when there are none", () => {
    render(
      <TableToolbar>
        <span>12 matches</span>
      </TableToolbar>,
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("StatusBadge", () => {
  it("applies the tone's token classes", () => {
    render(<StatusBadge label="filled" tone="positive" />);
    expect(screen.getByText("filled")).toHaveClass("bg-positive/15", "text-positive");
  });

  it("defaults to the neutral tone", () => {
    render(<StatusBadge label="cancelled" />);
    expect(screen.getByText("cancelled")).toHaveClass("bg-surface-secondary");
  });
});

describe("order and alert badges", () => {
  it("keeps the buy/sell and alert-state tone mapping after consolidation", async () => {
    const { OrderSideBadge, OrderStatusBadge, AlertStatusBadge } = await import(
      "@/components/operational-page-header"
    );

    const { container } = render(
      <div>
        <OrderSideBadge side="buy" />
        <OrderSideBadge side="sell" />
        <OrderStatusBadge status="filled" />
        <OrderStatusBadge status="pending" />
        <AlertStatusBadge triggered={false} dismissed={false} />
        <AlertStatusBadge triggered dismissed={false} />
        <AlertStatusBadge triggered dismissed />
      </div>,
    );

    const scope = within(container);
    expect(scope.getByText("buy")).toHaveClass("text-positive");
    expect(scope.getByText("sell")).toHaveClass("text-negative");
    expect(scope.getByText("filled")).toHaveClass("text-positive");
    expect(scope.getByText("pending")).toHaveClass("text-brand");
    expect(scope.getByText("Active")).toHaveClass("text-brand");
    expect(scope.getByText("Triggered")).toHaveClass("text-positive");
    expect(scope.getByText("Dismissed")).toHaveClass("text-text-secondary");
  });
});
