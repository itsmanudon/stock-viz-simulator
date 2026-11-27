/** A7.12 (M10.7): India tax types, URL state and formatting (client-safe). */

import type { components } from "./api/schema";

export type IndiaTax = components["schemas"]["IndiaTaxOut"];

export const TAX_YEARS = ["2026-27", "2025-26"] as const;
export const SURCHARGE_OPTIONS = [
  { value: 0, label: "None" },
  { value: 0.1, label: "10%" },
  { value: 0.15, label: "15% (Capped)" },
] as const;

export function parseTaxParams(raw: { fy?: string; surcharge?: string; book?: string }) {
  const fy = TAX_YEARS.includes(raw.fy as (typeof TAX_YEARS)[number])
    ? (raw.fy as string)
    : TAX_YEARS[0];
  const s = Number(raw.surcharge);
  const surcharge = SURCHARGE_OPTIONS.some((o) => o.value === s) ? s : 0;
  const b = Number(raw.book);
  return { fy, surcharge, book: Number.isInteger(b) && b > 0 ? b : null };
}

/** Rupees with Indian grouping ("₹1,25,000.00"); a dash for null. */
export function inr(value: string | number | null | undefined): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  });
}

export function rate(value: string | number): string {
  return `${(Number(value) * 100).toLocaleString("en-US", { maximumFractionDigits: 2 })}%`;
}
