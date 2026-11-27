/**
 * /theses — A7.5 (M5.6): your written theses, each with an optional kill
 * rule judged nightly as a linked rule alert (A2.3's engine). A firing
 * notifies once; closing or invalidating is the user's call.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { MetaChip, PageHeader } from "@/components/page-header";
import { ThesisForm } from "@/components/thesis-form";
import { Button } from "@/components/ui/button";
import { formatUtcDateTime } from "@/lib/api-time";
import { type Thesis, listTheses } from "@/lib/api/theses-server";
import { closeThesisAction, removeKillRuleAction } from "./actions";

export const metadata: Metadata = { title: "Theses" };

const KILL_LABEL: Record<Thesis["kill_state"], string> = {
  none: "No kill rule",
  armed: "Kill switch armed",
  paused: "Kill switch paused",
  fired: "Kill rule fired",
};

function ThesisCard({ thesis }: { thesis: Thesis }) {
  return (
    <li className="space-y-2 rounded-lg border border-border-muted p-4" data-testid="thesis-card">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">
          {thesis.ticker ? (
            <Link href={`/stocks/${encodeURIComponent(thesis.ticker)}`} className="hover:underline">
              {thesis.ticker}
            </Link>
          ) : (
            "Unknown symbol"
          )}{" "}
          · {thesis.title}
        </h3>
        <span className="flex flex-wrap gap-2">
          <MetaChip tone={thesis.status === "open" ? "neutral" : "warning"}>
            {thesis.status}
          </MetaChip>
          <MetaChip tone={thesis.kill_state === "fired" ? "warning" : "neutral"}>
            {KILL_LABEL[thesis.kill_state]}
          </MetaChip>
        </span>
      </div>
      <p className="whitespace-pre-wrap text-sm text-text-secondary">{thesis.body}</p>
      {thesis.kill_rule_text ? (
        <p className="font-mono text-xs text-text-tertiary" data-testid="thesis-kill-rule">
          Kill when: {thesis.kill_rule_text}
          {thesis.kill_fired_on ? ` · fired on the ${thesis.kill_fired_on} bar` : ""}
        </p>
      ) : null}
      <p className="text-xs text-text-tertiary">Updated {formatUtcDateTime(thesis.updated_at)}</p>
      {thesis.status === "open" ? (
        <div className="flex flex-wrap gap-2">
          <form action={closeThesisAction}>
            <input type="hidden" name="id" value={thesis.id} />
            <input type="hidden" name="status" value="closed" />
            <Button type="submit" size="sm" variant="outline">
              Close (played out)
            </Button>
          </form>
          <form action={closeThesisAction}>
            <input type="hidden" name="id" value={thesis.id} />
            <input type="hidden" name="status" value="invalidated" />
            <Button type="submit" size="sm" variant="outline">
              Mark invalidated
            </Button>
          </form>
          {thesis.kill_rule_text ? (
            <form action={removeKillRuleAction}>
              <input type="hidden" name="id" value={thesis.id} />
              <Button type="submit" size="sm" variant="ghost">
                Remove kill rule
              </Button>
            </form>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

export default async function ThesesPage() {
  const theses = await listTheses();
  const open = theses.filter((t) => t.status === "open");
  const done = theses.filter((t) => t.status !== "open");
  return (
    <div className="w-full space-y-6 px-4 py-6 sm:px-6 lg:py-7 xl:px-8">
      <PageHeader
        eyebrow="Portfolio & Tax"
        title="Theses"
        description="A written view per stock, with a kill rule that tells you when the reason you bought may be gone."
        meta={<MetaChip>{open.length} open</MetaChip>}
      />
      <section aria-labelledby="new-thesis" className="space-y-3">
        <h2 id="new-thesis" className="text-base font-semibold tracking-tight">
          New thesis
        </h2>
        <ThesisForm />
      </section>
      <section aria-labelledby="open-theses" className="space-y-3">
        <h2 id="open-theses" className="text-base font-semibold tracking-tight">
          Open
        </h2>
        {open.length ? (
          <ul className="space-y-3">
            {open.map((t) => (
              <ThesisCard key={t.id} thesis={t} />
            ))}
          </ul>
        ) : (
          <p className="text-sm text-text-secondary">No open theses yet.</p>
        )}
      </section>
      {done.length ? (
        <section aria-labelledby="closed-theses" className="space-y-3">
          <h2 id="closed-theses" className="text-base font-semibold tracking-tight">
            Closed and invalidated
          </h2>
          <ul className="space-y-3">
            {done.map((t) => (
              <ThesisCard key={t.id} thesis={t} />
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
