import type { BacktestUniverse } from "@/lib/api/types";

/**
 * A1.4a (M1.5): the universe a backtest ran on, beside its results. One
 * neutral line, not a red alarm: every run today is on the pinned symbol
 * list, so it is survivorship-biased.
 */
export function universeSummary(universe: BacktestUniverse | null | undefined): string | null {
  if (!universe) return null;
  const name = universe.name === "pinned" ? "Pinned symbol list" : universe.name;
  const timing = universe.point_in_time ? "point in time" : "not point in time";
  return universe.survivorship_biased
    ? `${name}, ${timing}: survivorship-biased.`
    : `${name}, ${timing}.`;
}

export function UniverseNote({
  universe,
  className = "",
}: {
  universe: BacktestUniverse | null | undefined;
  className?: string;
}) {
  const summary = universeSummary(universe);
  if (!universe || !summary) return null;
  return (
    <p
      className={`text-xs leading-5 text-text-tertiary ${className}`}
      data-testid="backtest-universe"
    >
      <span className="font-medium text-text-secondary">Universe:</span> {summary} {universe.note}
    </p>
  );
}
