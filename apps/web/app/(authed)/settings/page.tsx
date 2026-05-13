/**
 * /settings — user preferences.
 *
 * Currently exposes the leaderboard opt-in toggle. The form uses a server
 * action so no client JS is needed for the toggle itself.
 */

import { revalidatePath } from "next/cache";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getProfile, patchProfile } from "@/lib/api/leaderboard";

async function setPublicProfile(formData: FormData) {
  "use server";
  const next = formData.get("public_profile") === "true";
  await patchProfile({ public_profile: next });
  revalidatePath("/settings");
}

export default async function SettingsPage() {
  const profile = await getProfile();

  return (
    <div className="container mx-auto max-w-lg px-4 py-10 sm:px-6">
      <header className="mb-6">
        <h1 className="text-3xl font-bold tracking-tight">Settings</h1>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Leaderboard visibility</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            When enabled, your username and portfolio return appear on the public leaderboard.
            Your holdings and cash balance are never shown.
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
              <span className={profile.public_profile ? "text-green-500" : "text-muted-foreground"}>
                {profile.public_profile ? "visible" : "hidden"}
              </span>
            </span>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
