import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ usePathname: () => "/dashboard" }));

const played: string[] = [];
vi.mock("@/lib/sound/engine", () => ({
  playSound: (name: string) => played.push(name),
  primeSound: () => {},
}));

import { SoundProvider, emitSound } from "@/components/sound/sound-provider";
import { SoundToggle } from "@/components/sound/sound-toggle";

describe("PRISM sound", () => {
  beforeEach(() => {
    played.length = 0;
    window.localStorage.clear();
  });

  it("starts off, as a labelled switch, and plays nothing", () => {
    render(
      <SoundProvider>
        <SoundToggle />
        <button type="button">Buy</button>
      </SoundProvider>,
    );
    const toggle = screen.getByRole("switch", { name: "Interface sound" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    fireEvent.click(screen.getByRole("button", { name: "Buy" }));
    act(() => emitSound("fill"));
    expect(played).toEqual([]);
  });

  it("turns on, remembers the choice, and then plays taps and emitted sounds", () => {
    render(
      <SoundProvider>
        <SoundToggle />
        <button type="button">Buy</button>
      </SoundProvider>,
    );
    fireEvent.click(screen.getByRole("switch", { name: "Interface sound" }));
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
    expect(window.localStorage.getItem("stockviz:sound")).toBe("on");
    expect(played).toEqual(["toggleOn"]);

    fireEvent.click(screen.getByRole("button", { name: "Buy" }));
    act(() => emitSound("fill"));
    expect(played).toEqual(["toggleOn", "tap", "fill"]);
  });
});
