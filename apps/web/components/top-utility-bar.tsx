import { AccountMenu } from "@/components/account-menu";
import { AlertsBell } from "@/components/alerts-bell";
import { AppMobileNav } from "@/components/app-mobile-nav";
import { BookSwitcherSlot } from "@/components/book-switcher-slot";
import { GlobalTickerSearch } from "@/components/global-ticker-search";
import { DataDateChip } from "@/components/marketing/market-status";
import { RegimeBadges } from "@/components/regime-badge";
import { SoundToggle } from "@/components/sound/sound-toggle";

export function TopUtilityBar({ signedIn }: { signedIn: boolean }) {
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-border-muted bg-background/70 px-3 backdrop-blur-xl backdrop-saturate-150 lg:px-6">
      <AppMobileNav signedIn={signedIn} />
      <div className="min-w-0 max-w-xl flex-1">
        <GlobalTickerSearch />
      </div>
      <div className="ml-auto flex shrink-0 items-center gap-1">
        <span className="mr-1 hidden md:inline">
          <DataDateChip />
        </span>
        <SoundToggle className="mr-1" />
        <span className="mr-1 hidden sm:inline">
          <RegimeBadges />
        </span>
        {/* A5.2: the book switcher, signed in only. */}
        {signedIn ? <BookSwitcherSlot /> : null}
        <AlertsBell enabled={signedIn} />
        <AccountMenu />
      </div>
    </header>
  );
}
