/**
 * /event-study — what followed a Rule DSL trigger (A4.5, M7.3).
 *
 * Any condition (inline, a setup version, or a news or delivery rule) on a
 * market, a ticker list or your watchlist: forward 5-, 20- and 60-session
 * returns net of round-trip costs against the base rate of the same
 * universe and dates. The URL holds the study (`rule` or `setup`, `market`
 * | `tickers` | `watchlist`, `from`, `to`, `cooldown`), so a study is a
 * link; the screener's rule panel and /setups link here. Signed in the
 * study runs as you (watchlists, your setups); signed out it is public and
 * limited per visitor. `/news-reactions` stays the news-only CAR study.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { auth } from "@/auth";
import { EventStudyForm } from "@/components/event-study/event-study-form";
import { ScanStudyView } from "@/components/event-study/scan-study-view";
import { PageFrame } from "@/components/page-frame";
import { ResearchPageHeader, ResearchSubnav } from "@/components/research-page-header";
import type { StrategySetupOption } from "@/components/rule-strategy/rule-field";
import { VisitorLimitNotice } from "@/components/visitor-limit-notice";
import { ApiError } from "@/lib/api/client";
import { runScanEventStudy } from "@/lib/api/research";
import { runScanEventStudyAsUser } from "@/lib/api/research-server";
import { AuthedApiError } from "@/lib/api/server";
import { listPresets } from "@/lib/api/setups";
import { listSetups } from "@/lib/api/setups-server";
import { listWatchlists } from "@/lib/api/watchlist";
import { drillLaunchHref } from "@/lib/drills";
import {
  DEFAULT_TRIGGER,
  type ScanStudy,
  type StudyParams,
  parseStudyParams,
  studyRequest,
} from "@/lib/event-study";
import { describeRuleError } from "@/lib/screener-view";
import { checkVisitorLimit } from "@/lib/visitor-limit";

export const metadata: Metadata = { title: "Event study" };

function detailOf(raw: string): string {
  const body = raw.replace(/^API \d+ [^:]+:\s*/, "");
  try {
    const detail = (JSON.parse(body) as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object" && "kind" in detail && "message" in detail) {
      return describeRuleError(detail as Parameters<typeof describeRuleError>[0]);
    }
  } catch {
    // not JSON
  }
  return body || "The study could not be run.";
}

export default async function EventStudyPage({
  searchParams,
}: {
  searchParams: Promise<StudyParams>;
}) {
  const params = parseStudyParams(await searchParams);
  const request = studyRequest(params);
  const session = await auth();
  const signedIn = Boolean(session?.user?.id);
  if (request && !signedIn) {
    const limit = await checkVisitorLimit("eventStudy");
    if (!limit.allowed) return <VisitorLimitNotice retryAfterSeconds={limit.retryAfterSeconds} />;
  }
  const [presets, own, lists] = await Promise.all([
    listPresets().catch(() => []),
    signedIn ? listSetups().catch(() => []) : Promise.resolve([]),
    signedIn ? listWatchlists().catch(() => []) : Promise.resolve([]),
  ]);
  const seen = new Set<number>();
  const setups: StrategySetupOption[] = [];
  for (const s of [...own, ...presets]) {
    const v = s.latest_version;
    if (!v || seen.has(v.id)) continue;
    seen.add(v.id);
    setups.push({ versionId: v.id, name: s.name, rule: v.rule_text, preset: s.is_preset });
  }

  let study: ScanStudy | null = null;
  let error: string | null = null;
  if (request) {
    try {
      study = signedIn ? await runScanEventStudyAsUser(request) : await runScanEventStudy(request);
    } catch (err) {
      if (err instanceof AuthedApiError) error = detailOf(err.detail);
      else if (err instanceof ApiError) error = detailOf(err.message);
      else error = "The study could not be run.";
    }
  }

  return (
    <PageFrame width="workstation" className="py-5 sm:py-7">
      <ResearchPageHeader
        title="Event study"
        description="What followed a rule turning true: forward returns net of costs, against the base rate of the same symbols and dates. Association, not cause."
      />
      <ResearchSubnav current="/event-study" />
      <EventStudyForm
        initial={request ? params : { ...params, rule: params.rule || DEFAULT_TRIGGER }}
        setups={setups}
        watchlists={lists.map((w) => ({ id: w.id, name: w.name, count: w.item_count }))}
        signedIn={signedIn}
      />
      <section aria-label="Study results" className="mt-6">
        {error ? (
          <p
            className="rounded-md border border-negative/40 bg-negative/5 px-3 py-2 text-sm"
            role="alert"
          >
            {error}
          </p>
        ) : study ? (
          <>
            {signedIn && request ? (
              <p className="mb-4 text-sm">
                <Link
                  href={drillLaunchHref({
                    ...(request.trigger.setup_version_id
                      ? { setupVersionId: request.trigger.setup_version_id }
                      : { rule: request.trigger.rule ?? study.trigger.text }),
                    tickers: request.universe.tickers ?? undefined,
                    watchlistId: request.universe.watchlist_id ?? undefined,
                    market: request.universe.market ?? undefined,
                    from: study.from,
                    to: study.to,
                  })}
                  className="underline-offset-4 hover:underline"
                  data-testid="study-drill"
                >
                  Drill these triggers
                </Link>{" "}
                <span className="text-text-secondary">
                  — replay a sample of these events yourself, anonymised, and score your process.
                </span>
              </p>
            ) : null}
            <ScanStudyView study={study} />
          </>
        ) : (
          <p className="text-sm text-text-secondary">
            Pick a trigger and a universe, then run the study. Each event is a session where the
            rule turned true; what followed is measured over 5, 20 and 60 sessions.
          </p>
        )}
      </section>
    </PageFrame>
  );
}
