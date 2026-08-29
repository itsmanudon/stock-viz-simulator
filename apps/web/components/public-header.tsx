import { LineChart } from "lucide-react";
import Link from "next/link";

import { auth } from "@/auth";
import { AccountMenu } from "@/components/account-menu";
import { FloatingHeader } from "@/components/marketing/floating-header";
import { MarketStatus } from "@/components/marketing/market-status";
import { MobileNav } from "@/components/mobile-nav";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";

const PUBLIC_LINKS = [
  { href: "/markets", label: "Markets" },
  { href: "/compare", label: "Research" },
  { href: "/backtest", label: "Backtest" },
];

export async function PublicHeader() {
  const session = await auth();
  const signedIn = Boolean(session?.user?.id);

  return (
    <FloatingHeader>
      <MobileNav links={PUBLIC_LINKS} />
      <Link
        href="/"
        className="flex items-center gap-2.5 rounded-sm font-semibold tracking-tight focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="flex size-7 items-center justify-center rounded-md border border-brand/40 bg-brand/10 text-brand">
          <LineChart className="size-4" aria-hidden />
        </span>
        <span>StockViz</span>
      </Link>

      <nav aria-label="Public" className="ml-8 hidden items-center gap-6 md:flex">
        {PUBLIC_LINKS.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            // The underline grows from the centre on hover: `after` is a
            // full-width rule kept at scale-x-0 until the link is hovered.
            className="relative text-sm text-text-secondary transition-colors after:absolute after:-bottom-1 after:left-0 after:h-px after:w-full after:origin-center after:scale-x-0 after:bg-brand after:transition-transform after:duration-200 hover:text-foreground hover:after:scale-x-100"
          >
            {link.label}
          </Link>
        ))}
      </nav>

      <div className="ml-auto flex items-center gap-1 sm:gap-2">
        <MarketStatus />
        <Button asChild size="sm" className="hidden rounded-full sm:inline-flex">
          <Link href={signedIn ? "/dashboard" : "/signup"}>
            {signedIn ? "Open workspace" : "Create account"}
          </Link>
        </Button>
        <ThemeToggle />
        <AccountMenu />
      </div>
    </FloatingHeader>
  );
}
