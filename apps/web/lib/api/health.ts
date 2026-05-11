import { ApiError, apiGet } from "./client";
import type { Health } from "./types";

/**
 * Health probe used by the landing page. Swallows network errors so the page
 * can render a "degraded" indicator instead of throwing.
 */
export async function getApiHealth(): Promise<Health> {
  try {
    return await apiGet<Health>("/health");
  } catch (err) {
    if (err instanceof ApiError) {
      return { status: "degraded", version: "unknown", database: "down" };
    }
    return { status: "degraded", version: "unreachable", database: "down" };
  }
}
