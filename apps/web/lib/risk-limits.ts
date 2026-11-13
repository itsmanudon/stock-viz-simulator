import type { RiskLimits } from "@/lib/api/trading";

const NAMES = [
  "max_position_pct",
  "max_order_pct",
  "max_sector_pct",
  "max_currency_pct",
  "max_var_pct",
] as const;

/** Form fields to the API body: empty or invalid means no limit (null). */
export function limitsFromForm(formData: FormData): Omit<RiskLimits, "updated_at"> {
  const out = {} as Omit<RiskLimits, "updated_at">;
  for (const name of NAMES) {
    const raw = formData.get(name);
    const value = typeof raw === "string" ? raw.trim() : "";
    const n = Number(value);
    out[name] = value !== "" && Number.isFinite(n) && n > 0 && n <= 100 ? value : null;
  }
  return out;
}
