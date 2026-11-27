/**
 * /macro — A9.7 (M1.10, M3.5): US and India macro series from FRED and the
 * spreads built from them. Public; read from what the weekly fetch stored.
 */

import type { Metadata } from "next";

import { MacroView } from "@/components/macro-view";
import { PageHeader } from "@/components/page-header";
import { getMacroOverview } from "@/lib/api/macro";

export const metadata: Metadata = { title: "Macro" };

export default async function MacroPage() {
  let overview: Awaited<ReturnType<typeof getMacroOverview>> | null = null;
  try {
    overview = await getMacroOverview();
  } catch {
    overview = null;
  }
  return (
    <div className="w-full space-y-6 px-4 py-6 sm:px-6 lg:py-7 xl:px-8">
      <PageHeader
        title="Macro"
        description="Rates, inflation, growth, credit, the dollar and commodities, as FRED publishes them, with the spreads traders watch."
      />
      {overview ? (
        <MacroView overview={overview} />
      ) : (
        <p className="text-sm text-text-secondary" data-testid="macro-error">
          The macro series could not be loaded just now.
        </p>
      )}
    </div>
  );
}
