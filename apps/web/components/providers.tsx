"use client";

import { ThemeProvider } from "next-themes";

import { InterfacePreferences } from "@/components/interface-preferences";

/**
 * Dark only, for now (owner's decision, 12 Nov 2026): the Aurora pages were
 * designed and checked dark-first, and the light theme needs its own design
 * pass. `forcedTheme` overrides a "light" choice already saved in
 * localStorage. The light tokens stay in globals.css, so restoring the theme
 * is this prop plus the toggles that were removed with it.
 */
export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="dark" forcedTheme="dark" enableSystem={false}>
      <InterfacePreferences>{children}</InterfacePreferences>
    </ThemeProvider>
  );
}
