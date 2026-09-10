$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$baseCompose = (Resolve-Path -LiteralPath (Join-Path $repoRoot "infra/docker-compose.yml")).Path
$verifyCompose = (Resolve-Path -LiteralPath (Join-Path $repoRoot "infra/docker-compose.verify.yml")).Path
$project = "stockviz-pipeline-verify"

foreach ($path in @($baseCompose, $verifyCompose)) {
    if (-not $path.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Verification compose path escaped the repository root: $path"
    }
}

$artifactDir = Join-Path $repoRoot "artifacts/verification"
New-Item -ItemType Directory -Force -Path $artifactDir | Out-Null
$runId = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
$logPath = Join-Path $artifactDir "clean-pipeline-$runId.log"
$composePrefix = @(
    "compose", "-p", $project,
    "-f", $baseCompose,
    "-f", $verifyCompose,
    "--profile", "app",
    "--profile", "events",
    "--profile", "verify-tests"
)
$hadInternalToken = Test-Path Env:\INTERNAL_API_TOKEN
$previousInternalToken = $env:INTERNAL_API_TOKEN
$hadAuthSecret = Test-Path Env:\AUTH_SECRET
$previousAuthSecret = $env:AUTH_SECRET
$env:INTERNAL_API_TOKEN = "pipeline-verify-interpolation-token"
$env:AUTH_SECRET = "pipeline-verify-interpolation-auth"

function Invoke-VerifyCompose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$CommandArgs)

    # Windows PowerShell turns any native stderr line into an ErrorRecord when
    # ErrorActionPreference=Stop. Docker may emit non-fatal config warnings, so
    # capture both streams and use its process exit code as the authority.
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & docker @composePrefix @CommandArgs 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
    foreach ($line in $output) {
        $text = $line.ToString()
        Write-Host $text
        $text | Add-Content -LiteralPath $logPath -Encoding UTF8
    }
    if ($exitCode -ne 0) {
        throw "docker compose command failed ($exitCode): $($CommandArgs -join ' ')"
    }
}

Push-Location $repoRoot
try {
    "Credential-free clean verification started at $runId" | Set-Content -LiteralPath $logPath -Encoding UTF8

    # The project name constrains destructive cleanup to these disposable resources.
    Invoke-VerifyCompose down --volumes --remove-orphans
    Invoke-VerifyCompose build --no-cache api web api-tests

    Invoke-VerifyCompose up -d --wait postgres kafka
    Invoke-VerifyCompose up --no-deps kafka-init
    Invoke-VerifyCompose up -d --wait api web

    Invoke-VerifyCompose run --rm --no-deps api-tests pytest -q `
        tests/test_settings.py `
        tests/test_ingest_prices.py `
        tests/test_market_news_pipeline.py `
        tests/test_outbox.py `
        tests/test_event_contracts_market_news.py `
        tests/test_kafka_integration.py::test_market_event_pipeline_roundtrip `
        tests/test_kafka_integration.py::test_news_sentiment_event_pipeline_roundtrip

    $apiHealth = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:18000/live" -TimeoutSec 10
    $webHealth = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:13100/api/health" -TimeoutSec 10
    if ($apiHealth.StatusCode -ne 200 -or $webHealth.StatusCode -ne 200) {
        throw "Clean verification health check failed"
    }

    foreach ($image in @("stockviz-api:pipeline-verify", "stockviz-web:pipeline-verify", "stockviz-api-tests:pipeline-verify")) {
        $imageId = & docker image inspect $image --format "{{.Id}}"
        if ($LASTEXITCODE -ne 0) {
            throw "Could not inspect rebuilt image $image"
        }
        "image $image $imageId" | Add-Content -LiteralPath $logPath -Encoding UTF8
    }
    "health api=$($apiHealth.StatusCode) web=$($webHealth.StatusCode)" | Add-Content -LiteralPath $logPath -Encoding UTF8
    Write-Host "Credential-free clean verification passed. Evidence: $logPath"
}
finally {
    try {
        Invoke-VerifyCompose down --volumes --remove-orphans
    }
    finally {
        if ($hadInternalToken) {
            $env:INTERNAL_API_TOKEN = $previousInternalToken
        }
        else {
            Remove-Item Env:\INTERNAL_API_TOKEN -ErrorAction SilentlyContinue
        }
        if ($hadAuthSecret) {
            $env:AUTH_SECRET = $previousAuthSecret
        }
        else {
            Remove-Item Env:\AUTH_SECRET -ErrorAction SilentlyContinue
        }
        Pop-Location
    }
}
