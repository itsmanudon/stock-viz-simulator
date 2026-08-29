/**
 * Process liveness for Kubernetes. Does not touch Postgres, Kafka, or FastAPI.
 *
 * The homepage SSRs featured tickers and must not be the kubelet probe path:
 * a slow /v1 round-trip would flap readiness, and Kubernetes overwriting
 * HOSTNAME used to make GET / hang while Next listened on the pod name.
 */
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json({ status: "ok" });
}
