import { LineChart } from "lucide-react";
import Link from "next/link";

import { AccountMenu } from "@/components/account-menu";

const NAV_LINKS = [
  { href: "/markets", label: "Markets" },
  { href: "/trade", label: "Trade" },
  { href: "/compare", label: "Compare" },
  { href: "/news", label: "News" },
];

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b bg-background/80 backdrop-blur">
      <div className="container mx-auto flex h-16 items-center justify-between px-6">
        <Link href="/" className="flex items-center gap-2 font-semibold">
          <LineChart className="h-5 w-5 text-primary" />
          <span>StockViz</span>
        </Link>

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
          <AccountMenu />
        </div>
      </div>
    </header>
  );
}
