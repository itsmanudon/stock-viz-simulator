"use client";

/**
 * A4.7: a drill's chart is A4.6's `ReplayChart` with the drill's own routes:
 * drawings through `/v1/drills/{id}/drawings` (dates translated by the API
 * while the drill is anonymised) and the page path `/drills/{id}`.
 */

import { type ComponentProps, useMemo } from "react";

import {
  createDrillDrawingAction,
  deleteDrillDrawingAction,
  updateDrillDrawingAction,
} from "@/app/(product)/(authed)/drills/actions";
import type { DrawingActions } from "@/components/drawings/chart-workbench";
import { ReplayChart } from "@/components/replay-chart";

type Props = Omit<
  ComponentProps<typeof ReplayChart>,
  "basePath" | "drawingActions" | "sessionId"
> & {
  drillId: number;
};

export function DrillChart({ drillId, ...chart }: Props) {
  const actions = useMemo<DrawingActions>(
    () => ({
      create: (input) => createDrillDrawingAction(drillId, input),
      update: (id, changes) => updateDrillDrawingAction(drillId, id, changes),
      remove: (id) => deleteDrillDrawingAction(drillId, id),
    }),
    [drillId],
  );
  return (
    <ReplayChart
      {...chart}
      sessionId={drillId}
      basePath={`/drills/${drillId}`}
      drawingActions={actions}
    />
  );
}
