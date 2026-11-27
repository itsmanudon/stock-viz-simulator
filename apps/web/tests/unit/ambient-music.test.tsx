import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let pathname = "/";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));

const calls: string[] = [];
vi.mock("@/lib/sound/ambient", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/sound/ambient")>();
  return {
    ...real,
    startAmbient: () => {
      calls.push("start");
      return true;
    },
    stopAmbient: () => calls.push("stop"),
    setAmbientMood: (share: number | null) => calls.push(`mood:${share}`),
  };
});
vi.mock("@/lib/sound/engine", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/sound/engine")>();
  return { ...real, playSound: () => {}, primeSound: () => {} };
});

import { AmbientMood, AmbientMusic } from "@/components/sound/ambient-music";
import { SoundProvider } from "@/components/sound/sound-provider";
import { SoundToggle } from "@/components/sound/sound-toggle";
import { PROGRESSIONS, brightnessFor, moodFor } from "@/lib/sound/ambient";
import { setHarmony, tapNote } from "@/lib/sound/engine";

function page() {
  return render(
    <SoundProvider>
      <SoundToggle />
      <AmbientMusic />
    </SoundProvider>,
  );
}

describe("background music", () => {
  beforeEach(() => {
    calls.length = 0;
    pathname = "/";
    window.localStorage.clear();
  });

  it("stays silent while sound is off", () => {
    page();
    fireEvent.pointerDown(window);
    expect(calls).toEqual([]);
  });

  it("starts after a press once sound is on, and stops when switched off", () => {
    page();
    fireEvent.click(screen.getByRole("switch", { name: "Interface sound" }));
    fireEvent.pointerDown(window);
    expect(calls).toEqual(["start"]);
    fireEvent.click(screen.getByRole("switch"));
    expect(calls).toEqual(["start", "stop"]);
  });

  it("stops when the public pages unmount (signing in)", () => {
    window.localStorage.setItem("stockviz:sound", "on");
    const view = page();
    fireEvent.keyDown(window, { key: "Tab" });
    view.unmount();
    expect(calls).toEqual(["start", "stop"]);
  });

  it("never plays on the log-in form", () => {
    pathname = "/login";
    window.localStorage.setItem("stockviz:sound", "on");
    page();
    fireEvent.pointerDown(window);
    expect(calls).toEqual([]);
  });

  it("hands the hero's breadth to the music and clears it on leave", () => {
    const view = render(<AmbientMood share={0.72} />);
    view.unmount();
    expect(calls).toEqual(["mood:0.72", "mood:null"]);
  });

  it("leans minor and darker when most symbols are down", () => {
    expect(moodFor(0.2)).toBe("low");
    expect(moodFor(0.5)).toBe("even");
    expect(moodFor(0.8)).toBe("high");
    expect(moodFor(null)).toBe("even");
    expect(PROGRESSIONS.high[0].name).toBe("Cmaj9");
    expect(PROGRESSIONS.low[0].name).toBe("Am9");
    expect(brightnessFor(0.1)).toBeLessThan(brightnessFor(0.9));
  });

  it("lets taps walk the current chord, and go back to C5 without music", () => {
    setHarmony([261.63, 329.63, 392]);
    const notes = [tapNote(), tapNote(), tapNote()];
    for (const n of notes) expect(n).toBeGreaterThanOrEqual(350);
    expect(new Set(notes).size).toBe(3);
    act(() => setHarmony(null));
    expect(tapNote()).toBe(523.25);
  });
});
