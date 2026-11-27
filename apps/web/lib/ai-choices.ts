/**
 * A8.7: which models a signed-in user can run the copilot and extraction on:
 * the server's (A8.3) and each saved key (OpenAI-compatible; Claude since
 * A8.7b). Pure, client-safe.
 */

import type { AiKeys, AiProviderChoice, AiStatus } from "@/lib/api/ai";

export type AiChoice = { value: AiProviderChoice; label: string };

const KEY_LABEL: Record<string, string> = {
  openai_compatible: "Your key",
  anthropic: "Your Claude key",
};

export function aiChoices(status: AiStatus | null, keys: AiKeys | null): AiChoice[] {
  const out: AiChoice[] = [];
  if (status?.configured) {
    out.push({ value: "server", label: `Server: ${status.provider} ${status.model}` });
  }
  for (const provider of ["openai_compatible", "anthropic"] as const) {
    const key = keys?.keys.find((k) => k.provider === provider);
    if (key) out.push({ value: provider, label: `${KEY_LABEL[provider]}: ${key.model}` });
  }
  return out;
}
