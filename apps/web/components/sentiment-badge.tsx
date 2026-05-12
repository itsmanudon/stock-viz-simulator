import type { Sentiment } from "@/lib/api";

type Props = {
  sentiment: Sentiment | null;
};

const STYLES: Record<Sentiment, string> = {
  positive: "border-green-500/40 bg-green-500/10 text-green-600 dark:text-green-400",
  neutral: "border-zinc-500/40 bg-zinc-500/10 text-zinc-600 dark:text-zinc-400",
  negative: "border-red-500/40 bg-red-500/10 text-red-600 dark:text-red-400",
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
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${STYLES[sentiment]}`}
      aria-label={`Sentiment: ${LABELS[sentiment]}`}
    >
      {LABELS[sentiment]}
    </span>
  );
}
