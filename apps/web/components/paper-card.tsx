import { cn } from "@/lib/utils";

/**
 * The paper account card: the one brand object in the signed-in product.
 *
 * It is decorative, so it is hidden from assistive technology; every figure it
 * hints at is stated in text beside it. It only carries facts the account
 * actually has (the account number and its currency), never a rank, limit or
 * balance it cannot back up. Without an account (the public landing page) it
 * shows no number at all. Styling lives in `.paper-card` in globals.css.
 */
export function PaperCard({
  accountId,
  currency,
  className,
}: {
  accountId?: number;
  currency: string;
  className?: string;
}) {
  const number = accountId === undefined ? null : String(accountId).padStart(4, "0").slice(-4);

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
        <span>{number ? `•••• ${number} · ${currency}` : `PAPER ACCOUNT · ${currency}`}</span>
        <span className="relative h-5 w-7 rounded-[5px] bg-linear-to-br from-[#e7ecf5] to-[#9aa6bb] shadow-[inset_0_0_0_1px_rgb(0_0_0/0.2)]" />
      </div>
    </div>
  );
}
