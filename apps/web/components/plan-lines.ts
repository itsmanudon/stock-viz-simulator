/**
 * Plan lines (A6.7, M2.11): a ticker's trade plans (A5.4) as price lines on
 * the price pane, entry, stop and target.
 *
 * - **Drafts** (open, no fill yet) draw dashed and can be dragged: the line
 *   follows the pointer, and on release the draft's new prices are saved,
 *   debounced, through the plans API. A drag that would break the plan (a
 *   long plan's stop below its entry, its target above it) snaps back with
 *   the reason.
 * - **Locked** plans (a fill linked, or written after entry: `frozen`) draw
 *   dotted, with no handles. A press on one is refused with A5.4's reason;
 *   the API refuses the edit with 409 as well.
 *
 * The pure parts (`planLines`, `grabLine`, `movedPrices`) are exported for
 * tests; `PlanLinesController` binds them to a chart.
 */

import type { IPriceLine, ISeriesApi, SeriesType } from "lightweight-charts";

import { roundPrice } from "@/lib/drawings/drag";
import type { TradePlan } from "@/lib/plans";
import { debounce } from "@/lib/volume-profile";

export type PlanLevel = "entry" | "stop" | "target";

export type PlanLine = {
  planId: number;
  level: PlanLevel;
  price: number;
  locked: boolean;
};

export const PLAN_SAVE_DEBOUNCE_MS = 600;
export const GRAB_PX = 6;
export const LOCKED_REASON =
  "This plan is locked: it has a fill (or was written after entry), so its prices can't change. Notes and tags still can, in the Journal.";

const LEVELS: PlanLevel[] = ["entry", "stop", "target"];
const TITLES: Record<PlanLevel, string> = { entry: "Entry", stop: "Stop", target: "Target" };

/** Locked for the chart: any fill linked, or written after entry. */
export function planLocked(
  plan: Pick<TradePlan, "locked" | "frozen" | "written_after_entry" | "status">,
): boolean {
  return plan.locked || plan.frozen || plan.written_after_entry || plan.status !== "open";
}

function priceOf(plan: TradePlan, level: PlanLevel): number | null {
  const raw =
    level === "entry"
      ? plan.planned_entry
      : level === "stop"
        ? plan.planned_stop
        : plan.planned_target;
  const n = raw === null || raw === undefined ? Number.NaN : Number(raw);
  return Number.isFinite(n) && n > 0 ? n : null;
}

export function planLines(plans: readonly TradePlan[]): PlanLine[] {
  const out: PlanLine[] = [];
  for (const plan of plans) {
    const locked = planLocked(plan);
    for (const level of LEVELS) {
      const price = priceOf(plan, level);
      if (price !== null) out.push({ planId: plan.id, level, price, locked });
    }
  }
  return out;
}

/** The line nearest `y` within `tolerance` px (locked ones included), or null. */
export function grabLine(
  lines: readonly PlanLine[],
  y: number,
  yOfPrice: (price: number) => number | null,
  tolerance = GRAB_PX,
): PlanLine | null {
  let best: { line: PlanLine; distance: number } | null = null;
  for (const line of lines) {
    const at = yOfPrice(line.price);
    if (at === null) continue;
    const distance = Math.abs(at - y);
    if (distance <= tolerance && (!best || distance < best.distance)) best = { line, distance };
  }
  return best?.line ?? null;
}

export type MovedPrices =
  | { entry: string; stop: string; target: string | null }
  | { problem: string };

/** A long plan's prices with one level moved to `price`, or why it can't move there. */
export function movedPrices(plan: TradePlan, level: PlanLevel, price: number): MovedPrices {
  if (planLocked(plan)) return { problem: LOCKED_REASON };
  const entry = level === "entry" ? price : priceOf(plan, "entry");
  const stop = level === "stop" ? price : priceOf(plan, "stop");
  const target = level === "target" ? price : priceOf(plan, "target");
  if (entry === null || stop === null) return { problem: "The plan needs an entry and a stop." };
  if (price <= 0) return { problem: "Prices must be above 0." };
  if (stop >= entry) return { problem: "A long plan's stop must stay below its entry." };
  if (target !== null && target <= entry) {
    return { problem: "A long plan's target must stay above its entry." };
  }
  return {
    entry: roundPrice(entry),
    stop: roundPrice(stop),
    target: target === null ? null : roundPrice(target),
  };
}

type Prices = { entry: string; stop: string; target: string | null };

export type PlanLineColours = { entry: string; stop: string; target: string };

type Options = {
  series: ISeriesApi<SeriesType>;
  /** The element the pointer is read on (the chart's focusable group). */
  root: HTMLElement;
  /** The chart's container (pane coordinates start at its top-left). */
  container: HTMLElement;
  colours: PlanLineColours;
  /** Save a draft's moved prices (debounced); resolves to the saved plan or an error. */
  save: (
    planId: number,
    prices: { entry: string; stop: string; target: string | null },
  ) => Promise<{ plan?: TradePlan; error?: string }>;
  onPlans: (plans: TradePlan[]) => void;
  onMessage: (message: string) => void;
  debounceMs?: number;
};

/** Draws plans as price lines and lets drafts be dragged (see the module rules). */
export class PlanLinesController {
  private plans: TradePlan[] = [];
  private lines: { line: PlanLine; api: IPriceLine }[] = [];
  private grab: { line: PlanLine; api: IPriceLine; moved: boolean; startY: number } | null = null;
  private readonly saves = new Map<number, ((prices: Prices) => void) & { cancel: () => void }>();
  /** The last prices the server confirmed, per plan: a refused save goes back to them. */
  private confirmed = new Map<number, TradePlan>();

  constructor(private readonly opts: Options) {
    opts.root.addEventListener("pointerdown", this.onDown, true);
    opts.root.addEventListener("mousedown", this.stopIfGrabbed, true);
    opts.root.addEventListener("touchstart", this.stopIfGrabbed, true);
    window.addEventListener("pointermove", this.onMove);
    window.addEventListener("pointerup", this.onUp);
  }

  destroy(): void {
    const { root } = this.opts;
    root.removeEventListener("pointerdown", this.onDown, true);
    root.removeEventListener("mousedown", this.stopIfGrabbed, true);
    root.removeEventListener("touchstart", this.stopIfGrabbed, true);
    window.removeEventListener("pointermove", this.onMove);
    window.removeEventListener("pointerup", this.onUp);
    for (const save of this.saves.values()) save.cancel();
    this.clear();
  }

  /** The plans as the server holds them (a save or a reload). */
  setPlans(plans: TradePlan[]): void {
    this.plans = plans;
    this.confirmed = new Map(plans.map((p) => [p.id, p]));
    this.draw();
  }

  /** The lines drawn now (for tests and the chart's caption). */
  drawn(): PlanLine[] {
    return this.lines.map((l) => l.line);
  }

  private clear(): void {
    for (const { api } of this.lines) {
      try {
        this.opts.series.removePriceLine(api);
      } catch {
        // the chart was removed first
      }
    }
    this.lines = [];
  }

  private draw(): void {
    this.clear();
    for (const line of planLines(this.plans)) {
      const api = this.opts.series.createPriceLine({
        price: line.price,
        color: this.opts.colours[line.level],
        lineWidth: 1,
        // Locked: dotted (1); a draft: dashed (2).
        lineStyle: line.locked ? 1 : 2,
        axisLabelVisible: true,
        title: `${TITLES[line.level]}${line.locked ? " (Locked)" : ""}`,
      });
      this.lines.push({ line, api });
    }
  }

  private paneY(clientY: number): number {
    return clientY - this.opts.container.getBoundingClientRect().top;
  }

  private readonly onDown = (event: PointerEvent) => {
    if (event.button !== 0 || this.lines.length === 0) return;
    const y = this.paneY(event.clientY);
    const hit = grabLine(
      this.lines.map((l) => l.line),
      y,
      (p) => this.opts.series.priceToCoordinate(p),
    );
    if (!hit) return;
    if (hit.locked) {
      this.opts.onMessage(LOCKED_REASON);
      return;
    }
    const api = this.lines.find((l) => l.line === hit)?.api;
    if (!api) return;
    event.stopPropagation();
    this.grab = { line: hit, api, moved: false, startY: event.clientY };
  };

  private readonly stopIfGrabbed = (event: Event) => {
    if (this.grab) event.stopPropagation();
  };

  private readonly onMove = (event: PointerEvent) => {
    const grab = this.grab;
    if (!grab) return;
    if (!grab.moved && Math.abs(event.clientY - grab.startY) < 3) return;
    const price = this.opts.series.coordinateToPrice(this.paneY(event.clientY));
    if (price === null) return;
    grab.moved = true;
    grab.api.applyOptions({ price });
  };

  private readonly onUp = (event: PointerEvent) => {
    const grab = this.grab;
    this.grab = null;
    if (!grab?.moved) return;
    const plan = this.plans.find((p) => p.id === grab.line.planId);
    const price = this.opts.series.coordinateToPrice(this.paneY(event.clientY));
    if (!plan || price === null) {
      this.draw();
      return;
    }
    const moved = movedPrices(plan, grab.line.level, price);
    if ("problem" in moved) {
      this.opts.onMessage(moved.problem);
      this.draw();
      return;
    }
    // The draft shows its new prices at once; the save follows, debounced.
    const next: TradePlan = {
      ...plan,
      planned_entry: moved.entry,
      planned_stop: moved.stop,
      planned_target: moved.target,
    };
    this.plans = this.plans.map((p) => (p.id === plan.id ? next : p));
    this.draw();
    this.opts.onPlans(this.plans);
    this.saveLater(plan.id, moved);
  };

  private saveLater(
    planId: number,
    prices: { entry: string; stop: string; target: string | null },
  ) {
    let save = this.saves.get(planId);
    if (!save) {
      save = debounce((latest: { entry: string; stop: string; target: string | null }) => {
        void this.opts.save(planId, latest).then((result) => {
          if (result.plan) {
            const plan = result.plan;
            this.confirmed.set(plan.id, plan);
            this.plans = this.plans.map((p) => (p.id === plan.id ? plan : p));
            this.opts.onMessage(
              `Plan saved: entry ${plan.planned_entry}, stop ${plan.planned_stop}${plan.planned_target ? `, target ${plan.planned_target}` : ""}.`,
            );
          } else {
            // Refused (a fill arrived: the lock) or failed: back to the saved prices.
            const saved = this.confirmed.get(planId);
            if (saved) this.plans = this.plans.map((p) => (p.id === planId ? saved : p));
            this.opts.onMessage(result.error ?? "The plan could not be saved.");
          }
          this.draw();
          this.opts.onPlans(this.plans);
        });
      }, this.opts.debounceMs ?? PLAN_SAVE_DEBOUNCE_MS);
      this.saves.set(planId, save);
    }
    save(prices);
  }
}
