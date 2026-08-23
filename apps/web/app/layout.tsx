import { Providers } from "@/components/providers";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "StockViz | Market Visualization Platform",
  description:
    "End-of-day market analytics, strategy backtesting, and paper trading for equities and options.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen bg-background text-foreground antialiased">
        <Providers>
          {/* Visible only on keyboard focus — lets a keyboard or screen-reader
              user jump past the header nav on every page. */}
          <a
            href="#main"
            className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-background focus:px-4 focus:py-2 focus:ring-2 focus:ring-ring"
          >
            Skip to main content
          </a>
          <div className="flex min-h-screen flex-col">
            <SiteHeader />
            <main id="main" tabIndex={-1} className="flex-1">
              {children}
            </main>
            <SiteFooter />
          </div>
        </Providers>
      </body>
    </html>
  );
}
