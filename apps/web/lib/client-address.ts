/**
 * The visitor's address, for rate-limit keys (signup, sign-in, visitor limits).
 *
 * `X-Forwarded-For` is a list: each proxy appends the address it received the
 * request from. Only the entries added by our own proxies can be trusted; the
 * left-most entry is whatever the client sent and can be anything. So the
 * address is taken `TRUSTED_PROXY_HOPS` entries from the right (default 1:
 * Railway's edge, which also replaces any client-supplied value). With
 * `TRUSTED_PROXY_HOPS=0` the header is ignored and every request shares one
 * key, which is right only when nothing sits in front of the server.
 *
 * `X-Real-IP` is not read: no proxy of ours sets it, so it is client-chosen.
 */

export const UNKNOWN_ADDRESS = "unknown";

export function trustedProxyHops(raw: string | undefined = process.env.TRUSTED_PROXY_HOPS): number {
  if (raw === undefined || raw.trim() === "") return 1;
  const n = Number.parseInt(raw, 10);
  return Number.isFinite(n) && n >= 0 ? n : 1;
}

export function clientAddress(h: Pick<Headers, "get">, hops: number = trustedProxyHops()): string {
  if (hops <= 0) return UNKNOWN_ADDRESS;
  const chain = (h.get("x-forwarded-for") ?? "")
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
  if (chain.length === 0) return UNKNOWN_ADDRESS;
  // Fewer entries than trusted hops: the left-most is the furthest we know.
  return chain[Math.max(chain.length - hops, 0)] ?? UNKNOWN_ADDRESS;
}
