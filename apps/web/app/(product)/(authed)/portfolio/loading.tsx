const METRIC_SKELETONS = ["cash", "equities", "options", "return", "sharpe", "drawdown"];
const POSITION_SKELETONS = ["position-a", "position-b", "position-c", "position-d", "position-e"];

export default function Loading() {
  return (
    <output
      aria-label="Loading portfolio"
      className="w-full animate-pulse px-4 py-6 sm:px-6 lg:px-8 lg:py-8"
    >
      <div className="border-b border-border-muted pb-6">
        <div className="h-3 w-24 rounded-sm bg-muted" />
        <div className="mt-3 h-7 w-36 rounded-sm bg-muted" />
        <div className="mt-8 h-12 w-72 max-w-full rounded-sm bg-muted" />
        <div className="mt-8 h-[240px] rounded-sm bg-muted/60 sm:h-[300px] lg:h-[340px]" />
      </div>
      <div className="grid grid-cols-2 border-b border-border-muted lg:grid-cols-3 xl:grid-cols-6">
        {METRIC_SKELETONS.map((metric) => (
          <div key={metric} className="border-l border-border-muted px-4 py-5 first:border-l-0">
            <div className="h-2.5 w-20 rounded-sm bg-muted" />
            <div className="mt-3 h-5 w-28 max-w-full rounded-sm bg-muted" />
          </div>
        ))}
      </div>
      <div className="mt-8 h-10 border-b border-border-muted" />
      <div className="mt-6 space-y-3">
        {POSITION_SKELETONS.map((position) => (
          <div key={position} className="h-12 rounded-sm bg-muted/60" />
        ))}
      </div>
    </output>
  );
}
