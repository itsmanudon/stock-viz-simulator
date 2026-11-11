/**
 * A phone bezel showing one of several stacked app screens.
 *
 * Shared by the hero stage and the scroll story. Every screen stays laid out
 * (inactive ones are only transparent), so the hero can measure the portfolio
 * card at any time. Blocks inside a screen never shrink: a squashed card used
 * to overlap the balance below it. Callers wrap this in the dark theme and
 * hide it from assistive technology; it is a picture of the app.
 */

import { BriefcaseBusiness, ChartCandlestick, House, Newspaper, UserRound } from "lucide-react";

import type { PhoneScreen } from "@/components/marketing/hero-phone-screens";
import { cn } from "@/lib/utils";

const TABS = [
  { label: "Home", icon: House },
  { label: "Markets", icon: ChartCandlestick },
  { label: "News", icon: Newspaper },
  { label: "Portfolio", icon: BriefcaseBusiness },
  { label: "Account", icon: UserRound },
] as const;

export function PhoneFrame({
  screens,
  active,
  className,
}: {
  screens: PhoneScreen[];
  active: number;
  className?: string;
}) {
  const current = screens[active] ?? screens[0];
  return (
    <div
      className={cn(
        "h-[37rem] rounded-[2.9rem] bg-linear-to-b from-[#2a3142] via-[#0d1119] to-[#20283a] p-[7px] shadow-[0_30px_80px_-20px_rgb(0_0_0/0.7),inset_0_0_0_1px_rgb(255_255_255/0.06)]",
        className,
      )}
    >
      <div className="flex h-full flex-col overflow-hidden rounded-[2.5rem] bg-background">
        <div className="relative flex items-center justify-between px-6 pt-3.5 pb-1.5 text-xs font-semibold">
          <span className="font-mono">9:41</span>
          <span className="absolute top-2.5 left-1/2 h-6 w-24 -translate-x-1/2 rounded-full bg-black" />
          <span className="h-2.5 w-5 rounded-[3px] border border-foreground p-px">
            <span className="block h-full w-3/4 rounded-[1px] bg-foreground" />
          </span>
        </div>
        <div className="relative min-h-0 flex-1">
          {screens.map((screen, index) => (
            <div
              key={screen.key}
              data-active={index === active}
              className="absolute inset-0 flex flex-col gap-3.5 overflow-hidden px-3.5 pt-1.5 transition-opacity duration-500 data-[active=false]:pointer-events-none data-[active=false]:opacity-0 [&>*]:shrink-0"
            >
              {screen.node}
            </div>
          ))}
        </div>
        <div className="flex justify-around border-t border-border-muted px-2 pt-2 pb-5">
          {TABS.map(({ label, icon: Icon }) => (
            <span
              key={label}
              className={cn(
                "grid justify-items-center gap-0.5 text-[0.6rem]",
                current?.tab === label ? "text-foreground" : "text-text-tertiary",
              )}
            >
              <Icon className="size-[1.1rem]" />
              {label}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
