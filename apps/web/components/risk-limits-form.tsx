import type { RiskLimits } from "@/lib/api/trading";

export const LIMIT_FIELDS: {
  name: keyof Omit<RiskLimits, "updated_at">;
  label: string;
  hint: string;
}[] = [
  { name: "max_position_pct", label: "Largest holding", hint: "One holding's value after a buy" },
  { name: "max_order_pct", label: "Single order", hint: "One buy's cost, options included" },
  { name: "max_sector_pct", label: "One sector", hint: "A sector's stocks after a buy" },
  {
    name: "max_currency_pct",
    label: "One foreign currency",
    hint: "Its stocks and cash after a buy",
  },
  {
    name: "max_var_pct",
    label: "1-day 95% VaR",
    hint: "Estimated with the buy added; needs 250 sessions of history",
  },
];

/**
 * Phase 8.5: the account's own pre-trade limits, as % of the account's value.
 * Empty means no limit; all are empty until the user sets one. A server
 * action form, so it works without JavaScript.
 */
export function RiskLimitsForm({
  limits,
  action,
}: {
  limits: RiskLimits | null;
  action: (formData: FormData) => Promise<void>;
}) {
  return (
    <form action={action} className="space-y-3" aria-labelledby="limits-heading">
      <p className="text-xs leading-relaxed text-text-tertiary">
        Each is a share of the account&apos;s value. A buy that would cross one is refused, and a
        pending order that would is cancelled with the reason. Selling is always allowed. Leave a
        field empty for no limit.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        {LIMIT_FIELDS.map((field) => (
          <div key={field.name} className="grid gap-1">
            <label htmlFor={`limit-${field.name}`} className="text-xs text-text-tertiary">
              {field.label} (%)
            </label>
            <input
              id={`limit-${field.name}`}
              name={field.name}
              type="number"
              inputMode="decimal"
              min="0.01"
              max="100"
              step="0.01"
              defaultValue={limits?.[field.name] ?? ""}
              placeholder="No limit"
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-2 font-mono text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
            <span className="text-2xs text-text-tertiary">{field.hint}</span>
          </div>
        ))}
      </div>
      <button
        type="submit"
        className="h-9 rounded-full bg-primary px-5 text-sm font-medium text-primary-foreground transition hover:bg-primary/90"
      >
        Save limits
      </button>
    </form>
  );
}
