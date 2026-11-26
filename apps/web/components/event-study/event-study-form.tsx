"use client";

/**
 * A4.5: the trigger picker and universe of /event-study. A plain GET form,
 * so the study lives in the URL (`rule` or `setup`, `market` | `tickers` |
 * `watchlist`, `from`, `to`, `cooldown`) and a result is a link. The rule is
 * checked as the user types (`checkRule()`); a loaded setup is sent by its
 * version id until the text is edited. News and delivery triggers are rules,
 * offered as presets.
 */

import { useCallback, useState } from "react";

import { RuleFieldEditor, type StrategySetupOption } from "@/components/rule-strategy/rule-field";
import type { StrategyWatchlist } from "@/components/rule-strategy/rule-strategy-form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { type ParsedStudy, TRIGGER_PRESETS } from "@/lib/event-study";
import type { RuleField } from "@/lib/rule-strategy";

const SELECT = "flex h-10 w-full rounded-sm border border-input bg-transparent px-3 py-2 text-sm";

export function EventStudyForm({
  initial,
  setups,
  watchlists,
  signedIn,
}: {
  initial: ParsedStudy;
  setups: StrategySetupOption[];
  watchlists: StrategyWatchlist[];
  signedIn: boolean;
}) {
  const fromSetup = setups.find((s) => s.versionId === initial.setup);
  const [trigger, setTrigger] = useState<RuleField>({
    text: fromSetup?.rule ?? initial.rule,
    versionId: fromSetup ? fromSetup.versionId : initial.setup,
  });
  const [valid, setValid] = useState(true);
  const [universe, setUniverse] = useState(initial.universe);
  const onValidity = useCallback((v: boolean) => setValid(v), []);
  const empty = !trigger.text.trim() && trigger.versionId === null;

  return (
    <form
      method="GET"
      action="/event-study"
      className="mt-5 space-y-5 rounded-md border border-border-muted bg-card p-4"
      data-testid="event-study-form"
    >
      {trigger.versionId !== null ? (
        <input type="hidden" name="setup" value={trigger.versionId} />
      ) : (
        <input type="hidden" name="rule" value={trigger.text} />
      )}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="space-y-3">
          <RuleFieldEditor
            label="Trigger (a condition)"
            hint="An event is the session it turns true after a session it was false."
            value={trigger}
            onChange={setTrigger}
            onValidity={onValidity}
            setups={setups}
          />
          <fieldset className="space-y-1.5">
            <legend className="sr-only">Trigger presets</legend>
            {(["news", "delivery"] as const).map((group) => (
              <div key={group} className="flex flex-wrap items-center gap-2">
                <span className="w-16 text-2xs tracking-[0.02em] text-text-tertiary">
                  {group === "news" ? "News" : "Delivery"}
                </span>
                {TRIGGER_PRESETS.filter((p) => p.group === group).map((p) => (
                  <button
                    key={p.rule}
                    type="button"
                    onClick={() => setTrigger({ text: p.rule, versionId: null })}
                    aria-pressed={trigger.text === p.rule}
                    className="rounded-full border border-border-muted px-2.5 py-1 text-xs text-text-secondary hover:text-foreground aria-pressed:border-brand aria-pressed:text-foreground"
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            ))}
            <p className="text-2xs text-text-tertiary">
              News counts Aegis items linked to the symbol; delivery is NSE/BSE only (unknown until
              NSE files load).
            </p>
          </fieldset>
        </div>

        <div className="space-y-4">
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Universe</legend>
            <div className="flex flex-wrap gap-3 text-sm">
              {(
                [
                  ["market", "A market"],
                  ["tickers", "Ticker list"],
                  ["watchlist", "Watchlist"],
                ] as const
              ).map(([kind, label]) => (
                <label key={kind} className="flex items-center gap-1.5">
                  <input
                    type="radio"
                    name="universe_kind"
                    value={kind}
                    checked={universe === kind}
                    disabled={kind === "watchlist" && !signedIn}
                    onChange={() => setUniverse(kind)}
                  />
                  {label}
                </label>
              ))}
            </div>
            {universe === "market" ? (
              <select
                name="market"
                aria-label="Market"
                defaultValue={initial.market}
                className={SELECT}
              >
                <option value="US">US listings</option>
                <option value="IN">Indian listings (NSE, BSE)</option>
              </select>
            ) : null}
            {universe === "tickers" ? (
              <Input
                name="tickers"
                aria-label="Tickers"
                defaultValue={initial.tickers.join(", ")}
                placeholder="AAPL, MSFT, NVDA"
              />
            ) : null}
            {universe === "watchlist" ? (
              watchlists.length ? (
                <select
                  name="watchlist"
                  aria-label="Watchlist"
                  defaultValue={initial.watchlist ?? ""}
                  className={SELECT}
                >
                  {watchlists.map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.name} ({w.count})
                    </option>
                  ))}
                </select>
              ) : (
                <p className="text-xs text-text-tertiary">You have no watchlists yet.</p>
              )
            ) : null}
            {!signedIn ? (
              <p className="text-2xs text-text-tertiary">Sign in to study a watchlist.</p>
            ) : null}
          </fieldset>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <div className="space-y-1">
              <Label htmlFor="es-from" className="text-xs">
                From
              </Label>
              <Input id="es-from" name="from" type="date" defaultValue={initial.from} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="es-to" className="text-xs">
                To
              </Label>
              <Input id="es-to" name="to" type="date" defaultValue={initial.to} />
            </div>
            <div className="col-span-2 space-y-1 sm:col-span-1">
              <Label htmlFor="es-cooldown" className="text-xs">
                Cooldown
              </Label>
              <Input
                id="es-cooldown"
                name="cooldown"
                type="number"
                min={0}
                max={250}
                defaultValue={initial.cooldown}
              />
            </div>
          </div>
          <p className="text-2xs text-text-tertiary">
            Blank dates: the last ten years. Cooldown: sessions after an event in which a new event
            on that symbol is skipped (0: none).
          </p>
          <Button type="submit" disabled={empty || !valid} className="w-full rounded-sm">
            Run event study
          </Button>
        </div>
      </div>
    </form>
  );
}
