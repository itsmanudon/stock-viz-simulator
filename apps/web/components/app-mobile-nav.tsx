"use client";

import { LineChart, Menu, X } from "lucide-react";
import Link from "next/link";
import { Dialog } from "radix-ui";
import { useState } from "react";

import { AppNavigation, SimulatedDataTag } from "@/components/app-navigation";
import { homeHref } from "@/lib/app-navigation";

export function AppMobileNav({ signedIn }: { signedIn: boolean }) {
  const [open, setOpen] = useState(false);

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button
          type="button"
          className="inline-flex size-10 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring lg:hidden"
          aria-label="Open navigation"
        >
          <Menu className="size-5" aria-hidden />
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/55 backdrop-blur-[2px] data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 lg:hidden" />
        <Dialog.Content className="fixed inset-y-0 left-0 z-50 flex w-[min(19rem,88vw)] flex-col border-r border-border-muted bg-surface-elevated outline-none data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=closed]:slide-out-to-left data-[state=open]:slide-in-from-left lg:hidden">
          <Dialog.Title className="sr-only">Product navigation</Dialog.Title>
          <Dialog.Description className="sr-only">
            Navigate StockViz research, trading, portfolio, and community tools.
          </Dialog.Description>

          <div className="flex h-14 items-center gap-2.5 border-b border-border-muted px-5">
            <Link
              href={homeHref(signedIn)}
              onClick={() => setOpen(false)}
              className="flex items-center gap-2.5 rounded-sm font-semibold tracking-tight focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span className="flex size-7 items-center justify-center rounded-md border border-brand/40 bg-brand/10 text-brand">
                <LineChart className="size-4" aria-hidden />
              </span>
              <span>StockViz</span>
            </Link>
            <SimulatedDataTag />
            <Dialog.Close asChild>
              <button
                type="button"
                className="ml-auto inline-flex size-10 items-center justify-center rounded-sm text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                aria-label="Close navigation"
              >
                <X className="size-5" aria-hidden />
              </button>
            </Dialog.Close>
          </div>

          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-3 pt-3 pb-6">
            <AppNavigation signedIn={signedIn} onNavigate={() => setOpen(false)} />
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
