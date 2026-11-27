/** A8.7 (M11.2 BYOK): Settings → AI Keys never shows a key. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/(product)/(authed)/settings/ai-key-actions", () => ({
  saveAiKeyAction: vi.fn(async () => ({})),
  deleteAiKeyAction: vi.fn(async () => ({})),
}));

import { AiKeysPanel } from "@/components/ai-keys-panel";
import type { AiKeys } from "@/lib/api/ai";

const base: AiKeys = {
  available: true,
  keys: [],
  providers: ["openai_compatible"],
  held: { anthropic: "Claude keys need the official anthropic SDK, which is not added yet." },
  note: "Keys are encrypted on the server and never shown again.",
};

describe("AI keys panel", () => {
  it("offers a write-only key field and says why Claude is held", () => {
    render(<AiKeysPanel data={base} />);
    const field = screen.getByLabelText("Key");
    expect(field).toHaveAttribute("type", "password");
    expect(field).toHaveValue("");
    expect(screen.getByTestId("ai-key-held")).toHaveTextContent("Claude: Claude keys need");
    expect(screen.queryByTestId("ai-key-saved")).toBeNull();
  });

  it("shows a saved key by its last four characters only", () => {
    render(
      <AiKeysPanel
        data={{
          ...base,
          keys: [
            {
              provider: "openai_compatible",
              model: "gpt-test",
              base_url: "https://api.example.com/v1",
              key_last4: "WXYZ",
              updated_at: "2026-11-27T10:00:00",
            },
          ],
        }}
      />,
    );
    expect(screen.getByTestId("ai-key-saved")).toHaveTextContent("Key Ending WXYZ");
    expect(screen.getByLabelText("Replace Key")).toHaveValue("");
    expect(screen.getByLabelText("Model")).toHaveValue("gpt-test");
  });

  it("says when the server cannot store keys", () => {
    render(<AiKeysPanel data={{ ...base, available: false }} />);
    expect(screen.getByTestId("ai-keys-off")).toBeInTheDocument();
    expect(screen.queryByTestId("ai-key-form")).toBeNull();
  });
});
