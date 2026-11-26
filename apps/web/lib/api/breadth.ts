/** A7.1 (M3.3): market breadth and diffusion per session, from stored daily bars. */

import { apiGet } from "./client";
import type { components } from "./schema";

export type Breadth = components["schemas"]["BreadthOut"];
export type BreadthPoint = components["schemas"]["BreadthPointOut"];

export function getBreadth(market: "US" | "IN"): Promise<Breadth> {
  return apiGet<Breadth>(`/v1/breadth?market=${market}`, {
    revalidateSeconds: 600,
    tags: ["bars"],
  });
}
