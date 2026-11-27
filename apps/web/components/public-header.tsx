import Link from "next/link";

import { StockVizWordmark } from "@/components/brand/stockviz-mark";

import { auth } from "@/auth";
import { AccountMenu } from "@/components/account-menu";
import { FloatingHeader } from "@/components/marketing/floating-header";
import { MobileNav } from "@/components/mobile-nav";
import { SoundToggle } from "@/components/sound/sound-toggle";
import { Button } from "@/components/ui/button";
import { signupMode } from "@/lib/signup-gate";

// The three product pages, as SolCard's header lists its products, then the docs, centred
// in the bar from `lg` (owner, 27 Nov 2026); on smaller screens they follow the logo. Markets
// stays one click away from the hero's "Explore markets" and the footer.
const PUBLIC_LINKS = [
  { href: "/product/paper-trading", label: "Paper trading" },
  { href: "/product/research", label: "Research" },
  { href: "/product/replay", label: "Replay" },
  { href: "/docs", label: "Docs" },
];

export async function PublicHeader() {
  const session = await auth();
  const signedIn = Boolean(session?.user?.id);
  // The signup switch (SIGNUP_MODE): while closed, signed-out visitors get "Sign in".
  const closed = signupMode() === "closed";

  return (
    <FloatingHeader>
      <MobileNav links={PUBLIC_LINKS} />
      <Link
        href="/"
        className="flex items-center gap-2.5 rounded-sm font-semibold tracking-tight focus-visible:ring-2 focus-visible:ring-ring"
      >
        <StockVizWordmark />
      </Link>

      <nav
        aria-label="Public"
        className="ml-8 hidden items-center gap-6 md:flex lg:absolute lg:left-1/2 lg:ml-0 lg:-translate-x-1/2"
      >
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
        <SoundToggle />
        <Button asChild size="sm" className="hidden rounded-full sm:inline-flex">
          <Link href={signedIn ? "/dashboard" : closed ? "/login" : "/signup"}>
            {signedIn ? "Open workspace" : closed ? "Sign in" : "Create account"}
          </Link>
        </Button>
        <AccountMenu />
      </div>
    </FloatingHeader>
  );
}
