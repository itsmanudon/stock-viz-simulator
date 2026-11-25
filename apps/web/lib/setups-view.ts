/**
 * URL helpers for /setups and links into the screener (A2.2). Pure, so they
 * can be unit-tested; the page is an async server component.
 */

/** The screener running `rule` (a shareable link; no other filters). */
export function screenerHrefForRule(rule: string, mode: "met_only" | "all" = "met_only"): string {
  const q = new URLSearchParams({ rule });
  if (mode === "all") q.set("rule_mode", "all");
  return `/screener?${q.toString()}`;
}

/** /setups with one setup's versions open and/or archived setups shown. */
export function setupsHref({ open, archived }: { open?: number; archived?: boolean }): string {
  const q = new URLSearchParams();
  if (open) q.set("open", String(open));
  if (archived) q.set("archived", "1");
  const qs = q.toString();
  return qs ? `/setups?${qs}` : "/setups";
}

export const SETUP_KIND_LABEL: Record<"screen" | "alert" | "strategy" | "checklist", string> = {
  screen: "Screen",
  alert: "Alert",
  strategy: "Strategy",
  checklist: "Checklist",
};
