$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectDir

$windowsCdpUrl = "http://127.0.0.1:9222/json/version"
$containerCdpBase = "http://host.docker.internal:9222"
$webUiUrl = "http://127.0.0.1:8765"

function Get-CdpVersion {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [int]$TimeoutSec = 2
    )

    try {
        $payload = Invoke-RestMethod -Uri $Url -TimeoutSec $TimeoutSec
        if (-not $payload.webSocketDebuggerUrl) {
            throw "response is missing webSocketDebuggerUrl"
        }
        return $payload
    } catch {
        return $null
    }
}

function Wait-CdpVersion {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [int]$TimeoutSec = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    do {
        $payload = Get-CdpVersion -Url $Url
        if ($payload) { return $payload }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    return $null
}

function Wait-WebUi {
    param([int]$TimeoutSec = 60)

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    do {
        try {
            $null = Invoke-RestMethod -Uri "$webUiUrl/api/preflight" -TimeoutSec 3
            return $true
        } catch {
            Start-Sleep -Seconds 1
        }
    } while ((Get-Date) -lt $deadline)
    return $false
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker was not found. Install and start Docker Desktop, then rerun .\start.ps1."
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop is not running or is not reachable. Start Docker Desktop and wait until it reports Engine running."
}

if (-not (Test-Path (Join-Path $projectDir ".env"))) {
    throw "Missing .env. Copy .env.example to .env, configure an Aliyun/Token Plan/PPIO model API key, then rerun .\start.ps1."
}

$chromeCandidates = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$chrome = $chromeCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $chrome) {
    throw "Google Chrome was not found. Install Chrome for the current Windows user, then rerun .\start.ps1."
}

$profile = Join-Path $env:LOCALAPPDATA "AmazonSelector\ChromeProfile"
$cdpVersion = Get-CdpVersion -Url $windowsCdpUrl
if (-not $cdpVersion) {
    New-Item -ItemType Directory -Force -Path $profile | Out-Null
    # Keep the debugging endpoint on Windows loopback. Docker Desktop exposes
    # it to this project's container through host.docker.internal; never bind
    # Chrome 9222 directly to the LAN.
    Start-Process -FilePath $chrome -ArgumentList @(
        "--remote-debugging-address=127.0.0.1",
        "--remote-debugging-port=9222",
        "--user-data-dir=$profile",
        "--no-first-run",
        "--no-default-browser-check",
        "https://www.amazon.com/"
    )
    $cdpVersion = Wait-CdpVersion -Url $windowsCdpUrl -TimeoutSec 30
}

if (-not $cdpVersion) {
    throw @"
Dedicated Chrome did not expose $windowsCdpUrl within 30 seconds.
Close only the Chrome window using this profile and retry:
  $profile
If port 9222 is occupied, inspect it with:
  netstat -ano | findstr :9222
Do not add --remote-debugging-address=0.0.0.0 or expose port 9222 through Windows Firewall.
"@
}

Write-Host "Windows CDP ready: $($cdpVersion.Browser)"

# An accidental BU_CDP_HTTP=http://127.0.0.1:9222 in .env points back at the
# container. Force the correct consumer endpoint for this Compose invocation.
$env:BU_CDP_HTTP = $containerCdpBase

docker compose config --quiet
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose configuration is invalid. Review the error above and the project .env file."
}

docker compose up -d --build amazon-selector
if ($LASTEXITCODE -ne 0) {
    throw "The amazon-selector container failed to build or start. Run: docker compose logs --tail=200 amazon-selector"
}

# Verify the exact route consumed by the application. Chrome rejects an
# external-looking Host header on /json/version, so the application resolves
# it with a loopback Host header and rewrites the returned websocket host.
$containerCdpCheck = @'
from agent.browser_agent import _resolve_cdp_ws
from agent.preflight import _assert_cdp_websocket_reachable
ws = _resolve_cdp_ws(timeout_seconds=5)
_assert_cdp_websocket_reachable(ws, timeout_seconds=5)
print(ws)
'@
$containerWs = docker compose exec -T amazon-selector python -c $containerCdpCheck 2>&1
if ($LASTEXITCODE -ne 0) {
    docker compose stop amazon-selector | Out-Null
    throw @"
Windows Chrome is healthy at $windowsCdpUrl, but amazon-selector cannot use it through $containerCdpBase.
The WebUI was stopped to avoid a false-ready sourcing run.

Diagnostics:
$($containerWs | Out-String)
Recovery:
  1. Ensure Docker Desktop is running with Linux containers.
  2. Run: docker compose run --rm amazon-selector python -c "from agent.browser_agent import _resolve_cdp_ws; print(_resolve_cdp_ws())"
  3. Do not expose Chrome 9222 to the LAN or Internet.
"@
}
Write-Host "Container CDP ready: $containerWs"

if (-not (Wait-WebUi -TimeoutSec 60)) {
    docker compose logs --tail=200 amazon-selector
    throw "The container started, but $webUiUrl/api/preflight did not become ready within 60 seconds."
}

$preflight = Invoke-RestMethod -Uri "$webUiUrl/api/preflight" -TimeoutSec 10
$cdpCheck = $preflight.checks | Where-Object { $_.key -eq "1688_browser" } | Select-Object -First 1
if (-not $cdpCheck -or $cdpCheck.level -ne "ok") {
    docker compose stop amazon-selector | Out-Null
    throw "Container CDP preflight failed: $($cdpCheck.label) - $($cdpCheck.detail)"
}

$sellerSpriteCheck = $preflight.checks | Where-Object { $_.key -eq "seller_sprite_browser" } | Select-Object -First 1
if (-not $sellerSpriteCheck -or $sellerSpriteCheck.level -ne "ok") {
    Write-Warning @"
WebUI and Chrome CDP are ready, but formal SellerSprite sourcing is not ready:
  $($sellerSpriteCheck.label)
  $($sellerSpriteCheck.detail)

Open the dedicated Chrome profile, enable and log in to SellerSprite, log in to 1688,
then configure the reviewed locator profile/download directory in the WebUI and rerun preflight.
The WebUI stays available for this setup; do not start a formal run until this check is OK.
"@
} else {
    Write-Host "SellerSprite browser preflight ready."
}

Start-Process $webUiUrl
Write-Host "Amazon Selector WebUI started at $webUiUrl"
Write-Host "Dedicated Chrome profile: $profile"
