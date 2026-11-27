/** /india-options — A7.14 (M6.1, M6.3): NIFTY and BANKNIFTY option summaries (local files). */

import type { Metadata } from "next";

import { FoIndiaView } from "@/components/fo-india-view";
import { PageHeader } from "@/components/page-header";
import { getFoIndia } from "@/lib/api/fo";

export const metadata: Metadata = { title: "India options" };

export default async function IndiaOptionsPage() {
  const data = await getFoIndia().catch(() => null);
  return (
    <div className="w-full space-y-6 px-4 py-6 sm:px-6 lg:py-7 xl:px-8">
      <PageHeader
        eyebrow="Markets"
        title="India options"
        description="Index option volatility, skew and open interest by strike offset, from stored daily summaries."
      />
      {data ? (
        <FoIndiaView data={data} />
      ) : (
        <p className="text-sm text-text-secondary" data-testid="fo-error">
          The option summaries could not be loaded just now.
        </p>
      )}
    </div>
  );
}
