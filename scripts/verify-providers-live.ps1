$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$envFile = Join-Path $repoRoot "infra/.env"
if (-not (Test-Path -LiteralPath $envFile)) {
    throw "infra/.env is required. MASSIVE_SHADOW_ENABLED=true is required for this workflow."
}

$config = @{}
foreach ($rawLine in Get-Content -LiteralPath $envFile) {
    $line = $rawLine.Trim()
    if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
        continue
    }
    $name, $value = $line.Split("=", 2)
    $config[$name.Trim()] = $value.Trim().Trim('"').Trim("'")
}

function Config-Value([string]$Name) {
    if ($config.ContainsKey($Name)) {
        return [string]$config[$Name]
    }
    return ""
}

$massiveEnabled = (Config-Value "MASSIVE_SHADOW_ENABLED").ToLowerInvariant()
$massiveKey = Config-Value "MASSIVE_API_KEY"
$newsProvider = (Config-Value "NEWS_PROVIDER").ToLowerInvariant()
$newsdataKey = Config-Value "NEWSDATA_KEY"
$sentimentProvider = (Config-Value "SENTIMENT_PROVIDER").ToLowerInvariant()
$anthropicKey = Config-Value "ANTHROPIC_API_KEY"
$sentimentUrl = Config-Value "SENTIMENT_SERVICE_URL"

if ($massiveEnabled -ne "true") {
    throw "MASSIVE_SHADOW_ENABLED=true is required for private Massive verification."
}
if (-not $massiveKey) {
    throw "MASSIVE_SHADOW_ENABLED=true requires MASSIVE_API_KEY."
}
if ($newsProvider -notin @("", "none", "newsdata")) {
    throw "NEWS_PROVIDER must be none or newsdata."
}
if ($newsProvider -eq "newsdata" -and -not $newsdataKey) {
    throw "NEWS_PROVIDER=newsdata requires NEWSDATA_KEY."
}
if ($sentimentProvider -notin @("", "none", "anthropic", "http")) {
    throw "SENTIMENT_PROVIDER must be none, anthropic, or http."
}
if ($sentimentProvider -eq "anthropic" -and -not $anthropicKey) {
    throw "SENTIMENT_PROVIDER=anthropic requires ANTHROPIC_API_KEY."
}
if ($sentimentProvider -eq "http" -and -not $sentimentUrl) {
    throw "SENTIMENT_PROVIDER=http requires SENTIMENT_SERVICE_URL."
}

$baseCompose = (Resolve-Path -LiteralPath (Join-Path $repoRoot "infra/docker-compose.yml")).Path
$verifyCompose = (Resolve-Path -LiteralPath (Join-Path $repoRoot "infra/docker-compose.verify.yml")).Path
$privateRoot = Join-Path $repoRoot "artifacts/private/live-verification"
New-Item -ItemType Directory -Force -Path $privateRoot | Out-Null
$runId = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
$runDir = Join-Path $privateRoot $runId
New-Item -ItemType Directory -Path $runDir | Out-Null
$logPath = Join-Path $runDir "live-verification.log"
"Private live-provider verification started at $runId" | Set-Content -LiteralPath $logPath -Encoding UTF8

if (-not $runDir.StartsWith($privateRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Private artifact directory escaped its approved root."
}

$providerNames = @(
    "MASSIVE_SHADOW_ENABLED",
    "MASSIVE_API_KEY",
    "NEWS_PROVIDER",
    "NEWSDATA_KEY",
    "SENTIMENT_PROVIDER",
    "ANTHROPIC_API_KEY",
    "SENTIMENT_SERVICE_URL",
    "SENTIMENT_SERVICE_TOKEN",
    "SENTIMENT_MODEL_HINT"
)
$previousEnvironment = @{}
foreach ($name in $providerNames) {
    $previousEnvironment[$name] = if (Test-Path "Env:\$name") { [Environment]::GetEnvironmentVariable($name) } else { $null }
    [Environment]::SetEnvironmentVariable($name, (Config-Value $name))
}
foreach ($name in @("INTERNAL_API_TOKEN", "AUTH_SECRET")) {
    $previousEnvironment[$name] = if (Test-Path "Env:\$name") { [Environment]::GetEnvironmentVariable($name) } else { $null }
    $configured = Config-Value $name
    [Environment]::SetEnvironmentVariable(
        $name,
        $(if ($configured) { $configured } else { "private-live-verification-interpolation" })
    )
}

$project = "stockviz-pipeline-verify"
$composePrefix = @(
    "compose", "-p", $project,
    "-f", $baseCompose,
    "-f", $verifyCompose,
    "--profile", "app",
    "--profile", "events",
    "--profile", "verify-tests"
)

function Invoke-LiveCompose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$CommandArgs)

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
        throw "Live-provider container command failed ($exitCode)."
    }
}

function Invoke-LiveApi {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$CommandArgs)

    # Values are copied from the process by name only: -e MASSIVE_API_KEY -e NEWSDATA_KEY.
    $arguments = @(
        "run", "--rm", "--no-deps",
        "--volume", "${runDir}:/private-artifacts"
    )
    foreach ($name in $providerNames) {
        $arguments += @("-e", $name)
    }
    $arguments += @("api")
    $arguments += $CommandArgs
    Invoke-LiveCompose @arguments
}

Push-Location $repoRoot
try {
    Invoke-LiveCompose down --volumes --remove-orphans
    Invoke-LiveCompose build api
    $imageId = & docker image inspect "stockviz-api:pipeline-verify" --format "{{.Id}}"
    if ($LASTEXITCODE -ne 0) {
        throw "Rebuilt stockviz-api:pipeline-verify image is unavailable."
    }
    "image stockviz-api:pipeline-verify $imageId" | Add-Content -LiteralPath $logPath -Encoding UTF8

    Invoke-LiveCompose up -d --wait postgres
    Invoke-LiveApi alembic upgrade head
    Invoke-LiveApi python -m stockviz.cli seed
    Invoke-LiveApi python -m stockviz.cli ingest AAPL MSFT NVDA AMZN META TSLA JPM
    if ($newsProvider -eq "newsdata") {
        Invoke-LiveApi python -m stockviz.cli news AAPL
    }
    Invoke-LiveApi python -m stockviz.cli market-shadow AAPL MSFT NVDA AMZN META TSLA JPM --output-dir /private-artifacts/massive-shadow

    Write-Host "Private live-provider verification completed. Artifacts: $runDir"
}
finally {
    try {
        Invoke-LiveCompose down --volumes --remove-orphans
    }
    finally {
        foreach ($name in $previousEnvironment.Keys) {
            [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name])
        }
        Pop-Location
    }
}
