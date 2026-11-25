/**
 * Evidence badges on studies (A3.4, M2.6): the A2.4 evidence grade of a
 * study's canonical signal, with the sample, horizon and universe stamp
 * behind it. A study with no canonical signal says "No grade"; a grade is
 * never made up. The grade belongs to the default parameters, so a study
 * drawn with other values says so. Wording is neutral: association, not
 * cause, and not advice.
 */

import { universeSummary } from "@/components/universe-note";
import type { IndicatorCatalogItem } from "@/lib/api/types";
import { evidenceFigures, evidenceSample } from "@/lib/checklist-view";
import { parseIndicatorKey } from "@/lib/stock-workspace";

export type IndicatorBadge = {
  /** Short text on the chip: "A", "B", ..., "No grade", "Not graded", "Too few". */
  text: string;
  graded: boolean;
  /** The whole story, for the tooltip and screen readers. */
  title: string;
};

export const ASSOCIATION_NOTE = "Association, not cause; not advice.";

/** The badge for `item`, drawn as `key` (a chart key with parameters), if given. */
export function indicatorBadge(
  item: IndicatorCatalogItem | undefined,
  key?: string,
): IndicatorBadge {
  const signal = item?.signal;
  if (!item || !signal) {
    return {
      text: "No grade",
      graded: false,
      title: "No grade: this study has no canonical signal to grade.",
    };
  }
  const rule = `Signal: ${signal.description} (${signal.rule}), on the default parameters.`;
  const own = key ? parseIndicatorKey(key) : null;
  const differs =
    own !== null &&
    own.values.length > 0 &&
    own.values.some((v, i) => v !== item.parameters[i]?.default);
  const note = differs ? ` Graded on ${item.default_key}, not on the ${key} drawn.` : "";
  const evidence = signal.evidence;
  if (!evidence) {
    return {
      text: "Not graded",
      graded: false,
      title: `Not graded yet: the evidence study has not run. ${rule}`,
    };
  }
  const universe = `Universe: ${universeSummary(evidence.universe) ?? evidence.universe.name}`;
  const sample = `${evidenceSample(evidence)}.`;
  if (evidence.grade === "insufficient") {
    return {
      text: "Too few",
      graded: false,
      title: `Too few events to grade (under 30). ${rule} ${sample} ${universe}${note}`,
    };
  }
  return {
    text: evidence.grade,
    graded: true,
    title:
      `Grade ${evidence.grade}. ${rule} ${sample} ${evidenceFigures(evidence)}. ` +
      `${universe} ${ASSOCIATION_NOTE}${note}`,
  };
}

/** Badges per chart key, for the legend. */
export function badgesFor(
  keys: readonly string[],
  catalog: readonly IndicatorCatalogItem[] | null | undefined,
): Record<string, IndicatorBadge> {
  if (!catalog) return {};
  const out: Record<string, IndicatorBadge> = {};
  for (const key of keys) {
    const base = parseIndicatorKey(key)?.base;
    const item = catalog.find((c) => c.key === base);
    if (item) out[key] = indicatorBadge(item, key);
  }
  return out;
}
