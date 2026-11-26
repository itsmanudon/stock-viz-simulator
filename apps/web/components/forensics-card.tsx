/**
 * The forensic scorecard (A7.3, M5.1, M5.2) on the stock page's Financials
 * tab: the Piotroski F-score with each test's result, Altman Z'' (emerging
 * markets), Beneish M and cash flow to profit, on the latest annual facts as
 * known today. Unknown inputs are named, never guessed. Financial companies
 * get the note instead of the models.
 */

import type { Forensics } from "@/lib/api/fundamentals";
import { cn } from "@/lib/utils";

const RESULT_CLASS = {
  pass: "bg-positive",
  fail: "bg-negative",
  unknown: "bg-border-muted",
} as const;

const ZONE_LABEL: Record<string, string> = {
  safe: "Safe zone",
  grey: "Grey zone",
  distress: "Distress zone",
  flag: "Flagged",
  clear: "Not flagged",
  strong: "Cash above profit",
  weak: "Cash below profit",
};

function ScoreLine({
  label,
  score,
  title,
}: {
  label: string;
  score: Forensics["altman_z"];
  title?: string;
}) {
  return (
    <div title={title}>
      <dt className="text-xs text-text-tertiary">{label}</dt>
      <dd className="text-sm">
        {score && score.value !== null && score.value !== undefined ? (
          <>
            <span className="font-mono tabular-nums">{score.value.toFixed(2)}</span>
            {score.zone ? (
              <span className="ml-2 text-xs text-text-secondary">
                {ZONE_LABEL[score.zone] ?? score.zone}
              </span>
            ) : null}
          </>
        ) : (
          <span className="text-xs text-text-tertiary">
            Unknown
            {score?.missing?.length ? `: no ${score.missing.join(", ").replaceAll("_", " ")}` : ""}
          </span>
        )}
      </dd>
    </div>
  );
}

export function ForensicsCard({ forensics }: { forensics: Forensics | null }) {
  if (!forensics) return null;
  return (
    <section aria-labelledby="forensics-title" className="space-y-3" data-testid="forensics-card">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id="forensics-title" className="text-base font-semibold">
          Forensic scorecard
        </h3>
        {forensics.fiscal_year_end ? (
          <span className="text-xs text-text-tertiary">
            Fiscal year to {forensics.fiscal_year_end}, as filed by {forensics.as_of}
          </span>
        ) : null}
      </div>
      {forensics.financial ? (
        <p className="text-sm text-text-secondary" data-testid="forensics-financial">
          {forensics.financial_note}
        </p>
      ) : forensics.reason ? (
        <p className="text-sm text-text-secondary">{forensics.reason}</p>
      ) : (
        <>
          <div>
            <p className="text-sm">
              Piotroski F-score{" "}
              <span className="font-mono tabular-nums" data-testid="forensics-piotroski">
                {forensics.piotroski_score} of {forensics.piotroski_known} known
              </span>
            </p>
            <ul className="mt-2 grid grid-cols-1 gap-1 sm:grid-cols-3">
              {forensics.piotroski.map((t) => (
                <li key={t.key} className="flex items-center gap-2 text-xs" title={t.detail}>
                  <span
                    aria-hidden
                    className={cn("inline-block size-2 rounded-full", RESULT_CLASS[t.result])}
                  />
                  <span className="text-text-secondary">{t.label}</span>
                  <span className="sr-only">: {t.result}</span>
                </li>
              ))}
            </ul>
          </div>
          <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <ScoreLine
              label="Altman Z'' (EM)"
              score={forensics.altman_z}
              title={forensics.method.altman_z}
            />
            <ScoreLine
              label="Beneish M"
              score={forensics.beneish_m}
              title={forensics.method.beneish_m}
            />
            <ScoreLine
              label="Cash flow / profit"
              score={forensics.cfo_to_pat}
              title={forensics.method.cfo_to_pat}
            />
          </dl>
        </>
      )}
      <p className="text-xs text-text-tertiary">{forensics.method.point_in_time}</p>
    </section>
  );
}
