import { ShieldCheck, TrendingUp, Wallet } from "lucide-react";

/**
 * Shared frame for sign-in and sign-up.
 *
 * Both routes previously repeated the same centering wrapper. Beyond
 * deduplicating that, the panel gives the form some context: an empty card
 * floating on an empty page gives a first-time visitor no reason to fill it in.
 */

const POINTS = [
  {
    icon: Wallet,
    title: "$100,000 in simulated cash",
    body: "Every new account starts with the same paper balance.",
  },
  {
    icon: TrendingUp,
    title: "The full research loop",
    body: "Screener, comparison, signals, and backtesting on end-of-day data.",
  },
  {
    icon: ShieldCheck,
    title: "Nothing real at stake",
    body: "Orders are simulated against stored daily closes, never sent to an exchange.",
  },
];

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6 lg:py-14">
      <div className="grid items-center gap-10 lg:grid-cols-2">
        <div className="flex justify-center lg:justify-end">
          <div className="w-full max-w-md">{children}</div>
        </div>

        {/* Secondary on mobile — the form is what the visitor came for, so the
            pitch drops below the fold rather than pushing the fields down. */}
        <aside className="order-first max-w-md lg:order-last">
          <h2 className="text-2xl font-bold tracking-tight text-balance sm:text-3xl">
            A trading workspace where mistakes are free
          </h2>
          <ul className="mt-8 space-y-6">
            {POINTS.map((point) => {
              const Icon = point.icon;
              return (
                <li key={point.title} className="flex gap-3.5">
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-md border border-border-muted bg-surface-secondary text-brand">
                    <Icon className="size-4" aria-hidden />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-sm font-medium">{point.title}</span>
                    <span className="mt-1 block text-sm leading-6 text-text-secondary">
                      {point.body}
                    </span>
                  </span>
                </li>
              );
            })}
          </ul>
        </aside>
      </div>
    </div>
  );
}
