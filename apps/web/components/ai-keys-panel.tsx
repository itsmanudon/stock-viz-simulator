"use client";

/**
 * A8.7 (M11.2 BYOK): Settings → AI Keys. One form per provider: an
 * OpenAI-compatible endpoint (base URL, model, key) and, since A8.7b, Claude
 * (model, key; Anthropic's own endpoint). A saved key shows only its model,
 * endpoint and last four characters; the key field is write-only and empty
 * on every render.
 */

import { useActionState, useId, useState, useTransition } from "react";

import {
  type AiKeyState,
  deleteAiKeyAction,
  saveAiKeyAction,
} from "@/app/(product)/(authed)/settings/ai-key-actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatUtcDateTime } from "@/lib/api-time";
import type { AiKey, AiKeys } from "@/lib/api/ai";

const PROVIDERS = [
  { id: "openai_compatible", title: "OpenAI-Compatible Endpoint", endpoint: true, model: "" },
  { id: "anthropic", title: "Claude (Anthropic)", endpoint: false, model: "claude-opus-5-5" },
] as const;

function KeyForm({
  provider,
  saved,
}: {
  provider: (typeof PROVIDERS)[number];
  saved: AiKey | undefined;
}) {
  const id = useId();
  const [state, save, saving] = useActionState<AiKeyState, FormData>(saveAiKeyAction, {});
  const [removed, setRemoved] = useState<AiKeyState>({});
  const [removing, start] = useTransition();
  return (
    <section
      aria-labelledby={`${id}-title`}
      className="space-y-3 rounded-lg border border-border p-3"
      data-testid={`ai-key-${provider.id}`}
    >
      <h3 id={`${id}-title`} className="text-sm font-medium">
        {provider.title}
      </h3>
      {saved ? (
        <div className="text-xs text-text-secondary" data-testid="ai-key-saved">
          {saved.model}
          {saved.base_url ? ` · ${saved.base_url}` : ""} · Key Ending {saved.key_last4} · Saved{" "}
          {formatUtcDateTime(saved.updated_at)}
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="ml-2"
            disabled={removing}
            onClick={() => start(async () => setRemoved(await deleteAiKeyAction(provider.id)))}
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
        <input type="hidden" name="provider" value={provider.id} />
        {provider.endpoint ? (
          <div className="space-y-1 sm:col-span-2">
            <Label htmlFor={`${id}-url`} className="text-xs">
              Endpoint Base URL
            </Label>
            <Input
              id={`${id}-url`}
              name="base_url"
              defaultValue={saved?.base_url ?? ""}
              placeholder="https://api.openai.com/v1"
            />
          </div>
        ) : null}
        <div className="space-y-1">
          <Label htmlFor={`${id}-model`} className="text-xs">
            Model
          </Label>
          <Input id={`${id}-model`} name="model" defaultValue={saved?.model ?? provider.model} />
        </div>
        <div className="space-y-1">
          <Label htmlFor={`${id}-key`} className="text-xs">
            {saved ? "Replace Key" : "Key"}
          </Label>
          <Input
            id={`${id}-key`}
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
    </section>
  );
}

export function AiKeysPanel({ data }: { data: AiKeys }) {
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
      {PROVIDERS.filter((p) => data.providers.includes(p.id)).map((p) => (
        <KeyForm key={p.id} provider={p} saved={data.keys.find((k) => k.provider === p.id)} />
      ))}
      {Object.entries(data.held).map(([provider, why]) => (
        <p key={provider} className="text-xs text-text-tertiary" data-testid="ai-key-held">
          {provider}: {why}
        </p>
      ))}
    </div>
  );
}
