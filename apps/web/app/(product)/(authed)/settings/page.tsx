/**
 * /settings — user preferences (Aurora board v3).
 *
 * Main column: display currency and leaderboard visibility (server actions,
 * so both work without JavaScript), then interface preferences that live in
 * this browser. Aside: the account's paper card and details, keyboard
 * shortcuts, and the system context.
 */

import type { Metadata } from "next";
import { revalidatePath } from "next/cache";

import { auth } from "@/auth";
import { PageHeader } from "@/components/page-header";
import { PaperCard } from "@/components/paper-card";
import { AccountDetails, InterfacePanel, KeyboardShortcuts } from "@/components/settings-workspace";
import { getProfile, patchProfile } from "@/lib/api/leaderboard";
import { cn } from "@/lib/utils";

export const metadata: Metadata = { title: "Settings" };

const SUPPORTED_CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CAD", "INR"] as const;

async function setPublicProfile(formData: FormData) {
  "use server";
  const next = formData.get("public_profile") === "true";
  await patchProfile({ public_profile: next });
  revalidatePath("/settings");
}

async function setDisplayCurrency(formData: FormData) {
  "use server";
  const raw = formData.get("display_currency");
  const next = typeof raw === "string" ? raw.toUpperCase() : "USD";
  if (!SUPPORTED_CURRENCIES.includes(next as (typeof SUPPORTED_CURRENCIES)[number])) return;
  await patchProfile({ display_currency: next });
  revalidatePath("/settings");
  revalidatePath("/portfolio");
}

export default async function SettingsPage() {
  const [profile, session] = await Promise.all([getProfile(), auth()]);
  const visible = profile.public_profile;

  return (
    <div className="density-workspace mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 lg:py-7">
      <PageHeader
        eyebrow="Account"
        title="Settings"
        description="Account preferences are saved to your profile; interface preferences stay in this browser."
      />

      <div className="mt-6 grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem] lg:items-start">
        <div className="space-y-4">
          <SettingsPanel title="Display currency" id="currency-heading">
            <form
              action={setDisplayCurrency}
              className="flex flex-wrap items-end gap-3"
              aria-labelledby="currency-heading"
            >
              <div className="grid gap-1.5">
                <label htmlFor="display-currency" className="text-xs text-text-tertiary">
                  Show totals in
                </label>
                <select
                  id="display-currency"
                  name="display_currency"
                  defaultValue={profile.display_currency || "USD"}
                  className="flex h-9 w-40 rounded-md border border-input bg-transparent px-3 py-2 font-mono text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                >
                  {SUPPORTED_CURRENCIES.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </div>
              <button
                type="submit"
                className="h-9 rounded-full bg-primary px-5 text-sm font-medium text-primary-foreground transition hover:bg-primary/90"
              >
                Save currency
              </button>
            </form>
            <p className="mt-3 text-xs leading-relaxed text-text-tertiary">
              Cash is held in USD. Each trade stays in its listing&apos;s own currency; only
              portfolio totals are converted.
            </p>
          </SettingsPanel>

          <SettingsPanel title="Leaderboard" id="leaderboard-heading">
            <form action={setPublicProfile} className="flex items-center justify-between gap-4">
              <input type="hidden" name="public_profile" value={visible ? "false" : "true"} />
              <div className="min-w-0">
                <p id="leaderboard-label" className="text-sm font-medium">
                  Show me on the public leaderboard
                </p>
                <p className="mt-0.5 text-xs leading-relaxed text-text-tertiary">
                  Currently {visible ? "visible" : "hidden"}. Only your username and return are
                  shown; holdings and cash never are.
                </p>
              </div>
              {/* A submit button acting as a switch: one press saves the
                  opposite state, and it works without JavaScript. */}
              <button
                type="submit"
                role="switch"
                aria-checked={visible}
                aria-labelledby="leaderboard-label"
                className={cn(
                  "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition",
                  visible ? "border-brand bg-brand" : "border-border bg-surface-secondary",
                )}
              >
                <span
                  aria-hidden
                  className={cn(
                    "size-4 rounded-full bg-background shadow transition-transform",
                    visible ? "translate-x-6" : "translate-x-1",
                  )}
                />
              </button>
            </form>
          </SettingsPanel>

          <SettingsPanel title="Interface" id="interface-heading">
            <InterfacePanel />
          </SettingsPanel>
        </div>

        <aside className="space-y-4">
          <SettingsPanel title="Account" id="account-heading">
            {/* The account's paper card, in its display currency: the one
                brand moment on this page. */}
            <div className="relative isolate mb-4">
              <div aria-hidden className="brand-glow -top-6 -left-6 -z-10 h-40 w-64 opacity-50" />
              <PaperCard currency={profile.display_currency || "USD"} className="w-full" />
            </div>
            <AccountDetails email={session?.user?.email} name={session?.user?.name} />
          </SettingsPanel>

          <SettingsPanel title="Keyboard shortcuts" id="shortcuts-heading">
            <KeyboardShortcuts />
          </SettingsPanel>

          <SettingsPanel title="System" id="status-heading">
            <dl className="divide-y divide-border-muted text-xs">
              {[
                ["Pricing", "End-of-day bars"],
                ["Trading", "Paper only"],
                ["Data source", "Configured providers"],
              ].map(([term, value]) => (
                <div key={term} className="flex justify-between gap-3 py-2">
                  <dt className="text-text-tertiary">{term}</dt>
                  <dd className="text-right text-text-secondary">{value}</dd>
                </div>
              ))}
            </dl>
          </SettingsPanel>
        </aside>
      </div>
    </div>
  );
}

/** A titled settings card: header row with a hairline, then its content. */
function SettingsPanel({
  title,
  id,
  children,
}: {
  title: string;
  id: string;
  children: React.ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="rounded-xl border border-border-muted bg-card">
      <h2 id={id} className="border-b border-border-muted px-5 py-3.5 text-sm font-medium">
        {title}
      </h2>
      <div className="px-5 py-4">{children}</div>
    </section>
  );
}
