/**
 * /recommendations — retired with Signals in A2.4. The Checklist replaced it;
 * old links (and the `q` ticker search they carried) land there.
 */

import { permanentRedirect } from "next/navigation";

export default async function RecommendationsRedirect({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const { q } = await searchParams;
  const ticker = q?.trim();
  permanentRedirect(ticker ? `/checklist?q=${encodeURIComponent(ticker)}` : "/checklist");
}
