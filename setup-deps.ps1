# Installs the external dependencies of yt: yt-dlp, ffmpeg, and a JavaScript
# runtime only if you don't already have node or deno.
# Usage: powershell -ExecutionPolicy Bypass -File .\setup-deps.ps1
[CmdletBinding()]
param(
    [string]$ToolsDir = 'C:\Tools',
    [switch]$SkipFfmpegFallback
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Test-Tool([string]$name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

function Test-YtDlp {
    if (Test-Tool 'yt-dlp') { return $true }
    & python -m yt_dlp --version *> $null
    return ($LASTEXITCODE -eq 0)
}

# --- yt-dlp -----------------------------------------------------------------
Write-Host '== yt-dlp =='
if (Test-YtDlp) {
    $where = if (Test-Tool 'yt-dlp') { (Get-Command yt-dlp).Source } else { 'python -m yt_dlp' }
    Write-Host "  already installed: $where"
}
else {
    winget install --id yt-dlp.yt-dlp -e --skip-dependencies `
        --accept-package-agreements --accept-source-agreements --disable-interactivity
    if (-not (Test-YtDlp)) {
        Write-Host '  winget route failed, trying pip...'
        & python -m pip install --user --disable-pip-version-check yt-dlp
    }
}

# --- ffmpeg -----------------------------------------------------------------
Write-Host ''
Write-Host '== ffmpeg =='
if (Test-Tool 'ffmpeg') {
    Write-Host "  already installed: $((Get-Command ffmpeg).Source)"
}
else {
    winget install --id Gyan.FFmpeg -e --accept-package-agreements `
        --accept-source-agreements --disable-interactivity

    if (-not (Test-Tool 'ffmpeg') -and -not $SkipFfmpegFallback) {
        # Fallback for slow networks: resume-capable download of a static build.
        $ffDir = Join-Path $ToolsDir 'ffmpeg'
        $zip = Join-Path $env:TEMP 'ffmpeg-essentials.zip'
        New-Item -ItemType Directory -Force -Path $ffDir | Out-Null

        if (-not (Test-Path $zip) -or (Get-Item $zip).Length -lt 10MB) {
            Write-Host '  downloading ffmpeg-essentials (~35 MB, may take a while)...'
            curl.exe -L -C - --retry 20 --retry-all-errors --retry-delay 5 `
                -o $zip 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
        }

        Write-Host '  extracting...'
        if (Get-Command tar -ErrorAction SilentlyContinue) {
            & tar -xf $zip -C $ffDir            # bsdtar: faster than Expand-Archive
        }
        else {
            Expand-Archive -LiteralPath $zip -DestinationPath $ffDir -Force
        }
        $bin = Get-ChildItem -Path $ffDir -Recurse -Directory -Filter 'bin' |
            Select-Object -First 1 -ExpandProperty FullName
        if (-not $bin) { throw 'no bin folder found inside the ffmpeg zip' }
        Remove-Item $zip -Force -ErrorAction SilentlyContinue

        $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
        $entries = @($userPath -split ';' | Where-Object { $_ })
        if ($entries -notcontains $bin) {
            [Environment]::SetEnvironmentVariable('Path', (($entries + $bin) -join ';'), 'User')
            Write-Host "  added $bin to the user PATH"
        }
    }
}

# --- JavaScript runtime ------------------------------------------------------
# yt-dlp needs one to solve YouTube's JS challenge. Most machines already have
# node, so deno is only installed when neither exists: no redundant installs.
Write-Host ''
Write-Host '== JavaScript runtime (node or deno) =='
if (Test-Tool 'node') {
    Write-Host "  using node: $((Get-Command node).Source)"
}
elseif (Test-Tool 'deno') {
    Write-Host "  using deno: $((Get-Command deno).Source)"
}
else {
    Write-Host '  none found, installing deno (single binary)...'
    winget install --id DenoLand.Deno -e --accept-package-agreements `
        --accept-source-agreements --disable-interactivity
}

Write-Host ''
Write-Host 'Summary (open a new terminal so PATH refreshes):'
foreach ($tool in 'yt-dlp', 'ffmpeg', 'ffprobe', 'node', 'deno') {
    $cmd = Get-Command $tool -ErrorAction SilentlyContinue
    if ($cmd) { Write-Host ("  {0,-8} OK    {1}" -f $tool, $cmd.Source) }
    else { Write-Host ("  {0,-8} -" -f $tool) }
}
