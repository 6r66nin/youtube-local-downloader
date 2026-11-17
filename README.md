# yt — a small local YouTube downloader

A thin, readable CLI on top of [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) and
`ffmpeg`. Downloads go straight from your machine to YouTube: no external
service, no telemetry, no third‑party Python packages.

```
yt <url>                 best video + audio, merged to MP4
yt -q 1080 <url>         video up to 1080p
yt -a <url>              audio only (MP3 with tags and cover art)
yt -t 1:30-2:45 <url>    exact cut
yt update                update yt-dlp
```

Files are saved to your **Downloads** folder by default, directly in it (no
per‑channel subfolders unless you ask for them).

## Features

- **Video** up to any quality, video and audio merged into a single MP4.
- **Audio** as MP3 (tags + cover art) or M4A.
- **Exact cuts** with `-t START-END`, including open ends (`5:00-`) and
  "last 30 seconds" (`-0:30-`).
- **No duplicates**: downloads are recorded in an archive, per mode (video,
  audio, cut), so the same video can be fetched as video *and* as audio.
- **Friendly errors**: private, age‑restricted, geo‑blocked, 403/429, missing
  ffmpeg and network failures are explained with a next step.
- **Stable exit codes** for scripting.
- **Zero Python dependencies**: only the standard library (Python 3.11+).

## Requirements

| Tool | Why | Install |
|---|---|---|
| Python 3.11+ | runs `yt.py` (`tomllib`) | `winget install Python.Python.3.12` / `brew install python` |
| yt‑dlp | does the actual downloading | `winget install yt-dlp.yt-dlp -e` / `brew install yt-dlp` |
| ffmpeg | merging, MP3 conversion, cuts | `winget install Gyan.FFmpeg -e` / `brew install ffmpeg` |
| Node.js **or** Deno | solves YouTube's JavaScript challenge | usually already installed |

yt‑dlp only enables Deno by default. `yt` detects what you have and passes the
right `--js-runtimes` flag, so Node works too. Deno is only worth installing if
you have neither.

## Install

### Windows (PowerShell)

```powershell
git clone https://github.com/<you>/yt.git
cd yt

# 1) dependencies (yt-dlp, ffmpeg, and node/deno only if missing)
powershell -ExecutionPolicy Bypass -File .\setup-deps.ps1

# 2) the `yt` command itself (copies to C:\Tools\yt, adds it to your user PATH)
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Open a new terminal (winget does not refresh the PATH of the current session)
and check:

```powershell
yt --version
```

`setup-deps.ps1` falls back to `pip install --user yt-dlp` and a resumable
download of a static ffmpeg build when winget is slow or blocked.

### macOS / Linux

```sh
git clone https://github.com/<you>/yt.git
cd yt

# dependencies
brew install yt-dlp ffmpeg node        # macOS
# sudo apt install yt-dlp ffmpeg nodejs  # Debian/Ubuntu

./install.sh                           # installs into ~/.local
```

`install.sh` puts the program in `~/.local/share/yt` and a launcher in
`~/.local/bin`. Use `PREFIX=/usr/local ./install.sh` for a system‑wide copy.
You can also just run `./yt <url>` from the clone without installing.

## Usage

```sh
yt <url>                    # best video, MP4 (video+audio merged)
yt -q 1080 <url>            # cap the height: 2160, 1440, 1080, 720, 480, 360
yt -a <url>                 # audio only, MP3 (format from config.toml)
yt -a m4a <url>             # audio only, M4A
yt -t 1:30-2:45 <url>       # exact cut (start-end)
yt -t 5:00- <url>           # from 5:00 to the end
yt -t -0:30- <url>          # last 30 seconds
yt -o D:\Videos <url>       # different destination
yt -a -t 0:00-0:30 <url>    # combinations work: audio + cut
yt update                   # update yt-dlp
yt --version                # versions and dependency status
yt -h                       # help
```

Times accept `90`, `1:30` or `1:02:30`. Several URLs in one call are
downloaded one after another.

### Extra options

| Flag | Use |
|---|---|
| `--cookies-from-browser chrome` | when YouTube asks "confirm you're not a bot" or the video is age‑restricted |
| `--filename "<template>"` | override the output template for one run |
| `-o <dir>` | override `output_dir` for one run |

## Configuration

`config.toml` lives next to `yt.py` and is read on every run: edit and save, no
reinstall needed. `install.ps1` / `install.sh` create it from
`config.example.toml`.

```toml
output_dir = "~/Downloads"        # "~" expands to your home directory
default_quality = "best"          # best | 2160 | 1440 | 1080 | 720 | 480 | 360
audio_format = "mp3"              # what `yt -a` uses: mp3 | m4a
rate_limit = ""                   # e.g. "8M" to leave bandwidth for other things
filename = "%(upload_date>%Y-%m-%d)s - %(title).120B [%(id)s].%(ext)s"

# optional
# cookies_from_browser = "chrome"
# remote_components = "ejs:github"
```

To group files by channel, use a folder in the template:

```toml
filename = "%(uploader)s/%(upload_date>%Y-%m-%d)s - %(title).120B [%(id)s].%(ext)s"
```

`YT_CONFIG` and `YT_ARCHIVE` environment variables point `yt` at a different
config file and archive (the tests use this to stay out of your Downloads).

## Exit codes

| Code | Meaning |
|---|---|
| `0` | downloaded (or updated) successfully |
| `1` | unexpected error |
| `2` | missing dependency or incomplete environment |
| `3` | already downloaded (in the archive, or the file exists) |
| `4` | invalid arguments (quality, range, folder, audio format) |
| `5` | yt‑dlp failed (private, 403, geo‑blocked, network…) |
| `130` | cancelled with Ctrl+C |

```powershell
yt -q 720 $url; if ($LASTEXITCODE -eq 3) { "already had it" }
```

## How it behaves

Always applied: `--trim-filenames 150`, `--no-overwrites`, `--retries 10`,
`--newline`, `--no-playlist`, and `--windows-filenames` on Windows only.

Cuts use `--download-sections` with `--force-keyframes-at-cuts`, so the cut is
frame‑accurate (a partial re‑encode: slightly slower, but no black frames at the
start). The range is written into the filename (`[clip-30-60]`), which is also
what keeps repeated cuts from downloading twice.

Archives, one per mode, so one mode never blocks another:

| File | Prevents repeating |
|---|---|
| `.archive` | full video downloads |
| `.archive-audio` | audio of the same video |
| — | cuts: the range tag in the filename is enough |

## Troubleshooting

**`yt: command not found`** — the install folder is not on your PATH yet. Open a
new terminal; re‑run `install.ps1` if it still fails.

**"Requested format is not available" or only weird m3u8 formats** — YouTube's
JavaScript challenge was not solved. Make sure Node or Deno is on PATH, then
`yt update`. Setting `remote_components = ""` in `config.toml` disables the
solver and brings this problem back.

**"Sign in to confirm you're not a bot" / age‑restricted video** — use cookies
from a signed‑in browser: `yt --cookies-from-browser chrome <url>`.

**`yt update` says it cannot self‑update** — that is normal for winget/pip
installs. Use `winget upgrade --id yt-dlp.yt-dlp -e` or
`python -m pip install -U yt-dlp`.

**M4A download warns about cover art** — that build of ffmpeg needs
AtomicParsley for M4A thumbnails; `yt` retries automatically without the cover.
MP3 cover art always works.

**Slow network** — set `rate_limit` in `config.toml`, or leave it empty; yt‑dlp
resumes partial files and retries 10 times.

## Development

```sh
python -m unittest discover -s tests -v      # offline: parsing, tags, CLI
powershell -ExecutionPolicy Bypass -File tests/acceptance.ps1   # real downloads
```

The acceptance test needs network and the installed `yt` command; it uses a temp
folder with its own config and archive. CI runs the offline tests on Linux.

## Layout

| File | Purpose |
|---|---|
| `yt.py` | the CLI (standard library only) |
| `yt.cmd` / `yt` | Windows / POSIX launchers |
| `config.example.toml` | template for `config.toml` |
| `install.ps1` / `install.sh` | per‑user install + PATH |
| `setup-deps.ps1` | installs yt‑dlp, ffmpeg and a JS runtime if missing |
| `tests/` | offline unit tests and the acceptance test |

## License

MIT — see [LICENSE](LICENSE).

> Use it for content you are allowed to download. Redistributing other people's
> material can breach copyright and YouTube's terms of service. This project
> does not bypass DRM or paywalls.
