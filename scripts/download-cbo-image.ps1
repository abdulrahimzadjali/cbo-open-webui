<#
.SYNOPSIS
    Downloads, verifies, and optionally loads the CBO AI Docker image (.tar.gz) from GitHub Releases.
.DESCRIPTION
    Directly fetches the latest CBO AI container image archive from the GitHub repository release:
    https://github.com/abdulrahimzadjali/cbo-open-webui/releases/tag/cbo-latest
#>

[CmdletBinding()]
param (
    [string]$Repo = "abdulrahimzadjali/cbo-open-webui",
    [string]$Tag = "cbo-latest",
    [string]$OutputDir = "./docker-exports",
    [switch]$SkipLoad
)

$ErrorActionPreference = "Stop"

$ArchiveName = "cbo-open-webui-latest.tar.gz"
$ChecksumName = "$ArchiveName.sha256"

$BaseUrl = "https://github.com/$Repo/releases/download/$Tag"
$ArchiveUrl = "$BaseUrl/$ArchiveName"
$ChecksumUrl = "$BaseUrl/$ChecksumName"

if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

$ArchivePath = Join-Path $OutputDir $ArchiveName
$ChecksumPath = Join-Path $OutputDir $ChecksumName

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  CBO AI Docker Image Downloader" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Release Tag : $Tag"
Write-Host "Repository  : $Repo"
Write-Host "Output Dir  : $OutputDir"
Write-Host ""

Write-Host "[1/4] Downloading SHA-256 checksum..." -ForegroundColor Yellow
Invoke-WebRequest -Uri $ChecksumUrl -OutFile $ChecksumPath -UseBasicParsing
$ExpectedHash = (Get-Content $ChecksumPath).Trim().Split(" ")[0]
Write-Host "Expected SHA-256: $ExpectedHash" -ForegroundColor DarkGray

Write-Host "[2/4] Downloading container image archive (~1.1 GB)..." -ForegroundColor Yellow
Write-Host "URL: $ArchiveUrl"
Invoke-WebRequest -Uri $ArchiveUrl -OutFile $ArchivePath -UseBasicParsing
Write-Host "Download complete. File size: $([math]::Round((Get-Item $ArchivePath).Length / 1MB, 2)) MB" -ForegroundColor Green

Write-Host "[3/4] Verifying SHA-256 checksum..." -ForegroundColor Yellow
$ActualHash = (Get-FileHash -Path $ArchivePath -Algorithm SHA256).Hash.ToLower()
if ($ActualHash -ne $ExpectedHash.ToLower()) {
    Write-Error "Checksum verification FAILED! Expected: $ExpectedHash, Got: $ActualHash"
    exit 1
}
Write-Host "Checksum verified successfully!" -ForegroundColor Green

if (-not $SkipLoad) {
    Write-Host "[4/4] Loading container into Docker engine..." -ForegroundColor Yellow
    try {
        & docker load -i $ArchivePath
        Write-Host "Docker image loaded successfully!" -ForegroundColor Green
        Write-Host ""
        Write-Host "To run CBO AI:" -ForegroundColor Cyan
        Write-Host "  docker run -d -p 3000:8080 -v open-webui:/app/backend/data --name cbo-open-webui ghcr.io/$Repo`:latest" -ForegroundColor White
    }
    catch {
        Write-Warning "Could not automatically load into Docker (Docker daemon might not be running)."
        Write-Host "You can load manually later using: docker load -i $ArchivePath" -ForegroundColor Yellow
    }
} else {
    Write-Host "[4/4] Skipping Docker load (-SkipLoad specified)." -ForegroundColor DarkGray
    Write-Host "To load manually: docker load -i $ArchivePath" -ForegroundColor Yellow
}
