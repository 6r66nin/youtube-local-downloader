# Acceptance test (optional: needs network and the yt command installed).
# Uses a temp folder and its own archive, so your Downloads folder is untouched.
# Reads media metadata with ffprobe, falling back to `ffmpeg -i`.
#
# Usage:  powershell -ExecutionPolicy Bypass -File .\tests\acceptance.ps1
#         ... -Url "https://www.youtube.com/watch?v=OTHER"
[CmdletBinding()]
param(
    [string]$Url = 'https://www.youtube.com/watch?v=LXb3EKWsInQ'  # 1 min, CC
)

$ErrorActionPreference = 'Stop'
$root = Join-Path $env:TEMP ("yt-test-" + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Force -Path $root | Out-Null

# Isolate state: a private config file and archive for this run only.
$env:YT_CONFIG = Join-Path $root 'config.toml'
$env:YT_ARCHIVE = Join-Path $root '.archive'

$results = @()

function Add-Result([string]$name, [bool]$ok, [string]$detail = '') {
    $script:results += [pscustomobject]@{ Test = $name; State = $(if ($ok) { 'OK' } else { 'FAIL' }); Detail = $detail }
    $color = if ($ok) { 'Green' } else { 'Red' }
    Write-Host ("[{0}] {1}  {2}" -f $(if ($ok) { ' OK ' } else { 'FAIL' }), $name, $detail) -ForegroundColor $color
}

function Find-Media([string]$ext) {
    Get-ChildItem -Path $root -Recurse -File -Filter "*.$ext" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
}

function Get-MediaInfo([string]$file) {
    $info = [pscustomobject]@{
        Duration = 0.0; BitRate = 0; Heights = @(); HasAudio = $false; Title = ''; Artist = ''
    }

    if (Get-Command ffprobe -ErrorAction SilentlyContinue) {
        $json = (& ffprobe -v error -print_format json -show_format -show_streams $file) -join "`n"
        $data = $json | ConvertFrom-Json
        $info.Duration = [double]($data.format.duration -replace ',', '.')
        $info.BitRate = [double]($data.format.bit_rate -replace ',', '.')
        $info.Heights = @($data.streams | Where-Object { $_.codec_type -eq 'video' -and $_.height } | ForEach-Object { [int]$_.height })
        $info.HasAudio = [bool]($data.streams | Where-Object { $_.codec_type -eq 'audio' })
        $info.Title = [string]$data.format.tags.title
        $info.Artist = [string]$data.format.tags.artist
        if (-not $info.Artist) { $info.Artist = [string]$data.format.tags.album_artist }
        return $info
    }

    $raw = (& ffmpeg -hide_banner -i $file 2>&1) -join "`n"
    $m = [regex]::Match($raw, 'Duration: (\d+):(\d+):(\d+(?:[.,]\d+)?)')
    if ($m.Success) {
        $info.Duration = [double]$m.Groups[1].Value * 3600 + [double]$m.Groups[2].Value * 60 +
            [double]($m.Groups[3].Value -replace ',', '.')
    }
    $m = [regex]::Match($raw, 'Duration: .*?bitrate: (\d+) kb/s')
    if ($m.Success) { $info.BitRate = [double]$m.Groups[1].Value * 1000 }
    $info.HasAudio = $raw -match 'Stream #\S+.*Audio:'
    $info.Heights = @(
        [regex]::Matches($raw, 'Video:.*?(\d{2,4})x(\d{2,4})') | ForEach-Object { [int]$_.Groups[2].Value }
    )
    $m = [regex]::Match($raw, '(?m)^\s*title\s*:\s*(.+)$')
    if ($m.Success) { $info.Title = $m.Groups[1].Value.Trim() }
    $m = [regex]::Match($raw, '(?m)^\s*artist\s*:\s*(.+)$')
    if ($m.Success) { $info.Artist = $m.Groups[1].Value.Trim() }
    return $info
}

function Invoke-Yt {
    param([string[]]$Arguments)
    $out = & yt @Arguments 2>&1
    return @{ Code = $LASTEXITCODE; Output = ($out -join "`n") }
}

if (-not (Get-Command yt -ErrorAction SilentlyContinue)) {
    throw 'the `yt` command was not found (run install.ps1 and open a new terminal)'
}

Write-Host "Test folder: $root"
Write-Host "Video: $Url"
Write-Host ''

# --- 1. exact cut ------------------------------------------------------------
$r = Invoke-Yt @('-t', '0:30-1:00', '-q', '1080', '-o', $root, $Url)
$clip = Find-Media 'mp4'
$info = if ($clip) { Get-MediaInfo $clip.FullName } else { $null }
$ok = ($r.Code -eq 0) -and $clip -and ([math]::Abs($info.Duration - 30) -le 2)
Add-Result 'cut 0:30-1:00 -> ~30 s' $ok ("exit=$($r.Code) duration=$(if ($info) { [math]::Round($info.Duration,2) } else { 'n/a' })s")

# --- 2. MP3 audio with metadata ---------------------------------------------
$r = Invoke-Yt @('-a', '-o', $root, $Url)
$mp3 = Find-Media 'mp3'
$info = if ($mp3) { Get-MediaInfo $mp3.FullName } else { $null }
$ok = ($r.Code -eq 0) -and $mp3 -and $info.Title -and $info.BitRate -gt 100000
Add-Result 'MP3 audio with metadata' $ok ("exit=$($r.Code) title='$(if ($info) { $info.Title })' bitrate=$(if ($info) { [int]($info.BitRate / 1000) } else { 0 }) kb/s")

# --- 3. 720p video with audio (merge) ---------------------------------------
$r = Invoke-Yt @('-q', '720', '-o', $root, $Url)
$video = Get-ChildItem -Path $root -Recurse -File -Filter '*.mp4' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
$info = if ($video) { Get-MediaInfo $video.FullName } else { $null }
$maxHeight = if ($info -and $info.Heights.Count) { ($info.Heights | Measure-Object -Maximum).Maximum } else { 0 }
$ok = ($r.Code -eq 0) -and $video -and $info.HasAudio -and $maxHeight -gt 0 -and $maxHeight -le 720
Add-Result '720p video with audio track' $ok ("exit=$($r.Code) height=$maxHeight audio=$($info.HasAudio)")

# --- 4. repeat the cut -> "already downloaded" ------------------------------
$r = Invoke-Yt @('-t', '0:30-1:00', '-q', '1080', '-o', $root, $Url)
$ok = ($r.Code -eq 3) -and ($r.Output -match 'Already downloaded')
Add-Result 'second run -> already downloaded (exit 3)' $ok ("exit=$($r.Code)")

# --- summary ----------------------------------------------------------------
Write-Host ''
$results | Format-Table -AutoSize
$failed = @($results | Where-Object { $_.State -ne 'OK' }).Count
Write-Host ''
if ($failed -eq 0) {
    Write-Host 'ACCEPTANCE TEST: all OK' -ForegroundColor Green
    Write-Host "Files in: $root"
    exit 0
}
Write-Host "ACCEPTANCE TEST: $failed test(s) failed" -ForegroundColor Red
exit 1
