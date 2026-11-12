"use client";

/**
 * Create an alert rule (Phase 7.3, audit UX-2).
 *
 * One form for every kind: a price level, a session move, a technical
 * crossing, Aegis news, or a portfolio measure. It searches symbols by
 * ticker or name, shows the stored close with its date and the distance to a
 * price target, and previews the rule in words before it is saved. Rules are
 * judged on daily closes after each nightly run, never in real time.
 */

import { Bell } from "lucide-react";
import { Popover } from "radix-ui";
import { useActionState, useId, useMemo, useState } from "react";

import { type CreateAlertState, createAlertAction } from "@/app/(product)/(authed)/alerts/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { type RuleDraft, distanceToTargetPct, previewRule } from "@/lib/alert-rules";
import { formatCurrency } from "@/lib/portfolio-view-model";
import { formatCloseDate } from "@/lib/stock-workspace";

export type AlertSymbol = {
  ticker: string;
  name: string;
  currency: string;
  last_close: string | null;
  last_close_at: string | null;
};

type Kind = RuleDraft["kind"];

const KINDS: { value: Kind; label: string }[] = [
  { value: "price", label: "Price level" },
  { value: "move", label: "Big daily move" },
  { value: "technical", label: "Technical crossing" },
  { value: "news", label: "News (Aegis)" },
  { value: "portfolio", label: "My portfolio" },
];

/** Series a technical rule can compare; `.output` picks one of several. */
export const ALERT_OPERANDS = [
  { value: "close", label: "Close" },
  { value: "sma_20", label: "SMA 20" },
  { value: "sma_50", label: "SMA 50" },
  { value: "sma_200", label: "SMA 200" },
  { value: "ema_50", label: "EMA 50" },
  { value: "rsi_14", label: "RSI 14" },
  { value: "macd.macd", label: "MACD line" },
  { value: "macd.signal", label: "MACD signal" },
  { value: "stoch_14_3.k", label: "Stochastic %K" },
  { value: "adx_14.adx", label: "ADX 14" },
  { value: "cci_20", label: "CCI 20" },
  { value: "mfi_14", label: "MFI 14" },
  { value: "willr_14", label: "Williams %R 14" },
  { value: "bb_20_2.upper", label: "Bollinger upper" },
  { value: "bb_20_2.lower", label: "Bollinger lower" },
] as const;

const SELECT =
  "h-9 w-full rounded-sm border border-input bg-transparent px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";

function Field({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="text-xs">
        {label}
      </Label>
      {children}
    </div>
  );
}

function AlertFields({
  fixedTicker,
  initialTicker,
  lastClose,
  lastCloseAt,
  currency,
  symbols,
  pending,
  state,
}: {
  fixedTicker: string;
  initialTicker: string;
  lastClose: string | null;
  lastCloseAt: string | null;
  currency: string;
  symbols: AlertSymbol[];
  pending: boolean;
  state: CreateAlertState;
}) {
  const id = useId();
  const [draft, setDraft] = useState<RuleDraft>({
    kind: "price",
    ticker: fixedTicker || initialTicker,
    direction: "above",
    op: "below",
    indicator: "rsi_14",
    value: "30",
    metric: "drawdown_pct",
    repeat: "once",
  });
  const set = (patch: Partial<RuleDraft>) => setDraft((d) => ({ ...d, ...patch }));
  const bySymbol = useMemo(() => new Map(symbols.map((s) => [s.ticker, s])), [symbols]);
  const picked = bySymbol.get(draft.ticker.toUpperCase());
  const close = fixedTicker ? lastClose : (picked?.last_close ?? null);
  const closeAt = fixedTicker ? lastCloseAt : (picked?.last_close_at ?? null);
  const ccy = fixedTicker ? currency : (picked?.currency ?? currency);
  const distance = draft.kind === "price" ? distanceToTargetPct(close, draft.target) : null;
  const needsTicker = draft.kind !== "portfolio";

  return (
    <>
      <Field id={`${id}-kind`} label="Alert me on">
        <select
          id={`${id}-kind`}
          name="kind"
          value={draft.kind}
          onChange={(e) => set({ kind: e.target.value as Kind })}
          className={SELECT}
        >
          {KINDS.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </select>
      </Field>

      {needsTicker ? (
        fixedTicker ? (
          <input type="hidden" name="ticker" value={fixedTicker} />
        ) : (
          <Field id={`${id}-ticker`} label="Symbol">
            <Input
              id={`${id}-ticker`}
              name="ticker"
              list={`${id}-symbols`}
              value={draft.ticker}
              onChange={(e) => set({ ticker: e.target.value.toUpperCase() })}
              placeholder="Search ticker or company"
              autoComplete="off"
              maxLength={16}
              required
              className="font-mono uppercase placeholder:font-sans placeholder:normal-case"
            />
            <datalist id={`${id}-symbols`}>
              {symbols.map((s) => (
                <option key={s.ticker} value={s.ticker} label={s.name} />
              ))}
            </datalist>
          </Field>
        )
      ) : null}

      {needsTicker && close ? (
        <p className="text-xs text-text-tertiary" data-testid="alert-close">
          Stored close {formatCurrency(close, ccy)}
          {closeAt ? ` on ${formatCloseDate(closeAt)}` : ""}.
        </p>
      ) : null}

      {draft.kind === "price" ? (
        <div className="grid grid-cols-2 gap-3">
          <Field id={`${id}-direction`} label="Close">
            <select
              id={`${id}-direction`}
              name="direction"
              value={draft.direction}
              onChange={(e) => set({ direction: e.target.value as "above" | "below" })}
              className={SELECT}
            >
              <option value="above">at or above</option>
              <option value="below">at or below</option>
            </select>
          </Field>
          <Field id={`${id}-target`} label={`Target (${ccy})`}>
            <Input
              id={`${id}-target`}
              name="target_price"
              type="number"
              inputMode="decimal"
              min="0.01"
              step="0.01"
              required
              value={draft.target ?? ""}
              onChange={(e) => set({ target: e.target.value })}
              className="font-mono"
            />
          </Field>
        </div>
      ) : null}
      {distance !== null ? (
        <p className="text-xs text-text-tertiary" data-testid="alert-distance">
          {Math.abs(distance).toFixed(2)}% {distance >= 0 ? "above" : "below"} the stored close.
        </p>
      ) : null}

      {draft.kind === "move" ? (
        <Field id={`${id}-move`} label="Daily move of at least (%)">
          <Input
            id={`${id}-move`}
            name="move_pct"
            type="number"
            min="0.1"
            max="100"
            step="0.1"
            required
            value={draft.movePct ?? ""}
            onChange={(e) => set({ movePct: e.target.value })}
            className="font-mono"
          />
        </Field>
      ) : null}

      {draft.kind === "technical" ? (
        <div className="grid gap-3">
          <Field id={`${id}-indicator`} label="When">
            <select
              id={`${id}-indicator`}
              name="indicator"
              value={draft.indicator}
              onChange={(e) => set({ indicator: e.target.value })}
              className={SELECT}
            >
              {ALERT_OPERANDS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </Field>
          <Field id={`${id}-op`} label="Crosses">
            <select
              id={`${id}-op`}
              name="op"
              value={draft.op}
              onChange={(e) => set({ op: e.target.value as "above" | "below" })}
              className={SELECT}
            >
              <option value="above">above</option>
              <option value="below">below</option>
            </select>
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field id={`${id}-value`} label="A number">
              <Input
                id={`${id}-value`}
                name="value"
                type="number"
                step="any"
                value={draft.compareTo ? "" : (draft.value ?? "")}
                disabled={Boolean(draft.compareTo)}
                onChange={(e) => set({ value: e.target.value })}
                className="font-mono"
              />
            </Field>
            <Field id={`${id}-compare`} label="Or a series">
              <select
                id={`${id}-compare`}
                name="compare_to"
                value={draft.compareTo ?? ""}
                onChange={(e) => set({ compareTo: e.target.value || undefined })}
                className={SELECT}
              >
                <option value="">— a number —</option>
                {ALERT_OPERANDS.filter((o) => o.value !== draft.indicator).map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        </div>
      ) : null}

      {draft.kind === "news" ? (
        <div className="grid grid-cols-2 gap-3">
          <Field id={`${id}-sentiment`} label="Sentiment">
            <select
              id={`${id}-sentiment`}
              name="sentiment"
              value={draft.sentiment ?? ""}
              onChange={(e) => set({ sentiment: e.target.value || undefined })}
              className={SELECT}
            >
              <option value="">Any</option>
              <option value="negative">Negative</option>
              <option value="positive">Positive</option>
              <option value="mixed">Mixed</option>
            </select>
          </Field>
          <Field id={`${id}-event`} label="Event type (optional)">
            <Input
              id={`${id}-event`}
              name="event_type"
              maxLength={128}
              value={draft.eventType ?? ""}
              onChange={(e) => set({ eventType: e.target.value || undefined })}
            />
          </Field>
        </div>
      ) : null}

      {draft.kind === "portfolio" ? (
        <div className="grid grid-cols-2 gap-3">
          <Field id={`${id}-metric`} label="Measure">
            <select
              id={`${id}-metric`}
              name="metric"
              value={draft.metric}
              onChange={(e) => set({ metric: e.target.value })}
              className={SELECT}
            >
              <option value="drawdown_pct">Drawdown from peak</option>
              <option value="position_weight_pct">Largest holding's weight</option>
              <option value="day_change_pct">Move in one session</option>
            </select>
          </Field>
          <Field id={`${id}-threshold`} label="Threshold (%)">
            <Input
              id={`${id}-threshold`}
              name="threshold"
              type="number"
              min="0.1"
              max="100"
              step="0.1"
              required
              value={draft.threshold ?? ""}
              onChange={(e) => set({ threshold: e.target.value })}
              className="font-mono"
            />
          </Field>
        </div>
      ) : null}

      <Field id={`${id}-repeat`} label="Repeat">
        <select
          id={`${id}-repeat`}
          name="repeat"
          value={draft.repeat}
          onChange={(e) => set({ repeat: e.target.value as "once" | "every_cross" })}
          className={SELECT}
        >
          <option value="once">Once, then stop</option>
          <option value="every_cross">Every time it happens</option>
        </select>
      </Field>

      <p
        className="rounded-sm bg-surface-secondary px-2.5 py-2 text-xs"
        data-testid="alert-preview"
      >
        {previewRule({ ...draft, ticker: draft.ticker || fixedTicker })} Judged on daily closes
        after each nightly run; a condition already true when you save it waits for the next cross.
      </p>

      {state.error ? (
        <p className="text-xs text-negative" role="alert">
          {state.error}
        </p>
      ) : null}
      {state.createdId ? <output className="block text-xs text-positive">Alert set.</output> : null}
      <Button type="submit" size="sm" className="rounded-sm" disabled={pending}>
        {pending ? "Saving…" : "Create alert"}
      </Button>
    </>
  );
}

export function AlertForm({
  ticker,
  lastClose = null,
  lastCloseAt = null,
  currency = "USD",
  symbols = [],
  variant = "popover",
}: {
  ticker: string;
  lastClose?: string | null;
  lastCloseAt?: string | null;
  currency?: string;
  symbols?: AlertSymbol[];
  variant?: "popover" | "inline";
}) {
  const [open, setOpen] = useState(false);
  const [state, action, pending] = useActionState<CreateAlertState, FormData>(
    createAlertAction,
    {},
  );
  const fields = (
    <AlertFields
      fixedTicker={variant === "inline" ? "" : ticker}
      initialTicker={ticker}
      lastClose={lastClose}
      lastCloseAt={lastCloseAt}
      currency={currency}
      symbols={
        variant === "inline" && ticker && !symbols.some((s) => s.ticker === ticker)
          ? [
              ...symbols,
              { ticker, name: ticker, currency, last_close: lastClose, last_close_at: lastCloseAt },
            ]
          : symbols
      }
      pending={pending}
      state={state}
    />
  );

  if (variant === "inline") {
    return (
      <form action={action} className="space-y-3">
        {fields}
      </form>
    );
  }

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <Button type="button" variant="outline" size="sm">
          <Bell className="h-4 w-4" aria-hidden />
          <span className="ml-1.5">Alert</span>
        </Button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={8}
          className="z-50 max-h-[80vh] w-[min(22rem,calc(100vw-2rem))] overflow-y-auto rounded-md border border-border-muted bg-popover p-4 shadow-xl outline-none"
          aria-label={`Set an alert for ${ticker}`}
        >
          <div className="mb-4">
            <p className="text-sm font-semibold">Alert</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Get notified about {ticker} after a nightly run.
            </p>
          </div>
          <form action={action} className="space-y-3">
            {fields}
          </form>
          <Popover.Arrow className="fill-border" />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
