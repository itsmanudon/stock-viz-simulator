"use client";

/**
 * The replay chart (A4.6, M9.1): A3's one multi-pane chart with the
 * Indicators menu, drawings and event markers, all cut at the replay clock.
 *
 * - Bars, indicators and events come from the session's own routes, which the
 *   API cuts at `current_at`: indicators are computed from bars up to the
 *   clock (warm-up from earlier stored bars), news shows once its
 *   `available_at` has passed the clock, and the markers are the session's
 *   fills. Never the live bars, indicators or events routes.
 * - Drawings are the session's own (`replay/[sessionId]/drawing-actions.ts`):
 *   live-chart drawings never show here, and these never show there. The
 *   anchored VWAP is left out (its line reads every stored bar).
 * - The indicator choice is URL state (`?indicators=`), as on the stock page.
 */

import { useRouter } from "next/navigation";
import { type ComponentProps, useMemo } from "react";

import {
  createReplayDrawingAction,
  deleteReplayDrawingAction,
  updateReplayDrawingAction,
} from "@/app/(product)/(authed)/replay/[sessionId]/drawing-actions";
import { ChartWorkbench, type DrawingActions } from "@/components/drawings/chart-workbench";
import { IndicatorMenu } from "@/components/indicator-menu";
import type { IndicatorCatalogItem } from "@/lib/api/types";
import { type DrawingKind, KIND_SPECS } from "@/lib/drawings/kinds";
import type { StockIndicator } from "@/lib/stock-workspace";

/** Every drawing kind except the anchored VWAP and (A6.7) the volume profile. */
export const REPLAY_DRAWING_KINDS: readonly DrawingKind[] = KIND_SPECS.map((s) => s.kind).filter(
  (kind) => kind !== "avwap" && kind !== "volume_profile",
);

/** The replay page's href with a new `indicators` list (other params kept). */
export function replayIndicatorsHref(
  pathname: string,
  search: string,
  next: readonly string[],
): string {
  const params = new URLSearchParams(search);
  if (next.length) params.set("indicators", next.join(","));
  else params.delete("indicators");
  const qs = params.toString();
  return qs ? `${pathname}?${qs}` : pathname;
}

type WorkbenchProps = ComponentProps<typeof ChartWorkbench>;

type Props = Omit<WorkbenchProps, "actions" | "kinds" | "signedIn" | "callbackUrl"> & {
  sessionId: number;
  indicators: StockIndicator[];
  catalog: IndicatorCatalogItem[] | null;
  /** The page's query string (without `?`), so a new study keeps the other params. */
  search: string;
  /** A4.7: a drill's page path and its own drawing actions (`/v1/drills/{id}/drawings`). */
  basePath?: string;
  drawingActions?: DrawingActions;
};

export function ReplayChart({
  sessionId,
  indicators,
  catalog,
  search,
  basePath,
  drawingActions,
  ...chart
}: Props) {
  const router = useRouter();
  const pathname = basePath ?? `/replay/${sessionId}`;
  const replayActions = useMemo<DrawingActions>(
    () => ({
      create: (input) => createReplayDrawingAction(sessionId, input),
      update: (id, changes) => updateReplayDrawingAction(sessionId, id, changes),
      remove: (id) => deleteReplayDrawingAction(sessionId, id),
    }),
    [sessionId],
  );
  const actions = drawingActions ?? replayActions;
  return (
    <div className="space-y-2" data-testid="replay-chart">
      <div className="flex flex-wrap items-center gap-2 px-2">
        <IndicatorMenu
          indicators={indicators}
          catalog={catalog}
          onChange={(next) =>
            router.push(replayIndicatorsHref(pathname, search, next), {
              scroll: false,
            })
          }
        />
        <p className="text-2xs text-text-tertiary" data-testid="replay-chart-rule">
          Indicators use bars up to the replay date only; news appears once it was published.
        </p>
      </div>
      <ChartWorkbench
        {...chart}
        signedIn
        callbackUrl={pathname}
        actions={actions}
        kinds={REPLAY_DRAWING_KINDS}
      />
    </div>
  );
}
