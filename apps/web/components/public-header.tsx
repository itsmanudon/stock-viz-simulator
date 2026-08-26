import { LineChart } from "lucide-react";
import Link from "next/link";

import { auth } from "@/auth";
import { AccountMenu } from "@/components/account-menu";
import { MobileNav } from "@/components/mobile-nav";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";

const PUBLIC_LINKS = [
  { href: "/markets", label: "Markets" },
  { href: "/screener", label: "Research" },
  { href: "/backtest", label: "Backtest" },
];

export async function PublicHeader() {
  const session = await auth();
  const signedIn = Boolean(session?.user?.id);

  return (
    <header className="sticky top-0 z-40 border-b border-border-muted bg-background/90 backdrop-blur">
      <div className="mx-auto flex h-14 w-full max-w-7xl items-center gap-3 px-4 sm:px-6">
        <MobileNav links={PUBLIC_LINKS} />
        <Link
          href="/"
          className="flex items-center gap-2.5 rounded-sm font-semibold tracking-tight focus-visible:ring-2 focus-visible:ring-ring"
        >
          <span className="flex size-7 items-center justify-center rounded-sm border border-brand/40 bg-brand/10 text-brand">
            <LineChart className="size-4" aria-hidden />
          </span>
          <span>StockViz</span>
        </Link>

        <nav aria-label="Public" className="ml-8 hidden items-center gap-6 md:flex">
          {PUBLIC_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="text-sm text-text-secondary transition-colors hover:text-foreground"
            >
              {link.label}
            </Link>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-1 sm:gap-2">
          <Button asChild size="sm" className="hidden rounded-sm sm:inline-flex">
            <Link href={signedIn ? "/dashboard" : "/signup"}>
              {signedIn ? "Open workspace" : "Create account"}
            </Link>
          </Button>
          <ThemeToggle />
          <AccountMenu />
        </div>
      </div>
    </header>
  );
}
