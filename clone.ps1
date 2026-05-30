#!/usr/bin/env pwsh
<#
.SYNOPSIS
Clone GitHub repo with one-time token input.
Token stored in Git config (local, not pushed).

Usage:
  .\clone.ps1 owner/repo
  .\clone.ps1 owner/repo c:\path\to\clone

.EXAMPLE
  .\clone.ps1 gleekr/enxr c:\dev\enxr
#>

param(
    [Parameter(Mandatory=$true)][string]$Repo,
    [Parameter(Mandatory=$false)][string]$ClonePath
)

$RepoUrl = "https://github.com/$Repo.git"
if (-not $ClonePath) {
    $RepoName = $Repo.Split('/')[-1]
    $ClonePath = "$PWD\$RepoName"
}

# Check if token already stored in git config
$Token = git config --global github.token 2>$null
if (-not $Token) {
    Write-Host "[!] GitHub token not found in git config" -ForegroundColor Yellow
    $Token = Read-Host "Paste GitHub token (input hidden)" -AsSecureString
    $Token = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [System.Runtime.InteropServices.Marshal]::SecureStringToCoTaskMemUnicode($Token)
    )

    # Store token in git config (local, encrypted on Windows)
    git config --global github.token $Token
    Write-Host "[OK] Token stored in git config" -ForegroundColor Green
}

# Clone with token
$CloneUrl = $RepoUrl -replace "https://", "https://$Token@"
Write-Host "[clone] $Repo -> $ClonePath" -ForegroundColor Cyan
git clone $CloneUrl $ClonePath
if ($?) {
    Write-Host "[OK] Cloned to $ClonePath" -ForegroundColor Green
    cd $ClonePath
} else {
    Write-Host "[!] Clone failed" -ForegroundColor Red
    exit 1
}
