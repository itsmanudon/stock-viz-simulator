/**
 * /classroom — A10.2 (M12.1, M12.2): cohorts and drill assignments.
 * Instructors create a cohort, share its code, assign a drill recipe and read
 * a process-only gradebook. Students join with the code and their consent,
 * start an assignment (their own anonymised deck) and can leave.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { GradebookTable } from "@/components/classroom/gradebook-table";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { type Cohort, type Gradebook, getGradebook, listCohorts } from "@/lib/api/classroom";

import {
  addAssignmentAction,
  createCohortAction,
  joinCohortAction,
  leaveCohortAction,
  startAssignmentAction,
} from "./actions";

export const metadata: Metadata = { title: "Classroom" };

const CONSENT =
  "Your instructor will see, for each assignment, how many drills you revealed and traded, how many followed your plan and how many plan checks passed. Never your P&L, R, fills, books or the symbols and dates.";

export default async function ClassroomPage({
  searchParams,
}: {
  searchParams: Promise<{ ok?: string; error?: string }>;
}) {
  const { ok, error } = await searchParams;
  const cohorts: Cohort[] = await listCohorts().catch(() => []);
  const books = new Map<number, Gradebook | null>();
  for (const c of cohorts.filter((x) => x.role === "owner")) {
    books.set(c.id, await getGradebook(c.id).catch(() => null));
  }
  const owned = cohorts.filter((c) => c.role === "owner");
  const joined = cohorts.filter((c) => c.role === "member");
  return (
    <div className="w-full space-y-8 px-4 py-6 sm:px-6 lg:py-7 xl:px-8">
      <PageHeader
        eyebrow="Quant Lab"
        title="Classroom"
        description="Cohorts that drill the same anonymised setups. Instructors see how each student followed their plans, never their results."
      />
      {ok ? (
        <output className="block text-sm text-text-secondary" data-testid="classroom-ok">
          {ok}
        </output>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-negative" data-testid="classroom-error">
          {error}
        </p>
      ) : null}

      <section aria-labelledby="join" className="space-y-3">
        <h2 id="join" className="text-base font-semibold">
          Join a Cohort
        </h2>
        <form action={joinCohortAction} className="space-y-2" data-testid="join-form">
          <div className="flex flex-wrap items-end gap-2">
            <div className="space-y-1">
              <Label htmlFor="join-code" className="text-xs">
                Invite Code
              </Label>
              <Input id="join-code" name="code" className="w-40" placeholder="ABCD2345" />
            </div>
            <Button type="submit">Join</Button>
          </div>
          <label className="flex items-start gap-2 text-xs text-text-secondary">
            <input type="checkbox" name="consent" className="mt-0.5" data-testid="join-consent" />
            <span>I agree. {CONSENT}</span>
          </label>
        </form>
        {joined.length ? (
          <ul className="space-y-3" data-testid="joined-cohorts">
            {joined.map((c) => (
              <li key={c.id} className="space-y-2 rounded-xl border border-border bg-card p-4">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-sm font-semibold">{c.name}</h3>
                  <form action={leaveCohortAction}>
                    <input type="hidden" name="cohort_id" value={c.id} />
                    <Button type="submit" variant="outline" size="sm">
                      Leave
                    </Button>
                  </form>
                </div>
                {c.assignments.length === 0 ? (
                  <p className="text-xs text-text-secondary">No assignments yet.</p>
                ) : (
                  <ul className="space-y-2">
                    {c.assignments.map((a) => (
                      <li
                        key={a.id}
                        className="flex flex-wrap items-center justify-between gap-2 text-sm"
                      >
                        <span>
                          {a.title}{" "}
                          <span className="text-2xs text-text-tertiary">
                            {a.k} drills · rubric {a.min_followed_pct}%
                            {a.due_on ? ` · due ${a.due_on}` : ""}
                          </span>
                        </span>
                        {a.my_deck_id ? (
                          <Link href={`/drills?deck=${a.my_deck_id}`} className="text-xs underline">
                            Open My Deck
                          </Link>
                        ) : (
                          <form action={startAssignmentAction}>
                            <input type="hidden" name="assignment_id" value={a.id} />
                            <Button type="submit" size="sm">
                              Start
                            </Button>
                          </form>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      <section aria-labelledby="teach" className="space-y-3">
        <h2 id="teach" className="text-base font-semibold">
          Teach a Cohort
        </h2>
        <form
          action={createCohortAction}
          className="flex flex-wrap items-end gap-2"
          data-testid="create-cohort"
        >
          <div className="space-y-1">
            <Label htmlFor="cohort-name" className="text-xs">
              Cohort Name
            </Label>
            <Input id="cohort-name" name="name" className="w-56" placeholder="Swing 101" />
          </div>
          <Button type="submit" variant="outline">
            Create Cohort
          </Button>
        </form>
        {owned.map((c) => (
          <div
            key={c.id}
            className="space-y-4 rounded-xl border border-border bg-card p-4"
            data-testid="owned-cohort"
          >
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="text-sm font-semibold">{c.name}</h3>
              <p className="text-xs text-text-secondary">
                Invite code{" "}
                <span className="font-mono text-sm text-foreground" data-testid="invite-code">
                  {c.invite_code}
                </span>{" "}
                · {c.members} member{c.members === 1 ? "" : "s"}
              </p>
            </div>
            <details className="text-xs">
              <summary className="cursor-pointer text-text-tertiary hover:text-foreground">
                New Assignment
              </summary>
              <form
                action={addAssignmentAction}
                className="mt-3 grid gap-2 sm:grid-cols-2"
                data-testid="add-assignment"
              >
                <input type="hidden" name="cohort_id" value={c.id} />
                <Input name="title" placeholder="Title, e.g. Breakouts" aria-label="Title" />
                <Input
                  name="rule"
                  placeholder="close crosses_above sma(close, 20)"
                  aria-label="Trigger rule"
                />
                <Input name="tickers" placeholder="Symbols: AAPL, MSFT, KO" aria-label="Symbols" />
                <Input name="k" defaultValue="10" aria-label="Drills" inputMode="numeric" />
                <Input name="from" type="date" aria-label="From" />
                <Input name="to" type="date" aria-label="To" />
                <Input
                  name="min_followed_pct"
                  defaultValue="70"
                  aria-label="Rubric: % of traded drills that follow the plan"
                  inputMode="numeric"
                />
                <Input name="due_on" type="date" aria-label="Due" />
                <Button type="submit" className="sm:col-span-2">
                  Assign
                </Button>
              </form>
            </details>
            {books.get(c.id) ? (
              <GradebookTable book={books.get(c.id) as Gradebook} />
            ) : (
              <p className="text-xs text-text-secondary">The gradebook could not be loaded.</p>
            )}
          </div>
        ))}
      </section>
    </div>
  );
}
