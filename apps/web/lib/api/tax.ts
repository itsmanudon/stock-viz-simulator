import "server-only";

/** `/v1/tax/india` (A7.12, M10.7): an INR book's FY capital gains estimate. */

import type { IndiaTax } from "@/lib/india-tax";

import { authedGet } from "./server";

export function getIndiaTax(book: number | null, fy: string, surcharge: number): Promise<IndiaTax> {
  const q = new URLSearchParams({ fy, surcharge: String(surcharge) });
  if (book) q.set("book", String(book));
  return authedGet<IndiaTax>(`/v1/tax/india?${q.toString()}`);
}
