// A10.2: the gradebook shows process counts and grades, and nothing else.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GradebookTable } from "@/components/classroom/gradebook-table";
import type { Gradebook } from "@/lib/api/classroom";

const book: Gradebook = {
  cohort_id: 1,
  assignments: [
    {
      id: 7,
      title: "Breakouts",
      min_followed_pct: 50,
      rule: "close > 1",
      k: 2,
      seed: 9,
      created_at: "2026-11-27T00:00:00",
    },
  ],
  rows: [
    {
      user_id: 2,
      name: "Asha",
      joined_at: "2026-11-27T00:00:00",
      cells: [
        {
          assignment_id: 7,
          started: true,
          drills: 2,
          revealed: 2,
          traded: 2,
          followed_plan: 2,
          checks_passed: 6,
          checks_applicable: 6,
          followed_pct: 100,
          grade: "meets_rubric",
        },
      ],
    },
    {
      user_id: 3,
      name: "Ravi",
      joined_at: "2026-11-27T00:00:00",
      cells: [
        {
          assignment_id: 7,
          started: false,
          drills: 0,
          revealed: 0,
          traded: 0,
          followed_plan: 0,
          checks_passed: 0,
          checks_applicable: 0,
          followed_pct: null,
          grade: "not_started",
        },
      ],
    },
  ],
  rubric: "Meets the rubric when every drill is revealed.",
  privacy:
    "Process counts only. P&L, R, fills, books, symbols and dates never reach the instructor.",
};

describe("GradebookTable", () => {
  it("shows grades and process counts per student", () => {
    render(<GradebookTable book={book} />);
    expect(screen.getAllByTestId("gradebook-row")).toHaveLength(2);
    expect(screen.getByText("Meets Rubric")).toBeTruthy();
    expect(
      screen.getByText(/2\/2 revealed · 2\/2 followed plan \(100%\) · 6\/6 checks/),
    ).toBeTruthy();
    expect(screen.getByText("Not Started")).toBeTruthy();
    expect(screen.getByText(/never reach the instructor/)).toBeTruthy();
  });

  it("says when no student has joined", () => {
    render(<GradebookTable book={{ ...book, rows: [] }} />);
    expect(screen.getByTestId("gradebook-empty")).toBeTruthy();
  });
});
