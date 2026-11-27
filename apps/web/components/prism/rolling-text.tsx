/**
 * Text whose digits roll in like an odometer when the value changes.
 *
 * Each digit is keyed by its place and value, so a changed digit mounts
 * fresh and plays `.digit-roll` (globals.css); unchanged ones stay still.
 * The text itself is the real value, so it reads and copies normally. Under
 * reduced motion the stylesheet drops the animation.
 */

import { cn } from "@/lib/utils";

export function RollingText({ value, className }: { value: string; className?: string }) {
  const chars = [...value];
  return (
    <span className={cn("whitespace-pre tabular-nums", className)}>
      {chars.map((char, i) => {
        // Keyed from the right, so units stay units when the length changes.
        const place = chars.length - i;
        return /\d/.test(char) ? (
          <span key={`${place}-${char}`} className="digit-roll inline-block">
            {char}
          </span>
        ) : (
          <span key={`${place}-${char}`}>{char}</span>
        );
      })}
    </span>
  );
}
