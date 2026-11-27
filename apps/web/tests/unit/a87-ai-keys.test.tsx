/** A8.7 (M11.2 BYOK): Settings → AI Keys never shows a key. */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/(product)/(authed)/settings/ai-key-actions", () => ({
  saveAiKeyAction: vi.fn(async () => ({})),
  deleteAiKeyAction: vi.fn(async () => ({})),
}));

import { AiKeysPanel } from "@/components/ai-keys-panel";
import { aiChoices } from "@/lib/ai-choices";
import type { AiKeys } from "@/lib/api/ai";

const base: AiKeys = {
  available: true,
  keys: [],
  providers: ["openai_compatible", "anthropic"],
  held: {},
  note: "Keys are encrypted on the server and never shown again.",
};

describe("AI keys panel", () => {
  it("offers a write-only key field per provider; Claude needs no endpoint", () => {
    render(<AiKeysPanel data={base} />);
    const openai = within(screen.getByTestId("ai-key-openai_compatible"));
    expect(openai.getByLabelText("Key")).toHaveAttribute("type", "password");
    expect(openai.getByLabelText("Endpoint Base URL")).toBeInTheDocument();
    const claude = within(screen.getByTestId("ai-key-anthropic"));
    expect(claude.queryByLabelText("Endpoint Base URL")).toBeNull();
    expect(claude.getByLabelText("Model")).toHaveValue("claude-opus-5-5");
    expect(claude.getByLabelText("Key")).toHaveValue("");
  });

  it("shows a saved key by its last four characters only", () => {
    render(
      <AiKeysPanel
        data={{
          ...base,
          keys: [
            {
              provider: "anthropic",
              model: "claude-sonnet-5-5",
              base_url: null,
              key_last4: "ABCD",
              updated_at: "2026-11-27T10:00:00",
            },
          ],
        }}
      />,
    );
    const claude = within(screen.getByTestId("ai-key-anthropic"));
    expect(claude.getByTestId("ai-key-saved")).toHaveTextContent("Key Ending ABCD");
    expect(claude.getByLabelText("Replace Key")).toHaveValue("");
    expect(claude.getByLabelText("Model")).toHaveValue("claude-sonnet-5-5");
  });

  it("says when the server cannot store keys", () => {
    render(<AiKeysPanel data={{ ...base, available: false }} />);
    expect(screen.getByTestId("ai-keys-off")).toBeInTheDocument();
    expect(screen.queryByTestId("ai-key-form")).toBeNull();
  });

  it("lists the server model and each saved key as choices", () => {
    const status = {
      configured: true,
      provider: "ollama",
      model: "gemma4:e4b",
      reason: null,
      keys_available: true,
    };
    const keys: AiKeys = {
      ...base,
      keys: [
        {
          provider: "anthropic",
          model: "claude-opus-5-5",
          base_url: null,
          key_last4: "ABCD",
          updated_at: "2026-11-27T10:00:00",
        },
      ],
    };
    expect(aiChoices(status, keys)).toEqual([
      { value: "server", label: "Server: ollama gemma4:e4b" },
      { value: "anthropic", label: "Your Claude key: claude-opus-5-5" },
    ]);
    expect(aiChoices(null, null)).toEqual([]);
  });
});
