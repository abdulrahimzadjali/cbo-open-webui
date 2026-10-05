<#
.SYNOPSIS
    Safely synchronizes CBO AI custom branch with the upstream Open WebUI repository.
.DESCRIPTION
    1. Fetches latest commits from upstream (https://github.com/open-webui/open-webui.git).
    2. Fast-forwards the clean 'main' tracking branch.
    3. Pushes updated 'main' to your fork (origin).
    4. Merges 'main' into 'custom' branch.
    5. Preserves CBO assets and branding without manual conflict resolution.
    6. Pushes updated 'custom' branch to your fork (origin).
#>

[CmdletBinding()]
param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"

Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host "  CBO AI - Upstream Synchronization Pipeline         " -ForegroundColor Cyan
Write-Host "=====================================================" -ForegroundColor Cyan

# 1. Check working directory status
$status = git status --porcelain
if ($status -and -not $Force) {
    Write-Host "[!] Working tree has uncommitted changes:" -ForegroundColor Yellow
    Write-Host $status
    Write-Error "Please commit or stash your changes before running sync, or run with -Force."
    exit 1
}

# 2. Verify upstream remote exists
$remotes = git remote
if ($remotes -notcontains "upstream") {
    Write-Host "[*] Adding upstream remote..." -ForegroundColor Green
    git remote add upstream https://github.com/open-webui/open-webui.git
}

# 3. Fetch upstream
Write-Host "[*] Fetching latest changes from upstream..." -ForegroundColor Green
git fetch upstream

# 4. Update local main
Write-Host "[*] Updating local 'main' branch..." -ForegroundColor Green
git checkout main
git merge --ff-only upstream/main

# 5. Push main to fork
Write-Host "[*] Pushing updated 'main' to your GitHub fork (origin)..." -ForegroundColor Green
git push origin main

# 6. Switch back to custom branch and merge main
Write-Host "[*] Merging upstream updates into 'custom' branch..." -ForegroundColor Green
git checkout custom

try {
    git merge main -m "Sync upstream/main into custom"
    Write-Host "[+] Clean merge completed successfully!" -ForegroundColor Green
} catch {
    Write-Host "[!] Checking for conflicts..." -ForegroundColor Yellow
    # If binary static assets conflicted, keep our CBO branded assets
    $conflicts = git diff --name-only --diff-filter=U
    foreach ($file in $conflicts) {
        if ($file -like "static/*" -or $file -like "*.webmanifest") {
            Write-Host "    Auto-resolving CBO asset: $file (keeping ours)" -ForegroundColor Cyan
            git checkout --ours -- $file
            git add $file
        }
    }
    
    $remaining = git diff --name-only --diff-filter=U
    if (-not $remaining) {
        git commit -m "Sync upstream/main into custom (resolved brand assets)"
        Write-Host "[+] All asset conflicts resolved automatically!" -ForegroundColor Green
    } else {
        Write-Host "[X] Unresolved code conflicts detected in:" -ForegroundColor Red
        Write-Host $remaining
        Write-Error "Please resolve remaining code conflicts manually, then run: git commit"
        exit 1
    }
}

# 7. Ensure CBO branding assets are regenerated
Write-Host "[*] Verifying CBO brand assets..." -ForegroundColor Green
if (Test-Path "scripts/setup-cbo-branding.py") {
    python scripts/setup-cbo-branding.py
}

# 8. Push custom to origin
Write-Host "[*] Pushing updated 'custom' branch to origin..." -ForegroundColor Green
git push origin custom

Write-Host "=====================================================" -ForegroundColor Green
Write-Host "  Synchronization completed successfully!             " -ForegroundColor Green
Write-Host "  Your fork is now up-to-date with upstream.         " -ForegroundColor Green
Write-Host "=====================================================" -ForegroundColor Green
