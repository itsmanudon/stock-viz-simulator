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
      {/* A9.6: the chrome stays off printed pages (the tearsheet). */}
      <div className="contents" data-app-chrome>
        <AppSidebar signedIn={signedIn} />
      </div>
      <div className="relative min-w-0">
        <div className="contents" data-app-chrome>
          <TopUtilityBar signedIn={signedIn} />
        </div>
        <main id="main" tabIndex={-1} className="workspace-main min-w-0">
          {children}
        </main>
      </div>
    </div>
  );
}
