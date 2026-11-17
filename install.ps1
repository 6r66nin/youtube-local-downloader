# Installs/updates the `yt` CLI in C:\Tools\yt and adds it to the user PATH.
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\install.ps1
#   .\install.ps1 -Destination D:\Apps\yt -Force   # other folder / overwrite config
[CmdletBinding()]
param(
    [string]$Destination = 'C:\Tools\yt',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$source = $PSScriptRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error 'Python is not on PATH. Install it first (winget install Python.Python.3.12).'
}

New-Item -ItemType Directory -Force -Path $Destination | Out-Null

foreach ($file in 'yt.py', 'yt.cmd', 'README.md', 'LICENSE', 'config.example.toml') {
    $path = Join-Path $source $file
    if (Test-Path -LiteralPath $path) {
        Copy-Item -LiteralPath $path -Destination $Destination -Force
        Write-Host "  copied $file"
    }
}

# User config is never overwritten unless -Force is given.
$config = Join-Path $Destination 'config.toml'
if ((Test-Path -LiteralPath $config) -and -not $Force) {
    Write-Host '  kept existing config.toml (use -Force to overwrite)'
}
else {
    Copy-Item -LiteralPath (Join-Path $source 'config.example.toml') -Destination $config -Force
    Write-Host '  created config.toml from config.example.toml'
}

# User PATH: no admin needed, no duplicates.
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$entries = @($userPath -split ';' | Where-Object { $_ })
if ($entries -notcontains $Destination) {
    [Environment]::SetEnvironmentVariable('Path', (($entries + $Destination) -join ';'), 'User')
    Write-Host "  added $Destination to the user PATH (open a new terminal)"
}
else {
    Write-Host "  $Destination is already on the user PATH"
}

Write-Host ''
Write-Host "Installed in $Destination"
Write-Host 'Check dependencies with:  yt --version'
