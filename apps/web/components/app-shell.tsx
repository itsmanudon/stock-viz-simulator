import { AppSidebar } from "@/components/app-sidebar";
import { SpotlightTracker } from "@/components/prism/spotlight-tracker";
import { TopUtilityBar } from "@/components/top-utility-bar";

export function AppShell({
  children,
  signedIn,
}: {
  children: React.ReactNode;
  signedIn: boolean;
}) {
  return (
    <div className="relative min-h-screen bg-background lg:grid lg:grid-cols-[15rem_minmax(0,1fr)]">
      {/* PRISM: a faint light pinned behind the sidebar and header only. */}
      <div aria-hidden className="prism-ambient" />
      <SpotlightTracker />
      <AppSidebar signedIn={signedIn} />
      <div className="relative min-w-0">
        <TopUtilityBar signedIn={signedIn} />
        <main id="main" tabIndex={-1} className="workspace-main min-w-0">
          {children}
        </main>
      </div>
    </div>
  );
}
