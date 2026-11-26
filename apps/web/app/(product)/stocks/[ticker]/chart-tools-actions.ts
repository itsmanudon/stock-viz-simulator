"use server";

/**
 * A6.7: what the chart's own tools read and write, through the web server.
 *
 * - The volume profile (public, `/v1/symbols/{t}/volume-profile`).
 * - "Alert on this drawing": the Rule DSL setup the rule alert judges. The
 *   alert itself goes through the alert form's own action
 *   (`alerts/actions.ts::createAlertAction`), so it is the same rule.
 * - "Plan a trade here" and the plan lines: the A5.4 plans API. The API holds
 *   the lock: a plan's prices are refused with 409 once it has a fill.
 */

import { revalidatePath } from "next/cache";

import { apiDetail } from "@/lib/api-error-detail";
import { ApiError } from "@/lib/api/client";
import { createPlan, listPlans, updatePlan } from "@/lib/api/plans";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";
import { createSetup } from "@/lib/api/setups-server";
import { getVolumeProfile } from "@/lib/api/volume-profile";
import { type TradePlan, planFigures } from "@/lib/plans";
import type { VolumeProfile } from "@/lib/volume-profile";

type Failure = { error: string };

function authedFailure(err: unknown, fallback: string): Failure {
  if (err instanceof UnauthenticatedError) return { error: "Sign in first." };
  if (err instanceof AuthedApiError) return { error: apiDetail(err.detail, fallback) };
  throw err;
}

export async function volumeProfileAction(
  ticker: string,
  range: { from: string; to: string; feed?: string | null; bins?: number },
): Promise<{ profile?: VolumeProfile; error?: string; offered?: boolean }> {
  try {
    return { profile: await getVolumeProfile(ticker, range) };
  } catch (err) {
    if (err instanceof ApiError) {
      const body = err.message.slice(err.message.indexOf(": ") + 2);
      const reason = apiDetail(body, "The volume profile could not be loaded.");
      // 409: no profile is offered here (an index, or no volume), for any range.
      return { error: reason, offered: err.status !== 409 };
    }
    return { error: "The volume profile could not be loaded." };
  }
}

/** A Rule DSL setup for a chart alert; the caller then creates the rule alert. */
export async function chartRuleSetupAction(
  name: string,
  rule: string,
): Promise<{ versionId?: number; error?: string }> {
  try {
    const setup = await createSetup({ name: name.slice(0, 120), rule, kind: "alert" });
    return { versionId: setup.latest_version.id };
  } catch (err) {
    return authedFailure(err, "The rule could not be saved.");
  }
}

/** The ticker's plans the chart draws: open (drafts) and active (locked). */
export async function chartPlansAction(
  ticker: string,
): Promise<{ plans?: TradePlan[]; error?: string }> {
  try {
    const result = await listPlans(null, { ticker });
    return {
      plans: result.plans.filter(
        (p) =>
          (p.status === "open" || p.status === "active") &&
          (p.source === "paper" || p.source === "imported"),
      ),
    };
  } catch (err) {
    return authedFailure(err, "Your plans could not be loaded.");
  }
}

export type ChartPlanInput = {
  ticker: string;
  entry: string;
  stop: string;
  target: string;
  size: string;
  why: string;
};

/** "Plan a trade here": a long plan in the default book, as the plan editor saves one. */
export async function createChartPlanAction(
  input: ChartPlanInput,
): Promise<{ plan?: TradePlan; error?: string }> {
  const problem = planFigures(input).problem;
  if (problem) return { error: problem };
  try {
    const plan = await createPlan({
      ticker: input.ticker,
      side: "long",
      link_open_position: false,
      planned_entry: input.entry,
      planned_stop: input.stop,
      planned_target: input.target || null,
      planned_size: input.size,
      why: input.why.trim() || null,
      tags: [],
    });
    revalidatePath("/portfolio");
    return { plan };
  } catch (err) {
    return authedFailure(err, "The plan could not be saved.");
  }
}

/** A dragged plan line: the draft's new prices (409 once the plan has a fill). */
export async function updatePlanLinesAction(
  id: number,
  prices: { entry: string; stop: string; target: string | null },
): Promise<{ plan?: TradePlan; error?: string }> {
  try {
    const plan = await updatePlan(id, {
      planned_entry: prices.entry,
      planned_stop: prices.stop,
      planned_target: prices.target,
    });
    revalidatePath("/portfolio");
    return { plan };
  } catch (err) {
    return authedFailure(err, "The plan could not be saved.");
  }
}
