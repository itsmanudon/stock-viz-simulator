import { RegimePopover } from "@/components/regime-popover";
import { getRegime } from "@/lib/api/chart-context";

/**
 * A3.5 (M3.1): the market regime per market in the product top bar, beside
 * the data-date chip. An async server component (cached ten minutes); a
 * failed call renders nothing. Unit tests that render the shell mock it.
 */
export async function RegimeBadges() {
  const regime = await getRegime().catch(() => null);
  if (!regime?.markets.length) return null;
  return (
    <div className="flex items-center gap-1" data-testid="regime-badges">
      {regime.markets.map((market) => (
        <RegimePopover
          key={market.market}
          market={market}
          method={regime.method}
          disclaimer={regime.disclaimer}
        />
      ))}
    </div>
  );
}
