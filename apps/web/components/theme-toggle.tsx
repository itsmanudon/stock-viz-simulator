"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";

import { Button } from "@/components/ui/button";

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
      aria-label="Toggle color theme"
      className="rounded-sm"
    >
      <Sun className="h-4 w-4 scale-100 transition-all dark:scale-0" />
      <Moon className="absolute h-4 w-4 scale-0 transition-all dark:scale-100" />
    </Button>
  );
}
