import type { Metadata } from "next";
import { IBM_Plex_Mono, Inter } from "next/font/google";

import { Providers } from "@/components/providers";
import "./globals.css";

/**
 * Inter carries all non-numeric interface, heading, and marketing copy with a
 * familiar, highly legible system. IBM Plex Mono handles every ticker, price,
 * quantity, table value, and delta — it has true tabular figures and a slashed
 * zero, which the previous system-mono stack only had on some platforms.
 *
 * Both are self-hosted by next/font, so there is no runtime request to Google.
 */
const display = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-display",
});

const mono = IBM_Plex_Mono({
  weight: ["400", "500", "600", "700"],
  subsets: ["latin"],
  display: "swap",
  variable: "--font-numeric",
});

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
