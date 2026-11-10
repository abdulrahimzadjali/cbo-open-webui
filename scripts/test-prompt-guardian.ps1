# Test the CBO Prompt Guardian from the built Docker image.
#
# Usage:
#   .\scripts\test-prompt-guardian.ps1            # full run (E2E + live server)
#   .\scripts\test-prompt-guardian.ps1 -E2EOnly   # fast, no server startup
#
# Exit code 0 = all checks passed.

param(
    [string]$Image = 'cbo-ai:guardian-test',
    [int]$Port = 8099,
    [switch]$E2EOnly
)

$ErrorActionPreference = 'Stop'
$failed = @()

function Write-Section($t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function Write-Pass($t)    { Write-Host "  PASS  $t" -ForegroundColor Green }
function Write-Fail($t)    { Write-Host "  FAIL  $t" -ForegroundColor Red; $script:failed += $t }

Write-Section "0. Image"
$img = docker images -q $Image
if (-not $img) {
    Write-Fail "image '$Image' not found. Build it with: docker build -t $Image ."
    exit 1
}
Write-Pass "image present: $img"

# ---------------------------------------------------------------------------
Write-Section "1. In-container end-to-end suite (cbo_e2e.py)"
docker run --rm -e PYTHONIOENCODING=utf-8 -e WEBUI_SECRET_KEY=guardian-e2e-only $Image python /app/backend/cbo_e2e.py
if ($LASTEXITCODE -ne 0) { Write-Fail "cbo_e2e.py reported failures (exit $LASTEXITCODE)" }
else { Write-Pass "cbo_e2e.py all checks passed" }

if ($E2EOnly) {
    Write-Section "Summary"
    if ($failed) { $failed | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }; exit 1 }
    Write-Host "All checks passed." -ForegroundColor Green
    exit 0
}

# ---------------------------------------------------------------------------
Write-Section "2. Start the server"
docker rm -f cbo-guardian-test 2>$null | Out-Null

# A fresh named volume keeps this test isolated from any real deployment data.
docker volume rm cbo-guardian-test-data 2>$null | Out-Null

docker run -d --name cbo-guardian-test `
    -p "${Port}:8080" `
    -v cbo-guardian-test-data:/app/backend/data `
    -e WEBUI_SECRET_KEY=guardian-test-secret `
    -e WEBUI_AUTH=true `
    -e ENABLE_SIGNUP=true `
    -e DEFAULT_USER_ROLE=admin `
    $Image | Out-Null

if ($LASTEXITCODE -ne 0) { Write-Fail "container failed to start"; exit 1 }

Write-Host "  waiting for /health ..."
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 2
    try {
        $h = Invoke-RestMethod -Uri "http://localhost:$Port/health" -TimeoutSec 3
        if ($h.status -eq $true) { $ready = $true; break }
    } catch { }
    if ((docker ps -q -f name=cbo-guardian-test) -eq '') { break }
}
if (-not $ready) {
    Write-Fail "server did not become healthy"
    docker logs --tail 40 cbo-guardian-test
} else { Write-Pass "server healthy on http://localhost:$Port" }

Write-Section "3. Verify guardian artifacts inside the running container"
$checks = @{
    'guardian package present'      = 'test -f /app/backend/open_webui/cbo/guardian/engine.py'
    'router present'                = 'test -f /app/backend/open_webui/cbo/guardian/router.py'
    'hook wired in middleware'      = 'grep -q "guard_chat_payload" /app/backend/open_webui/utils/middleware.py'
    'config keys registered'        = 'grep -q "cbo.guardian.enabled" /app/backend/open_webui/config.py'
    'admin API mounted in main'     = 'grep -q "cbo_guardian_router" /app/backend/open_webui/main.py'
}
foreach ($k in $checks.Keys) {
    docker exec cbo-guardian-test sh -c $checks[$k] 2>$null
    if ($LASTEXITCODE -eq 0) { Write-Pass $k } else { Write-Fail $k }
}

Write-Section "Summary"
if (-not $ready) {
    $failed | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}

docker rm -f cbo-guardian-test | Out-Null
if ($failed) {
    $failed | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    Write-Host "`nFAILED: $($failed.Count) check(s)" -ForegroundColor Red
    exit 1
}
Write-Host "`nAll checks passed." -ForegroundColor Green
Write-Host "Container stopped. To explore manually:" -ForegroundColor Yellow
Write-Host "  docker run -d --name cbo-guardian -p 8080:8080 -v cbo-guardian-test-data:/app/backend/data $Image" -ForegroundColor Yellow
exit 0
