// A7.5: the thesis form explains the kill rule and posts the fields the action reads.
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/(product)/(authed)/theses/actions", () => ({
  createThesisAction: vi.fn(async () => ({})),
}));

import { ThesisForm } from "@/components/thesis-form";

describe("ThesisForm", () => {
  it("has the ticker, title, body and kill rule fields", () => {
    render(<ThesisForm />);
    for (const name of ["ticker", "title", "body", "kill_rule"]) {
      expect(document.querySelector(`[name="${name}"]`)).not.toBeNull();
    }
    expect(screen.getByText(/notified once/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Save thesis" })).toBeEnabled();
  });
});
