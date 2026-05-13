# Boots Postgres + Adminer via Docker Compose, waits for the DB to be ready,
# then applies Alembic migrations and seeds initial data.
# Run from the repo root: .\scripts\db-init.ps1

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

# ── Step 1: start containers ────────────────────────────────────────────────
Write-Host "==> Starting Postgres + Adminer..."
docker compose -f infra/docker-compose.yml up -d

# ── Step 2: wait for Postgres to accept connections ─────────────────────────
Write-Host "==> Waiting for Postgres on 127.0.0.1:5434..."
$ready = $false
while (-not $ready) {
    $result = docker compose -f infra/docker-compose.yml exec -T postgres `
        pg_isready -U stockviz -d stockviz_dev -q 2>$null
    if ($LASTEXITCODE -eq 0) {
        $ready = $true
    } else {
        Start-Sleep -Seconds 1
    }
}
Write-Host "    Postgres is ready."

# ── Step 3: apply migrations ─────────────────────────────────────────────────
Write-Host "==> Applying Alembic migrations..."
uv --directory apps/api run alembic upgrade head

# ── Step 4: seed and backfill ────────────────────────────────────────────────
Write-Host "==> Seeding symbol list..."
uv --directory apps/api run python -m stockviz.cli seed

Write-Host "==> Running one-time CSV backfill..."
uv --directory apps/api run python -m stockviz.cli backfill

Write-Host ""
Write-Host "Done. Services:"
Write-Host "  Postgres  127.0.0.1:5434"
Write-Host "  Adminer   http://localhost:8080  (server: postgres, user/pass/db: stockviz / stockviz_dev / stockviz)"
Write-Host ""
Write-Host "Next: open two terminals and run:"
Write-Host "  pnpm api:dev   # FastAPI on http://127.0.0.1:8000"
Write-Host "  pnpm dev:web   # Next.js on http://localhost:3000"
