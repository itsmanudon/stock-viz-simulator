import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { DENSITY_STORAGE_KEY } from "@/components/interface-preferences";
import { InterfacePanel, KeyboardShortcuts } from "@/components/settings-workspace";

describe("InterfacePanel density", () => {
  beforeEach(() => {
    window.localStorage.clear();
    delete document.documentElement.dataset.density;
  });

  afterEach(() => {
    window.localStorage.clear();
    delete document.documentElement.dataset.density;
  });

  it("restores compact density and applies it to the document", async () => {
    window.localStorage.setItem(DENSITY_STORAGE_KEY, "compact");

    render(<InterfacePanel />);

    await waitFor(() => {
      expect(document.documentElement).toHaveAttribute("data-density", "compact");
    });
    expect(screen.getByRole("button", { name: /compact/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("updates the document and local preference when density changes", () => {
    render(<InterfacePanel />);

    fireEvent.click(screen.getByRole("button", { name: /compact/i }));
    expect(document.documentElement).toHaveAttribute("data-density", "compact");
    expect(window.localStorage.getItem(DENSITY_STORAGE_KEY)).toBe("compact");

    fireEvent.click(screen.getByRole("button", { name: /comfortable/i }));
    expect(document.documentElement).toHaveAttribute("data-density", "comfortable");
    expect(window.localStorage.getItem(DENSITY_STORAGE_KEY)).toBe("comfortable");
  });
});

describe("KeyboardShortcuts", () => {
  it("lists the palette shortcuts inline", () => {
    render(<KeyboardShortcuts />);
    expect(screen.getByText("⌘ K / Ctrl K")).toBeVisible();
    expect(screen.getByText("Open the selected symbol")).toBeVisible();
  });
});
