/**
 * A4.2: every fee schedule with its dated versions, each component's rate,
 * side and source (the /docs/costs page and nothing else).
 */

import { FeeComponentRows } from "@/components/costs-disclosure";
import { DocSection, P } from "@/components/docs/docs-ui";
import { type FeeSchedules, formatDay, inForce, versionRange } from "@/lib/fees";

const SEGMENT: Record<string, string> = {
  equity_delivery: "Equity delivery",
  equity_intraday: "Equity intraday",
  futures: "Futures",
  options: "Options",
  equity: "Equity",
};

export function CostsSchedules({ schedules, today }: { schedules: FeeSchedules; today: string }) {
  // Indian schedules first: they are the ones on by default.
  const listed = schedules.schedules
    .filter((s) => s.versions.length > 0)
    .sort((a, b) => Number(b.market === "IN") - Number(a.market === "IN"));
  return (
    <>
      {listed.map((s) => (
        <DocSection key={s.name} title={s.label}>
          <div className="space-y-3 text-sm" data-testid={`fee-schedule-${s.name}`}>
            <p className="text-xs text-text-tertiary">
              <span className="font-mono">{s.name}</span>
              {s.aliases.length ? ` (also ${s.aliases.join(", ")})` : ""} ·{" "}
              {SEGMENT[s.segment] ?? s.segment} · {s.currency}
              {s.default_for.length ? ` · default for ${s.default_for.join(", ")}` : ""}
              {s.coverage_from ? ` · rates confirmed from ${formatDay(s.coverage_from)}` : ""}
            </p>
            {s.brokerage.length ? (
              <ul className="text-xs text-text-secondary">
                {s.brokerage.map((b) => (
                  <li key={b.key}>
                    Brokerage, {b.key === "zero" ? "none" : b.label}: {b.rate_text}
                    {b.source ? (
                      <>
                        {" "}
                        (
                        <a
                          href={b.source.url}
                          target="_blank"
                          rel="noreferrer"
                          className="underline underline-offset-2"
                        >
                          source
                        </a>
                        )
                      </>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : null}
            {[...s.versions].reverse().map((v) => (
              <details
                key={v.effective_from}
                open={inForce(v, today)}
                className="rounded-xl border border-border-muted bg-card px-3 py-2 text-xs"
              >
                <summary className="cursor-pointer font-medium">
                  In force {versionRange(v)}
                  {inForce(v, today) ? " · in force today" : ""}
                </summary>
                <FeeComponentRows components={v.components} />
                {v.notes.map((n) => (
                  <p key={n} className="mt-1 text-text-tertiary">
                    {n}
                  </p>
                ))}
              </details>
            ))}
            {s.notes.map((n) => (
              <p key={n} className="text-xs text-text-tertiary">
                {n}
              </p>
            ))}
          </div>
        </DocSection>
      ))}
      <DocSection title="Notes">
        {schedules.notes.map((n) => (
          <P key={n}>{n}</P>
        ))}
      </DocSection>
    </>
  );
}
