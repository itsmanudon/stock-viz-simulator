import { AccountMenu } from "@/components/account-menu";
import { AlertsBell } from "@/components/alerts-bell";
import { AppMobileNav } from "@/components/app-mobile-nav";
import { GlobalTickerSearch } from "@/components/global-ticker-search";
import { ThemeToggle } from "@/components/theme-toggle";

export function TopUtilityBar({ signedIn }: { signedIn: boolean }) {
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-border-muted bg-background/95 px-3 backdrop-blur lg:px-6">
      <AppMobileNav signedIn={signedIn} />
      <div className="min-w-0 max-w-xl flex-1">
        <GlobalTickerSearch />
      </div>
      <div className="ml-auto flex shrink-0 items-center gap-1">
        <AlertsBell enabled={signedIn} />
        <ThemeToggle />
        <AccountMenu />
      </div>
    </header>
  );
}
