export default function Loading() {
  return (
    <div className="w-full px-4 py-8 sm:px-6 xl:px-8">
      <div className="h-8 w-40 animate-pulse bg-surface-secondary" />
      <div className="mt-3 h-4 w-96 max-w-full animate-pulse bg-surface-secondary" />
      <div className="mt-8 grid gap-6 lg:grid-cols-[22rem_1fr]">
        <div className="h-96 animate-pulse bg-surface-secondary" />
        <div className="h-96 animate-pulse bg-surface-secondary" />
      </div>
      <span className="sr-only">Loading backtest workspace…</span>
    </div>
  );
}
