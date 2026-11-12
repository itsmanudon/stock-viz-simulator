import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { Providers } from "@/components/providers";
import "./globals.css";

/**
 * Geist carries all interface, heading, and marketing copy, and every ticker
 * symbol (the `ticker` utility in globals.css). Product titles are weight 600
 * with tight tracking; marketing headlines stay at 500. Geist Mono handles
 * prices, quantities, table values and deltas: it has tabular figures and its
 * own ₹, and globals.css turns on the slashed zero.
 *
 * Both are self-hosted by next/font, so there is no runtime request to Google.
 */
const display = Geist({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-display",
});

const mono = Geist_Mono({
  weight: ["400", "500", "600", "700"],
  subsets: ["latin", "latin-ext"],
  display: "swap",
  variable: "--font-numeric",
});

export const metadata: Metadata = {
  // Each page names itself (UI audit A1); the home page keeps the full name.
  title: {
    default: "StockViz | Market Visualization Platform",
    template: "%s | StockViz",
  },
  description:
    "End-of-day market analytics, strategy backtesting, and paper trading for equities and options.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning className={`${display.variable} ${mono.variable}`}>
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
