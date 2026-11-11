import { TriangleAlert } from "lucide-react";

import type { ValuationWarning } from "@/lib/api/trading";

/**
 * Says when the portfolio value leaves something out (audit LG-13): a holding
 * without a stored close or an unpriceable option counts as 0, and an amount
 * without an FX rate is added unconverted. Renders nothing when complete.
 */
export function ValuationNotice({
  warnings,
  className = "",
}: {
  warnings: ValuationWarning[] | undefined;
  className?: string;
}) {
  if (!warnings || warnings.length === 0) return null;
  return (
    <div
      role="note"
      aria-label="Portfolio value is incomplete"
      className={`flex items-start gap-2.5 rounded-md border border-warning/40 bg-warning-soft px-3 py-2.5 text-xs text-warning-soft-foreground ${className}`}
    >
      <TriangleAlert aria-hidden className="mt-px size-3.5 shrink-0" />
      <div className="min-w-0">
        <p className="font-medium">This value is incomplete.</p>
        <ul className="mt-1 space-y-0.5">
          {warnings.map((warning) => (
            <li key={`${warning.code}:${warning.subject}`}>{warning.message}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
