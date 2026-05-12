import { LineChart } from "lucide-react";
import Link from "next/link";

import { AccountMenu } from "@/components/account-menu";
import { MobileNav } from "@/components/mobile-nav";
import { ThemeToggle } from "@/components/theme-toggle";

const NAV_LINKS = [
  { href: "/markets", label: "Markets" },
  { href: "/compare", label: "Compare" },
  { href: "/recommendations", label: "Recommendations" },
  { href: "/news", label: "News" },
  { href: "/watchlist", label: "Watchlist" },
  { href: "/portfolio", label: "Portfolio" },
  { href: "/trade", label: "Trade" },
];

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b bg-background/80 backdrop-blur">
      <div className="container mx-auto flex h-16 items-center justify-between gap-2 px-4 sm:px-6">
        <div className="flex items-center gap-2">
          <MobileNav links={NAV_LINKS} />
          <Link href="/" className="flex items-center gap-2 font-semibold">
            <LineChart className="h-5 w-5 text-primary" />
            <span>StockViz</span>
          </Link>
        </div>

        <nav className="hidden items-center gap-6 md:flex">
          {NAV_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="text-sm text-muted-foreground transition hover:text-foreground"
            >
              {link.label}
            </Link>
          ))}
        </nav>

        <div className="flex items-center gap-3">
          <ThemeToggle />
          <AccountMenu />
        </div>
      </div>
    </header>
  );
}
