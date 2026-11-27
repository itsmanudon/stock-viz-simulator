# Self-hosting StockViz

This guide runs StockViz on your own machine from one Compose command, with your own keys. **No market data ships with it:** the database starts empty except for the company list, and you fetch prices yourself.

You need Docker with Compose v2 and about 4 GB of free memory. The first build takes several minutes.

## 1. Secrets

Copy the template and fill in the three secrets. Generate each one separately:

```bash
cp infra/release.env.example infra/release.env
openssl rand -base64 32   # run three times: POSTGRES_PASSWORD, INTERNAL_API_TOKEN, AUTH_SECRET
```

`infra/release.env` is gitignored. If a secret is missing, `docker compose` stops and names it. Every provider key is optional, and a blank key turns that feature off:

| Key | Turns on |
| --- | --- |
| `ALPHA_VANTAGE_KEY` | The fallback daily source |
| `SEC_USER_AGENT` | SEC EDGAR fundamentals ("your name, your email") |
| `ALPACA_KEY_ID` and `ALPACA_SECRET_KEY` | US minute bars and the live IEX stream (free plan) |
| `TIINGO_API_KEY`, `MASSIVE_API_KEY` | US minute history |
| `SMTP_*`, `TELEGRAM_BOT_TOKEN` | Alert delivery |

## 2. Start it

```bash
docker compose -f infra/compose.release.yml --env-file infra/release.env up -d --build
docker compose -f infra/compose.release.yml --env-file infra/release.env --profile setup run --rm setup
```

The first command builds and starts Postgres, the API and the web app. The API applies the database migrations every time it starts. The second command runs once: it writes the symbol list and the rule presets, with no prices.

Open http://localhost:3100. Both ports are bound to `127.0.0.1` only. To reach the instance from another machine, put your own reverse proxy with TLS in front of it.

## 3. Check it

```bash
docker compose -f infra/compose.release.yml --env-file infra/release.env exec api python -m stockviz.cli doctor
```

`doctor` prints one line per check:

- `ok`, `warn` or `off` are informational.
- `fail` means something must be fixed, and the command then exits 1.
- It names keys and never prints their values.

## 4. Your first prices

```bash
docker compose -f infra/compose.release.yml --env-file infra/release.env exec api python -m stockviz.cli ingest AAPL MSFT
docker compose -f infra/compose.release.yml --env-file infra/release.env exec api python -m stockviz.cli metrics
```

`ingest` fetches daily bars from yfinance, which is free but rate-limited, so start with a few symbols. With `ENABLE_SCHEDULER=true` (the default), the nightly jobs then run inside the API.

## Upgrades and backups

- **Upgrade:** `git pull`, then the same `up -d --build`. Migrations apply on start.
- **Back up** the `stockviz_release_db` volume, for example:

  ```bash
  docker compose -f infra/compose.release.yml --env-file infra/release.env exec postgres pg_dump -U stockviz stockviz > backup.sql
  ```

- **Stop:** `docker compose -f infra/compose.release.yml down`. Your data stays in the volume. Adding `-v` deletes it.

## What this is not

- It is not a hosted service.
- Prices are end of day (minute bars only with your own US feed keys).
- Trading is paper only, and nothing places a real order.

The release licence and the classroom and research-analyst modes are still open (see `docs/a10-design-note.md` in the workspace).

## Who can create an account

New accounts are **closed by default** (`SIGNUP_MODE=closed`): the first
account on an empty database can still be created, so you can set the
instance up, and nobody after it. Set `SIGNUP_MODE=allowlist` with
`SIGNUP_ALLOWLIST=you@example.com,friend@example.com` to invite people, or
`SIGNUP_MODE=open` to let anyone sign up. Existing accounts always sign in.

