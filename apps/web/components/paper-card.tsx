import { cn } from "@/lib/utils";

/**
 * The paper account card: the one brand object in the signed-in product.
 *
 * It is decorative, so it is hidden from assistive technology; every figure it
 * hints at is stated in text beside it. It only carries facts the account
 * actually has (the account number and its currency), never a rank, limit or
 * balance it cannot back up. Without an account (the public landing page) it
 * shows no number at all. Styling lives in `.paper-card` in globals.css.
 *
 * `fluid` sizes the type, padding and chip from the card's own width (container
 * units), so the card keeps one look at every size. The landing hero needs it:
 * the card in the phone and the larger card that flies out of it are the same
 * picture at two scales, and fixed rem text made the swap visibly shrink.
 */
export function PaperCard({
  accountId,
  currency,
  className,
  fluid = false,
}: {
  accountId?: number;
  currency: string;
  className?: string;
  fluid?: boolean;
}) {
  const number = accountId === undefined ? null : String(accountId).padStart(4, "0").slice(-4);

  const label = number ? `•••• ${number} · ${currency}` : `PAPER ACCOUNT · ${currency}`;

  if (fluid) {
    // Proportions taken from the card at 278px wide (the hero phone), where
    // the fixed sizes below read well: 24px wordmark, 20px padding, and so on.
    return (
      <div aria-hidden className={cn("paper-card [container-type:inline-size]", className)}>
        <div className="flex size-full flex-col justify-between p-[7.2cqw]">
          <div className="flex items-start justify-between gap-[4cqw]">
            <span className="text-[8.6cqw] leading-none font-semibold tracking-[-0.04em]">
              stockviz
            </span>
            <span className="rounded-[2.2cqw] border border-white/25 bg-black/25 px-[2.2cqw] py-[0.7cqw] font-mono text-[3.6cqw] leading-[1.4] font-medium tracking-[0.08em]">
              PAPER
            </span>
          </div>
          <div className="flex items-end justify-between gap-[4cqw] font-mono text-[4cqw] leading-[1.45] font-medium tracking-[0.06em]">
            <span>{label}</span>
            <span className="relative h-[7.2cqw] w-[10cqw] rounded-[1.8cqw] bg-linear-to-br from-[#e7ecf5] to-[#9aa6bb] shadow-[inset_0_0_0_1px_rgb(0_0_0/0.2)]" />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      aria-hidden
      className={cn("paper-card flex flex-col justify-between p-4 sm:p-5", className)}
    >
      <div className="flex items-start justify-between gap-3">
        <span className="text-xl font-semibold tracking-[-0.04em] sm:text-2xl">stockviz</span>
        <span className="rounded-md border border-white/25 bg-black/25 px-1.5 py-0.5 font-mono text-3xs font-medium tracking-[0.08em]">
          PAPER
        </span>
      </div>
      <div className="flex items-end justify-between gap-3 font-mono text-2xs font-medium tracking-[0.06em]">
        <span>{label}</span>
        <span className="relative h-5 w-7 rounded-[5px] bg-linear-to-br from-[#e7ecf5] to-[#9aa6bb] shadow-[inset_0_0_0_1px_rgb(0_0_0/0.2)]" />
      </div>
    </div>
  );
}
