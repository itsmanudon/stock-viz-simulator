/**
 * /settings — user preferences.
 *
 * Exposes the leaderboard opt-in toggle and the display-currency selector.
 * Both forms use server actions so the page stays a server component.
 */

import { revalidatePath } from "next/cache";

import { auth } from "@/auth";
import { SettingsWorkspace } from "@/components/settings-workspace";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getProfile, patchProfile } from "@/lib/api/leaderboard";

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

  return (
    <div className="density-workspace container mx-auto max-w-6xl px-4 py-6 sm:px-6 lg:py-8">
      <header className="mb-7 max-w-2xl">
        <p className="text-2xs font-semibold tracking-[0.14em] text-brand uppercase">
          Account / workspace
        </p>
        <h1 className="mt-1.5 text-3xl font-semibold tracking-tight">Settings</h1>
        <p className="mt-2 text-sm leading-relaxed text-text-secondary">
          Keep your paper-trading workspace useful and private. These controls change real account
          preferences or this browser&apos;s interface only.
        </p>
      </header>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_18rem] lg:items-start">
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Display currency</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm text-muted-foreground">
                Portfolio totals convert to this currency. Cash remains stored in USD; trades stay
                denominated in the symbol&apos;s native currency.
              </p>
              <form action={setDisplayCurrency} className="flex flex-wrap items-center gap-3">
                <label htmlFor="display-currency" className="sr-only">
                  Display currency
                </label>
                <select
                  id="display-currency"
                  name="display_currency"
                  defaultValue={profile.display_currency || "USD"}
                  className="flex h-9 w-32 rounded-md border border-input bg-transparent px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                >
                  {SUPPORTED_CURRENCIES.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
                <button
                  type="submit"
                  className="rounded-md border border-brand px-4 py-2 text-sm font-medium text-brand transition hover:bg-brand-muted"
                >
                  Save currency
                </button>
              </form>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Leaderboard visibility</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm text-muted-foreground">
                When enabled, your username and portfolio return appear on the public leaderboard.
                Holdings and cash are never shown.
              </p>
              <form action={setPublicProfile} className="flex flex-wrap items-center gap-4">
                <input
                  type="hidden"
                  name="public_profile"
                  value={profile.public_profile ? "false" : "true"}
                />
                <button
                  type="submit"
                  className={`rounded-md border px-4 py-2 text-sm font-medium transition hover:bg-accent ${profile.public_profile ? "border-destructive text-destructive" : "border-brand text-brand"}`}
                >
                  {profile.public_profile ? "Remove me from leaderboard" : "Show me on leaderboard"}
                </button>
                <span className="text-sm text-muted-foreground">
                  Currently:{" "}
                  <span className={profile.public_profile ? "text-positive" : "text-text-tertiary"}>
                    {profile.public_profile ? "visible" : "hidden"}
                  </span>
                </span>
              </form>
            </CardContent>
          </Card>
        </div>

        <aside className="space-y-4">
          <SettingsWorkspace email={session?.user?.email} name={session?.user?.name} />
          <section
            className="rounded-xl border border-border-muted bg-surface-secondary/45 p-4"
            aria-labelledby="status-heading"
          >
            <p className="text-2xs font-semibold tracking-[0.14em] text-text-tertiary uppercase">
              System context
            </p>
            <h2 id="status-heading" className="mt-2 text-sm font-semibold">
              StockViz paper workspace
            </h2>
            <dl className="mt-3 space-y-2 text-xs">
              <div className="flex justify-between gap-3">
                <dt className="text-text-tertiary">Pricing</dt>
                <dd className="text-right text-text-secondary">End-of-day bars</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-text-tertiary">Trading</dt>
                <dd className="text-right text-text-secondary">Paper only</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-text-tertiary">Data source</dt>
                <dd className="text-right text-text-secondary">Configured providers</dd>
              </div>
            </dl>
          </section>
        </aside>
      </div>
    </div>
  );
}
