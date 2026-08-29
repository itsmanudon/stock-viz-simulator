"use client";

import { ThemeProvider } from "next-themes";

import { InterfacePreferences } from "@/components/interface-preferences";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="dark" enableSystem={false}>
      <InterfacePreferences>{children}</InterfacePreferences>
    </ThemeProvider>
  );
}
