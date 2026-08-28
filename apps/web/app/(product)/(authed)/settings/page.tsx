/**
 * /settings — user preferences.
 *
 * Exposes the leaderboard opt-in toggle and the display-currency selector.
 * Both forms use server actions so the page stays a server component.
 */

import { revalidatePath } from "next/cache";

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
  const profile = await getProfile();

  return (
    <div className="container mx-auto max-w-lg px-4 py-10 sm:px-6">
      <header className="mb-6">
        <h1 className="text-3xl font-bold tracking-tight">Settings</h1>
      </header>

      <Card className="mb-4">
        <CardHeader>
          <CardTitle className="text-base">Display currency</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            All portfolio totals are converted to this currency. Cash is stored in USD and converted
            on display; trades stay denominated in the symbol&apos;s native currency.
          </p>
          <form action={setDisplayCurrency} className="flex items-center gap-3">
            <select
              name="display_currency"
              defaultValue={profile.display_currency || "USD"}
              className="flex h-10 w-32 rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              {SUPPORTED_CURRENCIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            <button
              type="submit"
              className="rounded-md border border-primary px-4 py-2 text-sm font-medium text-primary transition hover:bg-accent"
            >
              Save
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
            When enabled, your username and portfolio return appear on the public leaderboard. Your
            holdings and cash balance are never shown.
          </p>
          <form action={setPublicProfile} className="flex items-center gap-4">
            <input
              type="hidden"
              name="public_profile"
              value={profile.public_profile ? "false" : "true"}
            />
            <button
              type="submit"
              className={`rounded-md border px-4 py-2 text-sm font-medium transition hover:bg-accent ${
                profile.public_profile
                  ? "border-destructive text-destructive"
                  : "border-primary text-primary"
              }`}
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
  );
}
