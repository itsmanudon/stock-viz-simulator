import "server-only";

/** A9.12 (M11.6): the morning brief and the weekly journal review (signed in). */

import type { components } from "./schema";
import { authedGet } from "./server";

export type MorningBrief = components["schemas"]["MorningBriefOut"];
export type WeeklyReview = components["schemas"]["WeeklyReviewOut"];

export function getBrief(): Promise<MorningBrief> {
  return authedGet<MorningBrief>("/v1/brief");
}

export function getWeeklyReview(
  opts: { book?: string; weekEnd?: string } = {},
): Promise<WeeklyReview> {
  const q = new URLSearchParams();
  if (opts.book) q.set("book", opts.book);
  if (opts.weekEnd) q.set("week_end", opts.weekEnd);
  const s = q.toString();
  return authedGet<WeeklyReview>(`/v1/journal/weekly${s ? `?${s}` : ""}`);
}
