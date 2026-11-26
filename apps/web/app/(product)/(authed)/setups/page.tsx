/**
 * /setups — your saved rules and the read-only presets (A2.2).
 *
 * A setup is a named Rule DSL rule; editing it adds a version and never
 * changes an old one, so anything that names a version (a saved screen, and
 * later an alert or a backtest) keeps its exact rule. Each card opens the
 * rule in the screener, forks it into a setup of your own, or (yours only)
 * archives it. `?open=<id>` lists one setup's versions; `?archived=1` shows
 * archived setups too. Protected by proxy.ts.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { ResearchPageHeader } from "@/components/research-page-header";
import { Button } from "@/components/ui/button";
import { formatUtcDateTime } from "@/lib/api-time";
import type { Setup, SetupDetail } from "@/lib/api/setups";
import { getSetup, listSetups } from "@/lib/api/setups-server";
import { eventStudyHref } from "@/lib/event-study";
import { SETUP_KIND_LABEL, screenerHrefForRule, setupsHref } from "@/lib/setups-view";
import { archiveSetupAction, forkSetupAction } from "./actions";

export const metadata: Metadata = { title: "Setups" };

type Params = { open?: string; archived?: string };

export default async function SetupsPage({ searchParams }: { searchParams: Promise<Params> }) {
  const params = await searchParams;
  const archived = params.archived === "1";
  const openId = Number(params.open);

  let setups: Setup[] = [];
  let error: string | null = null;
  try {
    setups = await listSetups(archived);
  } catch {
    error = "Your setups could not be loaded. Try again in a moment.";
  }
  let opened: SetupDetail | null = null;
  if (Number.isInteger(openId) && setups.some((s) => s.id === openId)) {
    try {
      opened = await getSetup(openId);
    } catch {
      opened = null;
    }
  }
  const mine = setups.filter((s) => s.owned);
  const presets = setups.filter((s) => s.is_preset);

  return (
    <div className="w-full px-4 py-6 sm:px-6 lg:py-7 xl:px-8">
      <ResearchPageHeader
        title="Setups"
        description="Saved rules. Editing a rule adds a version and never changes an old one. Presets are read-only: fork one to make it yours."
        actions={
          <Link
            href={setupsHref({ archived: !archived })}
            className="text-xs text-text-secondary hover:text-foreground hover:underline"
          >
            {archived ? "Hide archived" : "Show archived"}
          </Link>
        }
      />

      {error ? (
        <p role="alert" className="mt-5 rounded-md border border-border-muted bg-card p-4 text-sm">
          {error}
        </p>
      ) : (
        <div className="mt-5 space-y-8">
          <section aria-labelledby="mine">
            <h2 id="mine" className="mb-3 text-sm font-semibold">
              Your setups
            </h2>
            {mine.length ? (
              <ul className="grid gap-3 lg:grid-cols-2">
                {mine.map((s) => (
                  <SetupCard key={s.id} setup={s} opened={opened?.id === s.id ? opened : null} />
                ))}
              </ul>
            ) : (
              <p className="rounded-md border border-border-muted bg-card p-4 text-sm text-text-secondary">
                None yet. Write a rule on the{" "}
                <Link href="/screener" className="underline">
                  screener
                </Link>{" "}
                and save it as a setup, or fork a preset below.
              </p>
            )}
          </section>
          <section aria-labelledby="presets">
            <h2 id="presets" className="mb-3 text-sm font-semibold">
              Presets
            </h2>
            {presets.length ? (
              <ul className="grid gap-3 lg:grid-cols-2">
                {presets.map((s) => (
                  <SetupCard key={s.id} setup={s} opened={opened?.id === s.id ? opened : null} />
                ))}
              </ul>
            ) : (
              <p className="text-sm text-text-secondary">No presets are seeded yet.</p>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

function SetupCard({ setup, opened }: { setup: Setup; opened: SetupDetail | null }) {
  const latest = setup.latest_version;
  return (
    <li
      id={`setup-${setup.id}`}
      className="space-y-3 rounded-md border border-border-muted bg-card p-4 text-sm"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-semibold">{setup.name}</h3>
        <span className="text-2xs text-text-tertiary">
          {SETUP_KIND_LABEL[setup.kind]} · version {latest.version}
          {setup.version_count > 1 ? ` of ${setup.version_count}` : ""}
          {setup.is_preset ? " · preset" : ""}
          {setup.archived_at ? " · archived" : ""}
        </span>
      </div>
      <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded bg-surface-secondary p-2 font-mono text-2xs leading-5">
        {latest.rule_text}
      </pre>
      {setup.description ? (
        <details className="text-xs text-text-secondary">
          <summary className="cursor-pointer text-text-tertiary hover:text-foreground">
            Source and limits
          </summary>
          <p className="mt-2 leading-5">{setup.description}</p>
        </details>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <Button asChild size="sm">
          <Link href={screenerHrefForRule(latest.rule_text)}>Open in screener</Link>
        </Button>
        <Button asChild size="sm" variant="outline">
          <Link href={eventStudyHref({ setup: latest.id })} data-testid="setup-event-study">
            Run event study
          </Link>
        </Button>
        <form action={forkSetupAction}>
          <input type="hidden" name="id" value={setup.id} />
          <Button type="submit" size="sm" variant="outline">
            Fork
          </Button>
        </form>
        {setup.owned && !setup.archived_at ? (
          <form action={archiveSetupAction}>
            <input type="hidden" name="id" value={setup.id} />
            <Button type="submit" size="sm" variant="ghost">
              Archive
            </Button>
          </form>
        ) : null}
        <Link
          href={opened ? setupsHref({}) : `${setupsHref({ open: setup.id })}#setup-${setup.id}`}
          className="ml-auto text-xs text-text-secondary hover:text-foreground hover:underline"
          aria-expanded={opened !== null}
        >
          {opened ? "Hide versions" : `Versions (${setup.version_count})`}
        </Link>
      </div>
      {opened ? (
        <ol aria-label={`Versions of ${setup.name}`} className="space-y-2 border-t pt-3">
          {opened.versions.map((v) => (
            <li key={v.id} className="space-y-1 text-xs">
              <p className="text-text-tertiary">
                Version {v.version} · {formatUtcDateTime(v.created_at)}
              </p>
              <p className="break-words font-mono text-2xs">{v.canonical_text}</p>
              {v.notes ? <p className="text-text-secondary">{v.notes}</p> : null}
            </li>
          ))}
        </ol>
      ) : null}
      {setup.forked_from_version_id ? (
        <p className="text-2xs text-text-tertiary">
          Forked from version #{setup.forked_from_version_id}.
        </p>
      ) : null}
    </li>
  );
}
