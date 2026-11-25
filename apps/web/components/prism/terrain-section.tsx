import { MarketTerrain } from "./market-terrain";
import { loadTerrain } from "./terrain-data";

/** Server half: loads the stored closes, renders nothing when there are too few. */
export async function TerrainSection() {
  const data = await loadTerrain();
  return data ? <MarketTerrain data={data} /> : null;
}
