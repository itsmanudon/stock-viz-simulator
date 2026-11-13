"use client";

import Link from "next/link";
import { useActionState } from "react";

import {
  type ScreenActionState,
  deleteScreenAction,
  saveScreenAction,
} from "@/app/(product)/screener/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { SavedScreen } from "@/lib/api/screens";

/**
 * Saved screens on /screener (Phase 6.2): the signed-in user's named screens
 * as links, and a form to save the one on show. A screen is its URL query, so
 * opening one is following its link.
 */
export function SavedScreens({ screens, query }: { screens: SavedScreen[]; query: string }) {
  const [state, save, saving] = useActionState<ScreenActionState, FormData>(saveScreenAction, {});
  return (
    <section
      aria-labelledby="saved-screens"
      className="space-y-2 border-t border-border-muted pt-4"
    >
      <h2
        id="saved-screens"
        className="text-2xs font-semibold tracking-[0.12em] text-text-tertiary uppercase"
      >
        Saved screens
      </h2>
      {screens.length ? (
        <ul className="space-y-1">
          {screens.map((screen) => (
            <li key={screen.id} className="flex items-center justify-between gap-2 text-sm">
              <Link
                href={screen.query ? `/screener?${screen.query}` : "/screener"}
                className="truncate hover:underline"
              >
                {screen.name}
              </Link>
              <form action={deleteScreenAction}>
                <input type="hidden" name="id" value={screen.id} />
                <button
                  type="submit"
                  className="text-2xs text-text-tertiary hover:text-negative"
                  aria-label={`Delete saved screen ${screen.name}`}
                >
                  Delete
                </button>
              </form>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-text-tertiary">None yet.</p>
      )}
      <form action={save} className="flex gap-2">
        <input type="hidden" name="query" value={query} />
        <Input name="name" aria-label="Name for this screen" placeholder="Name this screen" />
        <Button type="submit" variant="outline" disabled={saving}>
          Save
        </Button>
      </form>
      {state.saved ? <output className="block text-xs">Saved “{state.saved}”.</output> : null}
      {state.error ? (
        <p role="alert" className="text-xs text-negative">
          {state.error}
        </p>
      ) : null}
    </section>
  );
}
