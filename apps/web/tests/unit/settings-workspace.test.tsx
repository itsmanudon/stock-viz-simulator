import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { DENSITY_STORAGE_KEY } from "@/components/interface-preferences";
import { SettingsWorkspace } from "@/components/settings-workspace";

describe("SettingsWorkspace interface density", () => {
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

    render(<SettingsWorkspace email="investor@example.com" name="Investor" />);

    await waitFor(() => {
      expect(document.documentElement).toHaveAttribute("data-density", "compact");
    });
    expect(screen.getByRole("button", { name: /compact/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("updates the document and local preference when density changes", () => {
    render(<SettingsWorkspace email="investor@example.com" name="Investor" />);

    fireEvent.click(screen.getByRole("button", { name: /compact/i }));
    expect(document.documentElement).toHaveAttribute("data-density", "compact");
    expect(window.localStorage.getItem(DENSITY_STORAGE_KEY)).toBe("compact");

    fireEvent.click(screen.getByRole("button", { name: /comfortable/i }));
    expect(document.documentElement).toHaveAttribute("data-density", "comfortable");
    expect(window.localStorage.getItem(DENSITY_STORAGE_KEY)).toBe("comfortable");
  });
});
