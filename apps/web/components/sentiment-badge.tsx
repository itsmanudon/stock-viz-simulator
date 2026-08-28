import type { Sentiment } from "@/lib/api";

type Props = {
  sentiment: Sentiment | null;
};

const STYLES: Record<Sentiment, string> = {
  positive: "border-positive/40 bg-positive-soft text-positive-soft-foreground",
  neutral: "border-border bg-neutral-soft text-neutral-soft-foreground",
  negative: "border-negative/40 bg-negative-soft text-negative-soft-foreground",
};

const LABELS: Record<Sentiment, string> = {
  positive: "Positive",
  neutral: "Neutral",
  negative: "Negative",
};

export function SentimentBadge({ sentiment }: Props) {
  if (sentiment === null) return null;
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-3xs font-medium uppercase tracking-wide ${STYLES[sentiment]}`}
      aria-label={`Sentiment: ${LABELS[sentiment]}`}
    >
      {LABELS[sentiment]}
    </span>
  );
}
