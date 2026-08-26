import { Providers } from "@/components/providers";
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
          <a
            href="#main"
            className="skip-link sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:rounded-sm focus:bg-background focus:px-4 focus:py-2 focus:ring-2 focus:ring-ring"
          >
            Skip to main content
          </a>
          {children}
        </Providers>
      </body>
    </html>
  );
}
