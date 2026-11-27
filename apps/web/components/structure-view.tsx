/**
 * Honest structure annotations (A9.5, M2.12) on the stock page's Research
 * tab: support and resistance zones from clustered pivots and the latest
 * swing pivots with their HH/LH/HL/LL labels. Every mark states the rule that
 * drew it; nothing repaints.
 */

import type { Structure } from "@/lib/api/research-views";
import { cn } from "@/lib/utils";

export function StructureView({ structure }: { structure: Structure }) {
  const s = structure;
  const recent = [...s.pivots].slice(-10).reverse();
  return (
    <section aria-labelledby="structure-title" className="space-y-3" data-testid="structure">
      <h3 id="structure-title" className="text-base font-semibold">
        Structure
      </h3>
      {s.zones.length ? (
        <ul className="space-y-1 text-sm" data-testid="structure-zones">
          {s.zones.map((z) => (
            <li key={`${z.low}-${z.high}`} className="flex flex-wrap gap-2">
              <span
                className={cn(
                  "w-24 font-medium",
                  z.side === "support"
                    ? "text-positive"
                    : z.side === "resistance"
                      ? "text-negative"
                      : "",
                )}
              >
                {z.side === "at price"
                  ? "At price"
                  : z.side === "support"
                    ? "Support"
                    : "Resistance"}
              </span>
              <span className="font-mono tabular-nums">
                {z.low.toFixed(2)}–{z.high.toFixed(2)}
              </span>
              <span className="text-xs text-text-tertiary">
                {z.touches} touches, {z.first} to {z.last}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-text-secondary">
          No zone with two or more pivot touches in this window.
        </p>
      )}
      {recent.length ? (
        <table className="w-full max-w-md text-xs" data-testid="structure-pivots">
          <caption className="text-left text-text-tertiary">Latest swing pivots</caption>
          <tbody>
            {recent.map((p) => (
              <tr key={`${p.kind}-${p.day}`}>
                <td>{p.day}</td>
                <td>{p.kind === "high" ? "Swing high" : "Swing low"}</td>
                <td className="text-right font-mono tabular-nums">{p.price.toFixed(2)}</td>
                <td className="text-right font-semibold">{p.label ?? "—"}</td>
                <td className="text-right text-text-tertiary">confirmed {p.confirmed_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      <ul className="space-y-0.5 text-xs text-text-tertiary">
        {Object.entries(s.rules).map(([k, v]) => (
          <li key={k}>{v}.</li>
        ))}
      </ul>
    </section>
  );
}
