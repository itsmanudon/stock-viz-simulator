import type { Metadata } from "next";

import { CostsSchedules } from "@/components/docs/costs-schedules";
import { DocArticle, DocSection, P } from "@/components/docs/docs-ui";
import { getFeeSchedules } from "@/lib/api";
import { findDocPage } from "@/lib/docs/nav";
import type { FeeSchedules } from "@/lib/fees";

// A4.2: the schedules come from the API (`GET /v1/fees/schedules`), so the
// page renders per request instead of at build time.
export const dynamic = "force-dynamic";

const PAGE = findDocPage("costs");

export const metadata: Metadata = PAGE
  ? { title: `${PAGE.title} · Docs`, description: PAGE.summary }
  : {};

export default async function CostsPage() {
  if (!PAGE) return null;
  let schedules: FeeSchedules | null = null;
  try {
    schedules = await getFeeSchedules();
  } catch {
    schedules = null;
  }
  return (
    <DocArticle page={PAGE}>
      <DocSection title="How costs are applied">
        <P>
          Every fill pays the fee schedule version in force on its fill date. Indian symbols use
          their exchange&apos;s equity delivery schedule by default, in paper trading and in
          backtests; other markets default to none (a US backtest can choose the US schedule).
          Results show the figures after costs first and before costs second.
        </P>
        <P>
          Each rate below was copied from the document linked beside it, on the date shown. Where no
          document read confirms a rate for a period, that period is left out: a fill before the
          first confirmed date is priced at the earliest rates on file, and the result says so.
          Price bands (circuit limits) and the T2T, ASM and ban lists are not checked yet.
        </P>
      </DocSection>
      {schedules ? (
        <CostsSchedules schedules={schedules} today={new Date().toISOString().slice(0, 10)} />
      ) : (
        <DocSection title="Schedules">
          <P>The schedules could not be loaded just now. Try again in a minute.</P>
        </DocSection>
      )}
    </DocArticle>
  );
}
