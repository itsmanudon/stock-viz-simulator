# Networking

Four environments, four different sets of addresses for the same services.
Most StockViz setup failures are an address that is right for one
environment and wrong for the current one.

## The address matrix

| From → To | Local dev | Docker Compose | Kubernetes | Production |
| --- | --- | --- | --- | --- |
| Browser → web | `127.0.0.1:3000` | `127.0.0.1:3100` | port-forward / Ingress | Vercel domain |
| Browser → API | `127.0.0.1:8000` | `127.0.0.1:8000` | port-forward `:8000` | Render domain |
| Web **server** → API | `127.0.0.1:8000` | `http://api:8000` | `http://stockviz-api:8000` | Render internal URL |
| API → Postgres | `127.0.0.1:5434` | `postgres:5432` | `stockviz-postgres:5432` | Render internal |
| Worker → Kafka | `localhost:9092` | `kafka:29092` | `stockviz-kafka-bootstrap:9092` | n/a |

Two rows cause almost all confusion.

### The browser cannot resolve cluster DNS

`NEXT_PUBLIC_API_URL` is **inlined into the browser bundle at image build
time**. It must be a URL the user's laptop can reach:

```dockerfile
# apps/web/Dockerfile
# NEXT_PUBLIC_API_URL is inlined at build time and must be a URL the *browser*
# can reach (port-forward / ingress host). Cluster DNS such as
# http://stockviz-api:8000 is not reachable from the user's laptop.
```

Meanwhile `API_URL` is read at **runtime** by the Next.js server, which
*is* inside the cluster and *can* resolve `stockviz-api`. The ConfigMap
sets both, differently:

```yaml
API_URL: http://stockviz-api:8000          # server-side, cluster DNS
NEXT_PUBLIC_API_URL: http://localhost:8000 # browser-side, port-forward
```

`lib/api/client.ts` picks between them at call time:

```ts
function baseUrl(): string {
  return typeof window === "undefined" ? SERVER_BASE : BROWSER_BASE;
}
```

That one line is the whole browser/server networking split.

### Kafka's dual listeners

```yaml
KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:29092,PLAINTEXT_HOST://localhost:9092
```

A Kafka broker tells clients where to reach it, so it must advertise a
different address depending on who is asking. `kafka:29092` is for
containers on the compose network; `localhost:9092` is for a worker running
natively on the host. `KAFKA_BOOTSTRAP_SERVERS` defaults to
`localhost:9092`, so **every worker running inside compose must override
it** — the most common Kafka symptom in this repo is connection refused to
`localhost:9092` from inside a container.

## Kubernetes service discovery

```yaml
kind: Service
metadata: { name: stockviz-api, namespace: stockviz }
spec:
  selector:
    app.kubernetes.io/name: stockviz
    app.kubernetes.io/component: api
  ports: [{ name: http, port: 8000, targetPort: http }]
```

Type defaults to **ClusterIP** — reachable only inside the cluster, which
is correct: nothing outside should reach the API directly.

Three things worth understanding:

- **Selector, not name, decides membership.** The Service routes to any
  pod matching those labels. That is what makes rolling updates seamless —
  new pods join the Service as soon as they pass readiness.
- **`targetPort: http` is a named port**, resolved against the container's
  `ports: [{ name: http, containerPort: 8000 }]`. Renaming the container
  port breaks the Service; changing the number alone does not.
- **DNS is `<service>.<namespace>.svc.cluster.local`**, and within the same
  namespace the short name `stockviz-api` resolves.

Readiness gating is the load-balancing mechanism people miss: a pod
failing `/health` is removed from the Service's endpoints, so traffic
stops without a restart. See
[observability](../observability/overview.md).

### North-south vs east-west

| Direction | Traffic | Mechanism here |
| --- | --- | --- |
| North-south | Browser → cluster | Ingress (optional) or `kubectl port-forward` |
| East-west | web → API, workers → Kafka/Postgres | ClusterIP Services + cluster DNS |

`infra/k8s/optional/ingress.yaml` routes by path — `/v1`, `/live`,
`/health` to the API, `/` to the web app — on host `stockviz.local`. It is
**optional and not installed in CI**, which is honest: CI has no ingress
controller, so the smoke test uses port-forward.

Note the `pathType` distinction: `/health` is `Exact` while `/v1` and
`/live` are `Prefix`. `/health` is a single endpoint; `/v1` is a tree.

## Proxy headers — a correctness issue, not a detail

Behind a load balancer, `request.client.host` is the **proxy's** address
for every request. Without proxy-header handling, the rate limiter buckets
every user on the planet together.

```dockerfile
CMD ["sh", "-c", "... uvicorn ... --proxy-headers --forwarded-allow-ips='*'"]
```

`--proxy-headers` makes uvicorn honour `X-Forwarded-For` /
`X-Forwarded-Proto`; `--forwarded-allow-ips='*'` trusts the chain from any
peer. `limiter.py::client_key` then reads the **left-most**
`X-Forwarded-For` hop as the original client.

**Security note.** `X-Forwarded-For` is client-controllable, so trusting
the left-most hop means a caller can spoof their rate-limit bucket — and
`--forwarded-allow-ips='*'` trusts any peer. That is acceptable only
because a trusted proxy sits in front in every deployed environment. If
the API were ever exposed directly, this would need to be the *right-most
trusted* hop and a restricted allow-list.

## CORS

```python
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
```

`CORS_ORIGINS` accepts a single URL, a comma-separated list, or a JSON
array (`settings.py::_parse_cors_origins`, with `NoDecode` to stop
pydantic-settings parsing it as JSON first). Default is
`http://localhost:3000`.

**CORS is less load-bearing here than it looks.** Authenticated calls go
browser → Next.js server → API, so they are server-to-server and CORS
never applies. Only public reads called directly from a client component
are subject to it.

`allow_credentials=True` means the origin list must never become `*` —
browsers reject that combination outright.

## Compose specifics

- Postgres binds **5434**, not 5432, because the developer has a native
  install on 5432.
- Web publishes **3100**, not 3000, because 3000 is commonly taken.
- Use `127.0.0.1`, not `localhost`, in env defaults: Windows IPv6 lookups
  can otherwise bypass the container.
- `AUTH_URL` is deliberately **unset** so NextAuth derives the origin from
  the request host, which is why dev works on any port. That is also why
  `AUTH_TRUST_HOST=true` is required for production builds outside Vercel.

## What is missing

| Missing | Consequence |
| --- | --- |
| NetworkPolicies | Any pod can reach Postgres and Kafka directly |
| TLS inside the cluster | All east-west traffic is plaintext |
| Kafka auth (SASL/mTLS) | Any pod can produce or consume |
| Ingress in the default path | Access is port-forward |
| Service mesh | No mTLS, retries, or traffic shifting |

See [threat model T9](../security/threat-model.md).
