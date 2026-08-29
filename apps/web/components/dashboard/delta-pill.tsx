import { cn } from "@/lib/utils";

type Tone = "positive" | "negative" | "neutral";

/**
 * Rounded tinted chip carrying a signed change, as used throughout the
 * Financial Dashboard reference: value on the left, optional period on the
 * right ("+9.3% Y/Y").
 */
export function DeltaPill({
  value,
  period,
  tone,
  className,
}: {
  value: string;
  period?: string;
  /** Defaults to reading the sign off `value`. */
  tone?: Tone;
  className?: string;
}) {
  const resolved = tone ?? toneFromValue(value);

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        resolved === "positive" && "bg-positive-soft text-positive-soft-foreground",
        resolved === "negative" && "bg-negative-soft text-negative-soft-foreground",
        resolved === "neutral" && "bg-neutral-soft text-neutral-soft-foreground",
        className,
      )}
      data-financial
    >
      {value}
      {period ? <span className="font-normal opacity-70">{period}</span> : null}
    </span>
  );
}

function toneFromValue(value: string): Tone {
  if (value.startsWith("+")) return "positive";
  if (value.startsWith("-") || value.startsWith("−")) return "negative";
  return "neutral";
}
