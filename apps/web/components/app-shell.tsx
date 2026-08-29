import { AppSidebar } from "@/components/app-sidebar";
import { TopUtilityBar } from "@/components/top-utility-bar";

export function AppShell({
  children,
  signedIn,
}: {
  children: React.ReactNode;
  signedIn: boolean;
}) {
  return (
    <div className="min-h-screen bg-background lg:grid lg:grid-cols-[15rem_minmax(0,1fr)]">
      <AppSidebar signedIn={signedIn} />
      <div className="min-w-0">
        <TopUtilityBar signedIn={signedIn} />
        <main id="main" tabIndex={-1} className="workspace-main min-w-0">
          {children}
        </main>
      </div>
    </div>
  );
}
