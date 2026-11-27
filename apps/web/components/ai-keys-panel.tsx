"use client";

/**
 * A8.7 (M11.2 BYOK): Settings → AI Keys. A saved key shows only its model,
 * endpoint and last four characters; the key field is write-only and empty
 * on every render. Claude keys are listed as held (the API says why).
 */

import { useActionState, useState, useTransition } from "react";

import {
  type AiKeyState,
  deleteAiKeyAction,
  saveAiKeyAction,
} from "@/app/(product)/(authed)/settings/ai-key-actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatUtcDateTime } from "@/lib/api-time";
import type { AiKeys } from "@/lib/api/ai";

export function AiKeysPanel({ data }: { data: AiKeys }) {
  const [state, save, saving] = useActionState<AiKeyState, FormData>(saveAiKeyAction, {});
  const [removed, setRemoved] = useState<AiKeyState>({});
  const [removing, start] = useTransition();
  const saved = data.keys.find((k) => k.provider === "openai_compatible");
  if (!data.available) {
    return (
      <p className="text-sm text-text-secondary" data-testid="ai-keys-off">
        Saved keys are off on this server: it has no encryption key set.
      </p>
    );
  }
  return (
    <div className="space-y-4" data-testid="ai-keys">
      <p className="text-xs text-text-tertiary">{data.note}</p>
      {saved ? (
        <div className="rounded-lg border border-border p-3 text-sm" data-testid="ai-key-saved">
          <p className="font-medium">OpenAI-Compatible Endpoint</p>
          <p className="text-xs text-text-secondary">
            {saved.model} · {saved.base_url} · Key Ending {saved.key_last4} · Saved{" "}
            {formatUtcDateTime(saved.updated_at)}
          </p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="mt-2"
            disabled={removing}
            onClick={() =>
              start(async () => setRemoved(await deleteAiKeyAction("openai_compatible")))
            }
          >
            Remove Key
          </Button>
        </div>
      ) : null}
      {removed.error ? (
        <p role="alert" className="text-xs text-negative">
          {removed.error}
        </p>
      ) : null}
      <form action={save} className="grid gap-3 sm:grid-cols-2" data-testid="ai-key-form">
        <input type="hidden" name="provider" value="openai_compatible" />
        <div className="space-y-1 sm:col-span-2">
          <Label htmlFor="ai-key-base-url" className="text-xs">
            Endpoint Base URL
          </Label>
          <Input
            id="ai-key-base-url"
            name="base_url"
            defaultValue={saved?.base_url ?? ""}
            placeholder="https://api.openai.com/v1"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="ai-key-model" className="text-xs">
            Model
          </Label>
          <Input id="ai-key-model" name="model" defaultValue={saved?.model ?? ""} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="ai-key-secret" className="text-xs">
            {saved ? "Replace Key" : "Key"}
          </Label>
          <Input
            id="ai-key-secret"
            name="api_key"
            type="password"
            autoComplete="off"
            defaultValue=""
          />
        </div>
        <div className="sm:col-span-2">
          <Button type="submit" size="sm" disabled={saving}>
            {saving ? "Saving…" : "Save Key"}
          </Button>
        </div>
      </form>
      {state.error ? (
        <p role="alert" className="text-xs text-negative">
          {state.error}
        </p>
      ) : state.ok ? (
        <output className="block text-xs text-text-secondary">{state.ok}</output>
      ) : null}
      {Object.entries(data.held).map(([provider, why]) => (
        <p key={provider} className="text-xs text-text-tertiary" data-testid="ai-key-held">
          {provider === "anthropic" ? "Claude" : provider}: {why}
        </p>
      ))}
    </div>
  );
}
