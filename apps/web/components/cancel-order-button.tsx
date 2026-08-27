"use client";

import { useFormStatus } from "react-dom";

import { Button } from "@/components/ui/button";

export function CancelOrderButton() {
  const { pending } = useFormStatus();
  return (
    <Button
      type="submit"
      variant="outline"
      size="sm"
      className="rounded-sm"
      disabled={pending}
      aria-busy={pending}
    >
      {pending ? "Cancelling…" : "Cancel order"}
    </Button>
  );
}
