# Networking: service discovery, proxies, and where addresses come from

> **Before this note:** read
> [Networking](../../infrastructure/networking.md) and
> [Docker](../../infrastructure/docker.md).

The recurring theme: **the same service has a different address depending
on who is asking**, and most configuration bugs in this repo are an address
that is correct for one asker and wrong for the current one.

## The core insight

```ts
// lib/api/client.ts
return typeof window === "undefined" ? SERVER_BASE : BROWSER_BASE;
```

The Next.js server is *inside* the cluster and resolves `stockviz-api` via
cluster DNS. The browser is on someone's laptop and cannot. One process,
two networks — so one client, two base URLs.

`API_URL` is read at runtime; `NEXT_PUBLIC_API_URL` is **inlined into the
JavaScript bundle at build time**. That distinction catches people out: you
cannot fix a wrong `NEXT_PUBLIC_*` by redeploying with a new env var. The
image must be rebuilt.

## Kubernetes service discovery

A Service is a **stable virtual IP plus a DNS name in front of a changing
set of pods**. Pods are ephemeral; their IPs change on every restart.

```yaml
spec:
  selector:
    app.kubernetes.io/name: stockviz
    app.kubernetes.io/component: api
  ports: [{ port: 8000, targetPort: http }]
```

Three things to be able to say:

1. **Labels decide membership, not names.** Any pod matching the selector
   receives traffic — which is what makes rolling updates seamless.
2. **Readiness gates membership.** A pod failing `/health` is removed from
   the Service's endpoints. That's how a database outage takes pods out of
   rotation *without* restarting them.
3. **`targetPort: http` is a named port.** Renaming the container's port
   breaks the Service; changing only the number does not.

DNS: `stockviz-api` within the namespace, or
`stockviz-api.stockviz.svc.cluster.local` fully qualified. ClusterIP is the
default type and the right one here — nothing outside should reach the API
directly.

### Service types, mapped

| Type | Reachable from | StockViz uses it? |
| --- | --- | --- |
| ClusterIP | Inside the cluster | ✅ API and web |
| NodePort | A port on every node | ❌ |
| LoadBalancer | Cloud LB with an external IP | ❌ (kind has no cloud provider) |
| Ingress (not a Service) | HTTP routing by host/path | Optional, not installed in CI |

The Ingress routes by path — `/v1`, `/live`, `/health` to the API, `/` to
web — and is honestly marked optional, because CI has no ingress
controller and uses `kubectl port-forward`.

Note `pathType`: `/health` is `Exact`, `/v1` is `Prefix`. One endpoint
versus a tree.

## North-south vs east-west

| | Traffic | Concerns |
| --- | --- | --- |
| **North-south** | Browser ↔ cluster | TLS, auth, rate limiting, DDoS |
| **East-west** | Service ↔ service | Discovery, retries, mTLS, network policy |

StockViz has north-south controls (auth bridge, rate limiting) and
essentially **no east-west controls**: no NetworkPolicies, no TLS inside
the cluster, no Kafka auth. Any pod can reach Postgres directly. Naming
that before an interviewer does is the right move — it's a lab, and the
gap is recorded in
[threat model T9](../../security/threat-model.md).

## The proxy-header problem

This one is a genuine correctness bug that looks like a config detail.

Behind a load balancer, `request.client.host` is **the proxy's address for
every request**. A rate limiter keyed on it therefore has *one global
bucket for every user on Earth* — and it will look like it's working,
because it does limit traffic.

```dockerfile
uvicorn ... --proxy-headers --forwarded-allow-ips='*'
```

`--proxy-headers` makes uvicorn honour `X-Forwarded-For`;
`--forwarded-allow-ips` says which peers may set it. Then:

```python
forwarded = request.headers.get("x-forwarded-for")
if forwarded:
    return f"ip:{forwarded.split(',')[0].strip()}"   # left-most = original client
```

`X-Forwarded-For` is append-only: each proxy adds the address it received
from. Left-most is the original client; everything after is proxy hops.

**The security caveat to volunteer:** the header is client-controllable.
With `--forwarded-allow-ips='*'`, a caller reaching the API directly could
spoof their rate-limit bucket. That's acceptable only because a trusted
proxy sits in front in every deployed environment. Exposed directly, you'd
want the right-most *trusted* hop and a restricted allow-list.

## Kafka's advertised listeners

```yaml
KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:29092,PLAINTEXT_HOST://localhost:9092
```

A Kafka client connects to a bootstrap server, receives **the addresses
the broker advertises**, and reconnects to those. So the broker must
advertise a different address depending on the network the client is on —
hence two listeners.

This is why `KAFKA_BOOTSTRAP_SERVERS` defaulting to `localhost:9092` bites
inside compose: the container connects to itself. The symptom is a
connection refused that looks like the broker is down.

## CORS — less important than it looks

```python
allow_origins=settings.cors_origins, allow_credentials=True
```

Authenticated traffic goes browser → **Next.js server** → API. That's
server-to-server, so CORS never applies to it. Only public reads called
directly from a client component are subject to CORS.

`allow_credentials=True` means the origin list can never be `*` — browsers
reject that pairing outright.

## Interview questions

**Foundation — "What does a Kubernetes Service do?"**
> Gives a stable virtual IP and DNS name in front of a changing set of
> pods, selected by labels. Pod IPs change constantly; the Service doesn't.

**Foundation — "ClusterIP vs NodePort vs LoadBalancer?"**
> Internal-only, a port on every node, and a cloud load balancer with an
> external IP. My API and web are ClusterIP — nothing outside should reach
> the API directly; external access is Ingress or port-forward.

**Strong SWE — "Why does your web app have two API base URLs?"**
> The Next.js server is in the cluster and resolves `stockviz-api` by
> cluster DNS. The browser is on a laptop and can't. The client picks by
> `typeof window === "undefined"`. And the browser one is inlined at build
> time, so a wrong value needs a rebuild, not a redeploy.

**Strong SWE — "Your rate limiter is behind a load balancer. What breaks?"**
> `request.client.host` becomes the proxy for every request, so every user
> shares one bucket — and it silently looks like it's working. Fix is
> uvicorn `--proxy-headers` plus reading the left-most `X-Forwarded-For`
> hop.

**Advanced — "That header is attacker-controlled. Isn't that a bypass?"**
> Yes, if the API were directly reachable — with `--forwarded-allow-ips='*'`
> a caller could spoof their bucket. It's safe only because a trusted proxy
> is always in front. Exposed directly, I'd take the right-most trusted hop
> and restrict the allow-list.

**Advanced — "Any pod in your cluster can reach Postgres. Problem?"**
> Yes — no NetworkPolicies, so there's no east-west segmentation, and Kafka
> has no auth either. In a single-tenant lab the risk is low, but in
> production I'd default-deny and allow only the flows that need to exist.

## Memorise vs understand

**Memorise:** ClusterIP/NodePort/LoadBalancer; `<svc>.<ns>.svc.cluster.local`;
left-most `X-Forwarded-For`; `NEXT_PUBLIC_*` is build-time.

**Understand:** why readiness gating is load balancing; why a broker
advertises different addresses per network; why a proxied rate limiter
fails silently rather than loudly.
