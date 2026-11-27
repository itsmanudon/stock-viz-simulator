/**
 * A7.12 (M10.7): the India capital gains estimate. Server-renderable. Every
 * figure is an estimate and the page says so first; rates name their section
 * and sources. Neutral wording: what realising a lot would do, never what to do.
 */

import { FigureStrip } from "@/components/figure-strip";
import { type IndiaTax, inr, rate } from "@/lib/india-tax";

function Section({
  title,
  children,
  id,
}: { title: string; children: React.ReactNode; id: string }) {
  return (
    <section aria-labelledby={id} className="space-y-2">
      <h2 id={id} className="text-base font-semibold">
        {title}
      </h2>
      {children}
    </section>
  );
}

export function IndiaTaxView({ data }: { data: IndiaTax }) {
  const c = data.computation;
  const r = data.rules;
  const losses = data.open_lots.filter((l) => l.unrealised != null && Number(l.unrealised) < 0);
  const longGains = data.open_lots.filter(
    (l) => l.term === "long" && l.unrealised != null && Number(l.unrealised) > 0,
  );
  return (
    <div className="space-y-8" data-testid="india-tax">
      <p
        className="rounded-lg border border-warning/40 bg-warning-soft px-3 py-2 text-sm text-warning-soft-foreground"
        data-testid="tax-estimate-note"
      >
        {data.estimate_note}
      </p>
      <FigureStrip
        label={`FY ${data.fy} estimate`}
        figures={[
          {
            label: "Short-Term Gains, Net",
            value: inr(c.net_short),
            note: `Taxed at ${rate(r.stcg_rate)} (s.${r.stcg_section})`,
          },
          {
            label: "Long-Term Gains, Net",
            value: inr(c.net_long_before_exemption),
            note: `${rate(r.ltcg_rate)} above ${inr(r.ltcg_exemption)} (s.${r.ltcg_section})`,
          },
          {
            label: "Exemption Left",
            value: inr(c.exemption_left),
            note: `Of ${inr(r.ltcg_exemption)} this year`,
          },
          {
            label: "Estimated Tax",
            value: inr(c.total_tax),
            note: `Cess ${rate(r.cess_rate)} included`,
          },
        ]}
      />
      <dl className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4" data-testid="tax-breakdown">
        {(
          [
            ["Short-term gains", c.stcg],
            ["Short-term losses", c.stcl],
            ["Long-term gains", c.ltcg],
            ["Long-term losses", c.ltcl],
            ["Tax on short term", c.tax_short],
            ["Tax on long term", c.tax_long],
            ["Surcharge", c.surcharge],
            ["Cess", c.cess],
            ["Short-term loss to carry", c.loss_carried_short],
            ["Long-term loss to carry", c.loss_carried_long],
            ["Intraday P&L (business income)", c.intraday_pnl],
          ] as const
        ).map(([label, value]) => (
          <div key={label}>
            <dt className="text-text-tertiary">{label}</dt>
            <dd className="font-mono tabular-nums">{inr(value)}</dd>
          </div>
        ))}
      </dl>
      {data.unmatched.length ? (
        <p className="text-xs text-warning" data-testid="tax-unmatched">
          {data.unmatched.length} sell{data.unmatched.length === 1 ? "" : "s"} had fewer shares than
          the book held (an opening lot is missing); they are left out.
        </p>
      ) : null}

      <Section title="Realised This Year" id="tax-realised">
        {data.realised.length === 0 ? (
          <p className="text-sm text-text-secondary">No delivery sales in FY {data.fy}.</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-sm" data-testid="tax-realised-table">
              <thead className="text-2xs text-text-tertiary">
                <tr>
                  {["Symbol", "Bought", "Sold", "Qty", "Cost", "Proceeds", "Gain", "Term"].map(
                    (h) => (
                      <th key={h} className="px-3 py-2 text-left font-medium">
                        {h}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {data.realised.map((x) => (
                  <tr
                    key={`${x.ticker}-${x.bought}-${x.sold}-${x.quantity}`}
                    className="border-t border-border"
                  >
                    <td className="ticker px-3 py-2 font-semibold">{x.ticker}</td>
                    <td className="px-3 py-2">{x.bought}</td>
                    <td className="px-3 py-2">{x.sold}</td>
                    <td className="px-3 py-2 font-mono tabular-nums">{Number(x.quantity)}</td>
                    <td className="px-3 py-2 font-mono tabular-nums">{inr(x.cost)}</td>
                    <td className="px-3 py-2 font-mono tabular-nums">{inr(x.proceeds)}</td>
                    <td className="px-3 py-2 font-mono tabular-nums">{inr(x.gain)}</td>
                    <td className="px-3 py-2">
                      {x.term === "long" ? "Long Term" : "Short Term"}
                      {x.grandfathered ? " · Grandfathered" : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title="Open Lots and Harvesting" id="tax-open">
        <p className="text-xs text-text-secondary" data-testid="tax-harvest-summary">
          Realising the open losses below would add{" "}
          {inr(losses.reduce((s, l) => s + Number(l.unrealised), 0))} of losses this year. Long-term
          lots with gains hold {inr(longGains.reduce((s, l) => s + Number(l.unrealised), 0))};{" "}
          {inr(c.exemption_left)} of the exemption is unused. Figures, not a recommendation.
        </p>
        {data.open_lots.length === 0 ? (
          <p className="text-sm text-text-secondary">No open lots.</p>
        ) : (
          <ul className="grid gap-2 sm:grid-cols-2" data-testid="tax-open-lots">
            {data.open_lots.map((l) => (
              <li
                key={`${l.ticker}-${l.bought}`}
                className="rounded-lg border border-border bg-card p-3 text-xs"
                data-testid="tax-open-lot"
                data-term={l.term}
              >
                <p className="text-sm">
                  <span className="ticker font-semibold">{l.ticker}</span> · {Number(l.quantity)}{" "}
                  bought {l.bought}
                </p>
                <p className="text-text-secondary">
                  {l.term === "long" ? "Long Term" : `Short Term until ${l.long_term_on}`} · Cost{" "}
                  {inr(l.cost)} · Unrealised {inr(l.unrealised)}
                  {l.close_date ? ` at the ${l.close_date} close` : " (no stored close)"}
                </p>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Rules and Sources" id="tax-rules">
        <p className="text-xs text-text-secondary">
          {r.act}. FY {r.fy}: {r.start} to {r.end}. Long term after {r.long_term_after_months}{" "}
          months. Surcharge capped at {rate(r.surcharge_cap)} on these gains.
        </p>
        <ul
          className="list-disc space-y-1 pl-5 text-2xs text-text-tertiary"
          data-testid="tax-method"
        >
          {data.method.map((m) => (
            <li key={m}>{m}</li>
          ))}
        </ul>
        <ul className="space-y-1 text-2xs text-text-tertiary" data-testid="tax-sources">
          {r.sources.map((s) => (
            <li key={s.title}>
              {s.url ? (
                <a href={s.url} target="_blank" rel="noreferrer" className="underline">
                  {s.title}
                </a>
              ) : (
                s.title
              )}{" "}
              (read {s.read_on}){s.note ? `: ${s.note}` : ""}
            </li>
          ))}
        </ul>
        {data.skipped_tickers.length ? (
          <p className="text-2xs text-text-tertiary">
            Not Indian listings, left out: {data.skipped_tickers.join(", ")}.
          </p>
        ) : null}
      </Section>
    </div>
  );
}
