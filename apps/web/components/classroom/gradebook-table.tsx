/**
 * A10.2 (M12.2): the instructor's gradebook. Process counts only, by design:
 * the API sends no money, R, fills, symbols or dates, and this table shows
 * only what it sends.
 */

import type { Gradebook } from "@/lib/api/classroom";

export const GRADE_LABEL: Record<string, string> = {
  not_started: "Not Started",
  in_progress: "In Progress",
  meets_rubric: "Meets Rubric",
  below_rubric: "Below Rubric",
};

export function GradebookTable({ book }: { book: Gradebook }) {
  if (book.rows.length === 0) {
    return (
      <p className="text-sm text-text-secondary" data-testid="gradebook-empty">
        No students yet. Share the invite code.
      </p>
    );
  }
  return (
    <div className="space-y-2">
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm" data-testid="gradebook">
          <thead className="text-2xs text-text-tertiary">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Student</th>
              {book.assignments.map((a) => (
                <th key={a.id} className="px-3 py-2 text-left font-medium">
                  {a.title} (≥{a.min_followed_pct}%)
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {book.rows.map((r) => (
              <tr key={r.user_id} className="border-t border-border" data-testid="gradebook-row">
                <td className="px-3 py-2">{r.name}</td>
                {r.cells.map((c) => (
                  <td key={c.assignment_id} className="px-3 py-2 text-xs" data-grade={c.grade}>
                    <span className="font-medium">{GRADE_LABEL[c.grade] ?? c.grade}</span>
                    {c.started ? (
                      <span className="block text-text-tertiary">
                        {c.revealed}/{c.drills} revealed · {c.followed_plan}/{c.traded} followed
                        plan
                        {c.followed_pct != null ? ` (${Math.round(c.followed_pct)}%)` : ""} ·{" "}
                        {c.checks_passed}/{c.checks_applicable} checks
                      </span>
                    ) : null}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-2xs text-text-tertiary">{book.rubric}</p>
      <p className="text-2xs text-text-tertiary">{book.privacy}</p>
    </div>
  );
}
