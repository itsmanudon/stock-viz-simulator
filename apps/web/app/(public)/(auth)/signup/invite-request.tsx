"use client";

import { ArrowUpRight, Check, Send } from "lucide-react";
import Link from "next/link";
import { useActionState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { type InviteFormState, requestInviteAction } from "./invite-actions";

/**
 * The invite-only page, shaped as a paper ticket: the top half says why the
 * door is closed, the stub below the perforation is a short request that opens
 * the visitor's mail app, addressed to the owner.
 */
export function InviteRequest() {
  const [state, formAction, pending] = useActionState<InviteFormState, FormData>(
    requestInviteAction,
    { status: "idle" },
  );

  return (
    <div className="relative isolate" data-testid="signup-closed">
      <div aria-hidden className="brand-glow -top-10 -right-10 -z-10 h-56 w-72 opacity-50" />
      <div className="overflow-hidden rounded-2xl border border-border-muted bg-card text-card-foreground shadow-[0_30px_80px_-40px_rgb(0_0_0/0.6)]">
        <div className="px-6 pt-6 pb-7">
          <div className="flex items-start justify-between gap-4">
            <h1 className="text-3xl leading-[1.02] font-medium tracking-[-0.04em] text-balance">
              Pull up a chair at the desk
            </h1>
            <span className="mt-1 shrink-0 rotate-6 rounded-md border border-border-muted px-2 py-1 font-mono text-[10px] tracking-widest text-text-tertiary uppercase">
              Invite only
            </span>
          </div>
          <p className="mt-4 text-sm leading-relaxed text-text-secondary">
            StockViz is open to a small group while it is being tested, so new accounts are by
            invite. Tell me who you are and what you would try first, and I will send you one.
          </p>
        </div>

        {/* The perforation: two notches and a dashed tear line. */}
        <div aria-hidden className="relative h-0">
          <span className="absolute -top-3 -left-3 size-6 rounded-full border border-border-muted bg-background" />
          <span className="absolute -top-3 -right-3 size-6 rounded-full border border-border-muted bg-background" />
          <span className="absolute inset-x-5 top-0 border-t border-dashed border-border-muted" />
        </div>

        <div className="bg-surface-secondary/40 px-6 pt-7 pb-6">
          {state.status === "sent" ? (
            <output className="block space-y-4">
              <span className="flex size-10 items-center justify-center rounded-full border border-border-muted text-brand">
                <Check className="size-4" aria-hidden />
              </span>
              <p className="text-lg font-medium tracking-tight">Request received.</p>
              <p className="text-sm leading-relaxed text-text-secondary">
                Thanks. I read every one and will reply to the email you gave, usually within a day
                or two. Meanwhile the markets and docs are open.
              </p>
            </output>
          ) : (
            <form action={formAction} className="space-y-4">
              {/* Honeypot: hidden from people, tempting to bots. */}
              <div aria-hidden className="absolute -left-[9999px] h-0 w-0 overflow-hidden">
                <label htmlFor="invite-company">Company</label>
                <input id="invite-company" name="company" tabIndex={-1} autoComplete="off" />
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="invite-name">Name</Label>
                  <Input
                    id="invite-name"
                    name="name"
                    autoComplete="name"
                    required
                    maxLength={120}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="invite-email">Email</Label>
                  <Input
                    id="invite-email"
                    name="email"
                    type="email"
                    autoComplete="email"
                    required
                    maxLength={200}
                  />
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="invite-note">What would you try first?</Label>
                <textarea
                  id="invite-note"
                  name="note"
                  rows={3}
                  maxLength={1000}
                  placeholder="Backtest a momentum idea, replay a crash, paper-trade earnings week..."
                  className="w-full min-w-0 resize-none rounded-md border border-input bg-transparent px-3 py-2 text-base outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 md:text-sm dark:bg-input/30"
                />
              </div>
              {state.status === "error" && state.error ? (
                <p className="text-sm text-negative" role="alert">
                  {state.error}
                </p>
              ) : null}
              <Button type="submit" disabled={pending} className="h-11 w-full gap-2 rounded-full">
                <Send className="size-4" aria-hidden />
                {pending ? "Sending..." : "Request an invite"}
              </Button>
              <p className="text-center text-xs text-text-tertiary">
                Goes straight to the maker of StockViz. Used only to reply to you.
              </p>
            </form>
          )}
        </div>
      </div>

      <div className="mt-5 flex flex-wrap items-center justify-between gap-3 px-1 text-sm text-text-secondary">
        <span>
          Already invited?{" "}
          <Link href="/login" className="font-medium text-foreground underline underline-offset-4">
            Sign in
          </Link>
        </span>
        <Link href="/markets" className="inline-flex items-center gap-1 hover:text-foreground">
          Explore markets <ArrowUpRight className="size-3.5" aria-hidden />
        </Link>
      </div>
    </div>
  );
}
