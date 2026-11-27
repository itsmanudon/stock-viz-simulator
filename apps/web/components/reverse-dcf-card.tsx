"use client";

/**
 * Reverse DCF (A7.4, M5.3) on the stock page's Financials tab: the
 * free-cash-flow growth today's enterprise value implies, with editable
 * WACC, terminal growth, horizon and an optional FCF margin override. The
 * maths runs on the API (`/v1/symbols/{t}/reverse-dcf`); this only asks.
 */

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { BROWSER_BASE } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type ReverseDcf = components["schemas"]["ReverseDcfOut"];

const pct = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined ? "—" : `${(v * 100).toFixed(digits)}%`;
const big = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : Intl.NumberFormat("en", { notation: "compact" }).format(v);

const STEP_LABEL: Record<string, string> = {
  enterprise_value: "Enterprise value",
  less_debt: "Less debt",
  plus_cash: "Plus cash",
  equity_value: "Equity value",
  shares: "Shares",
  price: "Price",
};

export function ReverseDcfCard({
  ticker,
  initial,
}: { ticker: string; initial: ReverseDcf | null }) {
  const [data, setData] = useState<ReverseDcf | null>(initial);
  const [wacc, setWacc] = useState(String((initial?.wacc ?? 0.09) * 100));
  const [terminal, setTerminal] = useState(String((initial?.terminal_growth ?? 0.03) * 100));
  const [years, setYears] = useState(String(initial?.years ?? 10));
  const [margin, setMargin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function recompute(event: React.FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    const q = new URLSearchParams({
      wacc: String(Number(wacc) / 100),
      terminal_growth: String(Number(terminal) / 100),
      years,
    });
    if (margin.trim()) q.set("fcf_margin", String(Number(margin) / 100));
    try {
      const res = await fetch(
        `${BROWSER_BASE}/v1/symbols/${encodeURIComponent(ticker)}/reverse-dcf?${q}`,
      );
      if (!res.ok) throw new Error(`The model could not run (HTTP ${res.status}).`);
      setData((await res.json()) as ReverseDcf);
    } catch (err) {
      setError(err instanceof Error ? err.message : "The model could not run.");
    } finally {
      setPending(false);
    }
  }

  if (!data) return null;
  return (
    <section aria-labelledby="rdcf-title" className="space-y-3" data-testid="reverse-dcf">
      <h3 id="rdcf-title" className="text-base font-semibold">
        Reverse DCF
      </h3>
      <p className="text-sm" data-testid="reverse-dcf-result">
        {data.implied_growth !== null && data.implied_growth !== undefined ? (
          <>
            Today's enterprise value implies free cash flow growing{" "}
            <span className="font-mono font-semibold tabular-nums">{pct(data.implied_growth)}</span>{" "}
            a year for {data.years} years, then {pct(data.terminal_growth)} forever, at a{" "}
            {pct(data.wacc)} WACC.
          </>
        ) : (
          <span className="text-text-secondary">{data.reason}</span>
        )}
      </p>
      <form onSubmit={recompute} className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        {(
          [
            ["WACC %", wacc, setWacc, "rdcf-wacc"],
            ["Terminal %", terminal, setTerminal, "rdcf-terminal"],
            ["Years", years, setYears, "rdcf-years"],
            ["FCF margin % (optional)", margin, setMargin, "rdcf-margin"],
          ] as const
        ).map(([label, value, set, id]) => (
          <div key={id} className="space-y-1">
            <Label htmlFor={id} className="text-xs">
              {label}
            </Label>
            <Input
              id={id}
              inputMode="decimal"
              value={value}
              onChange={(e) => set(e.target.value)}
            />
          </div>
        ))}
        <div className="flex items-end">
          <Button type="submit" size="sm" disabled={pending}>
            {pending ? "Solving…" : "Solve"}
          </Button>
        </div>
      </form>
      {error ? <p className="text-xs text-negative">{error}</p> : null}
      {data.sensitivity.length ? (
        <table className="w-full max-w-md text-xs" data-testid="reverse-dcf-grid">
          <caption className="text-left text-text-tertiary">
            Implied growth by WACC (rows) and terminal growth (columns)
          </caption>
          <thead>
            <tr>
              <th />
              {[...new Set(data.sensitivity.map((r) => r.terminal_growth))].map((t) => (
                <th key={t} className="text-right font-normal text-text-tertiary">
                  {pct(t)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[...new Set(data.sensitivity.map((r) => r.wacc))].map((w) => (
              <tr key={w}>
                <th className="text-left font-normal text-text-tertiary">{pct(w)}</th>
                {data.sensitivity
                  .filter((r) => r.wacc === w)
                  .map((r) => (
                    <td key={r.terminal_growth} className="text-right font-mono tabular-nums">
                      {pct(r.implied_growth)}
                    </td>
                  ))}
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {data.reconciliation.length ? (
        <p className="text-xs text-text-tertiary">
          {data.reconciliation
            .map(
              (s) =>
                `${STEP_LABEL[s.step] ?? s.step} ${s.step === "price" ? (s.value?.toFixed(2) ?? "—") : big(s.value)}`,
            )
            .join(" · ")}{" "}
          ({data.currency ?? "reporting currency"}; base {data.base_fcf_source} {big(data.base_fcf)}
          )
        </p>
      ) : null}
      <p className="text-xs text-text-tertiary">{data.method}</p>
    </section>
  );
}
