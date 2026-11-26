/** A7.2 (M3.2): weekly RS-Trend and RS-Momentum per sector. */

import { apiGet } from "./client";
import type { components } from "./schema";

export type Rotation = components["schemas"]["RotationOut"];
export type RotationSector = components["schemas"]["RotationSectorOut"];

export function getSectorRotation(market: "US" | "IN"): Promise<Rotation> {
  return apiGet<Rotation>(`/v1/sector-rotation?market=${market}&weeks=10`, {
    revalidateSeconds: 600,
    tags: ["bars"],
  });
}
