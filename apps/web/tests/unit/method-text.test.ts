import { describe, expect, it } from "vitest";

import { methodParts } from "@/lib/method-text";

describe("methodParts", () => {
  it("turns a Markdown list in a method note into labelled items", () => {
    const { lead, items } = methodParts(
      "Per day: - **ATM IV:** the mean of the call's and put's IV. - **Put-call skew:** IV ``SKEW_OFFSET`` strikes below. - **IV rank** over the stored window.",
    );
    expect(lead).toBe("Per day:");
    expect(items).toEqual([
      { label: "ATM IV", text: "the mean of the call's and put's IV.", joined: false },
      { label: "Put-call skew", text: "IV SKEW_OFFSET strikes below.", joined: false },
      { label: "IV rank", text: "over the stored window.", joined: true },
    ]);
  });

  it("leaves a plain note as its lead", () => {
    expect(methodParts("Closes from stored bars - nothing else.")).toEqual({
      lead: "Closes from stored bars - nothing else.",
      items: [],
    });
  });
});
