"use client";

import { X } from "lucide-react";
import { Dialog } from "radix-ui";
import { useState } from "react";

import {
  ContextualTradeTicket,
  type ContextualTradeTicketProps,
} from "@/components/contextual-trade-ticket";

type Side = "buy" | "sell";

export function MobileTradeSheet(props: Omit<ContextualTradeTicketProps, "initialSide">) {
  const [open, setOpen] = useState(false);
  const [side, setSide] = useState<Side>("buy");

  function openFor(nextSide: Side) {
    setSide(nextSide);
    setOpen(true);
  }

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      {/* Pinned to the bottom of narrow screens, like Revolut's stock page:
          a white Buy pill and a dark Sell pill over a blurred band. The page
          adds matching bottom padding so nothing is hidden behind it. */}
      <div className="fixed inset-x-0 bottom-0 z-40 border-t border-border-muted bg-background/85 px-4 pt-2.5 pb-[max(0.75rem,env(safe-area-inset-bottom))] backdrop-blur-md xl:hidden">
        <p className="mb-2 text-center text-2xs text-text-tertiary">
          Paper trading · no real money
        </p>
        <div className="mx-auto grid max-w-md grid-cols-2 gap-2">
          <button
            type="button"
            onClick={() => openFor("buy")}
            className="h-12 rounded-full bg-primary text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={`Buy ${props.ticker}`}
          >
            Buy
          </button>
          <button
            type="button"
            onClick={() => openFor("sell")}
            className="h-12 rounded-full border border-border-muted bg-surface-secondary text-sm font-semibold transition-colors hover:bg-surface-hover focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={`Sell ${props.ticker}`}
          >
            Sell
          </button>
        </div>
      </div>

      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/60 backdrop-blur-[2px] data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 xl:hidden" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed inset-x-0 bottom-0 z-50 max-h-[92dvh] overflow-y-auto rounded-t-3xl border-t border-border-muted bg-surface-elevated px-5 pb-[max(1.5rem,env(safe-area-inset-bottom))] pt-4 shadow-2xl outline-none data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=closed]:slide-out-to-bottom data-[state=open]:slide-in-from-bottom sm:left-1/2 sm:max-w-md sm:-translate-x-1/2 sm:border-x xl:hidden"
        >
          <Dialog.Title className="sr-only">Paper trade {props.ticker}</Dialog.Title>
          <div className="mb-3 flex justify-end">
            <Dialog.Close asChild>
              <button
                type="button"
                aria-label="Close paper trade"
                className="inline-flex size-10 items-center justify-center rounded-sm text-muted-foreground transition-colors hover:bg-surface-hover hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
              >
                <X className="size-5" aria-hidden />
              </button>
            </Dialog.Close>
          </div>
          <ContextualTradeTicket
            key={`${props.ticker}-${side}-${open ? "open" : "closed"}`}
            {...props}
            initialSide={side}
          />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
