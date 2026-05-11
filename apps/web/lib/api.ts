const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type HealthResponse = {
  status: "ok" | "degraded";
  version: string;
  database: "up" | "down";
};

export async function getApiHealth(): Promise<HealthResponse> {
  try {
    const res = await fetch(`${API_URL}/health`, { cache: "no-store" });
    if (!res.ok) {
      return { status: "degraded", version: "unknown", database: "down" };
    }
    return (await res.json()) as HealthResponse;
  } catch {
    return { status: "degraded", version: "unreachable", database: "down" };
  }
}
