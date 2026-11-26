import { PrismCursor } from "@/components/prism/prism-cursor";
import { SpotlightTracker } from "@/components/prism/spotlight-tracker";
import { PublicHeader } from "@/components/public-header";
import { SiteFooter } from "@/components/site-footer";

export default function PublicLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <PrismCursor />
      <SpotlightTracker />
      <PublicHeader />
      <main id="main" tabIndex={-1} className="flex-1">
        {children}
      </main>
      <SiteFooter />
    </div>
  );
}
