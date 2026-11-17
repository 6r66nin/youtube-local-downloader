#!/usr/bin/env python3
"""yt - a small, local YouTube downloader built on yt-dlp and ffmpeg.

Quick reference:
    yt <url>                 best video + audio merged to MP4
    yt -q 1080 <url>         video up to 1080p
    yt -a <url>              audio only (MP3, with tags and cover art)
    yt -a m4a <url>          audio only as M4A
    yt -t 1:30-2:45 <url>    exact cut
    yt -o D:\\Videos <url>    custom destination
    yt update                update yt-dlp

No third-party Python packages: only the standard library. Video traffic goes
straight from yt-dlp/ffmpeg to YouTube. The only remote extra is yt-dlp's own
JavaScript challenge solver (--remote-components ejs:github), fetched once and
cached on disk.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections import deque
from pathlib import Path

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

IS_WINDOWS = os.name == "nt"

SCRIPT_DIR = Path(__file__).resolve().parent
# YT_CONFIG / YT_ARCHIVE let you (or the tests) use a different state location.
CONFIG_PATH = Path(os.environ.get("YT_CONFIG") or SCRIPT_DIR / "config.toml")
ARCHIVE_PATH = Path(os.environ.get("YT_ARCHIVE") or SCRIPT_DIR / ".archive")

# Exit codes, stable so the CLI can be chained in scripts.
EXIT_OK = 0
EXIT_ERROR = 1        # unexpected error
EXIT_SETUP = 2        # missing dependency / environment not ready
EXIT_SKIPPED = 3      # already downloaded
EXIT_USAGE = 4        # bad arguments
EXIT_DOWNLOAD = 5     # yt-dlp failed

QUALITIES = ("best", "2160", "1440", "1080", "720", "480", "360")
AUDIO_FORMATS = ("mp3", "m4a")

DEFAULT_CONFIG = {
    # "~" is expanded, so the default works on every machine.
    "output_dir": "~/Downloads",
    "default_quality": "best",
    "audio_format": "mp3",
    "rate_limit": "",
    "filename": "%(upload_date>%Y-%m-%d)s - %(title).120B [%(id)s].%(ext)s",
    # Optional extras.
    "cookies_from_browser": "",
    # yt-dlp needs this solver to get real formats (not just m3u8) from YouTube.
    # Empty string disables it.
    "remote_components": "ejs:github",
}

# Frequent yt-dlp errors translated into actionable messages.
ERROR_HINTS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (
        ("private video", "this video is private"),
        "This video is private.",
        "Only the owner and invited viewers can watch it.",
    ),
    (
        ("sign in to confirm you", "confirm you’re not a bot", "confirm you're not a bot"),
        "YouTube wants to confirm you are not a bot.",
        "Run `yt update`; if it persists, use --cookies-from-browser chrome",
    ),
    (
        ("age-restricted", "confirm your age", "inappropriate for some users"),
        "This video is age-restricted.",
        "Use --cookies-from-browser <browser> with a signed-in account.",
    ),
    (
        ("not available in your country", "geo restricted", "geo-restricted",
         "blocked it in your country"),
        "This video is geo-blocked.",
        "You would need a VPN; the downloader cannot work around it.",
    ),
    (
        ("members-only", "join this channel", "available to this channel's members"),
        "This video is members-only.",
        "It needs cookies from an account subscribed to the channel.",
    ),
    (
        ("video unavailable", "has been removed", "does not exist",
         "is not available anymore", "removed by the uploader"),
        "The video is unavailable (removed, hidden, or wrong URL).",
        "Open the link in a browser to check.",
    ),
    (
        ("http error 403", "403 forbidden"),
        "YouTube returned 403 (temporary CDN block).",
        "Run `yt update`; if it persists, wait a few minutes or change network.",
    ),
    (
        ("http error 429", "too many requests"),
        "Too many requests to YouTube (429).",
        "Wait a few minutes, or set rate_limit in config.toml.",
    ),
    (
        ("requested format is not available", "no video formats found"),
        "That quality is not available for this video.",
        "Try `yt -q 720 <url>` or drop -q.",
    ),
    (
        ("unsupported url", "is not a valid url"),
        "The URL is not valid or not supported.",
        "youtube.com and youtu.be links work.",
    ),
    (
        ("unable to download webpage", "getaddrinfo", "timed out",
         "network is unreachable", "connection reset", "ssl"),
        "Network error while talking to YouTube.",
        "Check your connection, proxy or firewall.",
    ),
    (
        ("no space left", "not enough space", "disk full"),
        "Not enough disk space.",
        "Pick another folder with -o.",
    ),
    (
        ("ffmpeg", "ffprobe"),
        "Problem with ffmpeg (missing, or merging/converting failed).",
        "Install it: winget install --id Gyan.FFmpeg -e",
    ),
    (
        ("is live", "live event will begin", "premieres in"),
        "This is an ongoing live stream or a premiere.",
        "Live streams do not download well; wait until it ends.",
    ),
)

ALREADY_MARKERS = (
    "has already been recorded in the archive",
    "has already been downloaded",
)

# winget installs outside PATH; look there too (Windows only).
_WINGET_ROOT = Path(os.environ.get("LOCALAPPDATA", "") or ".")
WINGET_LINKS = _WINGET_ROOT / "Microsoft" / "WinGet" / "Links"
WINGET_PACKAGES = _WINGET_ROOT / "Microsoft" / "WinGet" / "Packages"


# --------------------------------------------------------------------------
# Console helpers
# --------------------------------------------------------------------------

def emit(text: str = "") -> None:
    """print() that survives titles with unencodable characters."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"))
    sys.stdout.flush()


def warn(text: str) -> None:
    emit(f"[warn] {text}")


def fail(text: str, hint: str = "") -> None:
    emit(f"[error] {text}")
    if hint:
        emit(f"        {hint}")


# --------------------------------------------------------------------------
# Tool discovery
# --------------------------------------------------------------------------

def find_tool(name: str) -> str | None:
    """Find an executable on PATH, then where winget put it.

    winget does not refresh the current session PATH, so a freshly installed
    yt-dlp/ffmpeg may be invisible until you open a new terminal.
    """
    found = shutil.which(name)
    if found:
        return found

    if IS_WINDOWS:
        for suffix in (".exe", ".cmd", ".bat"):
            candidate = WINGET_LINKS / f"{name}{suffix}"
            if candidate.is_file():
                return str(candidate)
        if WINGET_PACKAGES.is_dir():
            # e.g. Packages\yt-dlp.FFmpeg_x\ffmpeg-N-...\bin\ffmpeg.exe
            for pattern in (f"*/{name}.exe", f"*/bin/{name}.exe", f"*/*/bin/{name}.exe"):
                for match in WINGET_PACKAGES.glob(pattern):
                    return str(match)
    return None


# --------------------------------------------------------------------------
# Time and ranges
# --------------------------------------------------------------------------

def parse_time(text: str) -> int:
    """'90' | '1:30' | '1:02:30' -> seconds. Raises ValueError."""
    parts = text.strip().split(":")
    if not parts or len(parts) > 3 or any(not p.isdigit() for p in parts):
        raise ValueError(text)
    values = [int(p) for p in parts]
    if any(v >= 60 for v in values[1:]):
        raise ValueError(text)
    total = 0
    for value in values:
        total = total * 60 + value
    return total


def format_time(seconds: int) -> str:
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def parse_range(text: str) -> tuple[str, str]:
    """'1:30-2:45' | '5:00-' | '-0:30-' -> (start, end) normalised.

    An open end becomes 'inf'. A negative start stays relative (yt-dlp reads it
    as "from the end of the video").
    """
    match = re.match(r"^(-?\d+(?::\d+){0,2})?-(.*)$", text.strip())
    if not match:
        raise ValueError(
            f"invalid range: {text!r} (expected start-end, e.g. 1:30-2:45)"
        )

    raw_start = match.group(1) or "0"
    raw_end = match.group(2).strip() or "inf"

    negative = raw_start.startswith("-")
    try:
        start_seconds = parse_time(raw_start.lstrip("-"))
    except ValueError:
        raise ValueError(f"invalid range start: {raw_start!r}") from None

    if raw_end == "inf":
        end_seconds = None
        end_norm = "inf"
    else:
        try:
            end_seconds = parse_time(raw_end)
        except ValueError:
            raise ValueError(f"invalid range end: {raw_end!r}") from None
        end_norm = format_time(end_seconds)

    if not negative:
        if end_seconds is not None and end_seconds <= start_seconds:
            raise ValueError(
                f"inverted or empty range: {format_time(start_seconds)}-{end_norm} "
                "(the end must be greater than the start)"
            )

    start_norm = ("-" if negative else "") + format_time(start_seconds)
    return start_norm, end_norm


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

def load_config() -> dict:
    config = dict(DEFAULT_CONFIG)
    if not CONFIG_PATH.is_file():
        return config
    try:
        with CONFIG_PATH.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        warn(f"could not read {CONFIG_PATH.name} ({exc}); using defaults")
        return config

    for key, value in data.items():
        if key in DEFAULT_CONFIG:
            config[key] = value
        else:
            warn(f"config.toml: unknown key {key!r} (ignored)")
    return config


def resolve_output_dir(value: str) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(str(value).strip()))
    path = Path(expanded)
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"cannot create folder {path}: {exc}") from None
    return path


# --------------------------------------------------------------------------
# Command building
# --------------------------------------------------------------------------

def js_runtime_flags(has_deno: bool, has_node: bool) -> list[str]:
    """yt-dlp only enables deno by default: name the runtime we do have."""
    if has_deno:
        return ["--js-runtimes", "deno"]
    if has_node:
        return ["--js-runtimes", "node"]
    return []


def video_format(quality: str) -> str:
    if quality == "best":
        return "bv*+ba/b"
    return f"bv*[height<={quality}]+ba/b[height<={quality}]"


def clip_tag(start: str, end: str) -> str:
    """Filesystem-safe tag for a cut: 0:30-1:00 -> clip-30-60."""

    def part(token: str, is_end: bool) -> str:
        if is_end and token == "inf":
            return "end"
        negative = token.startswith("-")
        seconds = parse_time(token.lstrip("-"))
        return f"r{seconds}" if negative else str(seconds)

    return f"clip-{part(start, False)}-{part(end, True)}"


def add_clip_tag(template: str, tag: str) -> str:
    """Insert the clip tag before the extension in the output template."""
    marker = ".%(ext)s"
    if marker in template:
        return template.replace(marker, f" [{tag}]{marker}", 1)
    return f"{template} [{tag}]"


def run_update(yt_dlp: str) -> int:
    emit("Updating yt-dlp...")
    code, tail = stream([yt_dlp, "-U"], echo=True)
    if code == 0:
        emit("yt-dlp is up to date.")
        return EXIT_OK

    blob = "\n".join(tail).lower()
    if any(word in blob for word in ("winget", "pip", "permission", "administrator")):
        fail("yt-dlp cannot self-update (installed with winget or pip).")
        emit("        winget upgrade --id yt-dlp.yt-dlp -e")
        emit("        (or, with pip: python -m pip install -U yt-dlp)")
        return EXIT_SETUP
    fail("update failed.")
    return EXIT_DOWNLOAD


def stream(cmd: list[str], echo: bool = True) -> tuple[int, list[str]]:
    """Run cmd, showing its output line by line. Returns (code, tail)."""
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
    except FileNotFoundError:
        fail(f"executable not found: {cmd[0]}")
        return 127, []

    tail: deque[str] = deque(maxlen=120)
    assert proc.stdout is not None
    try:
        for raw in proc.stdout:
            line = raw.rstrip("\r\n")
            tail.append(line)
            if echo and line:
                emit(line)
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        emit("")
        warn("cancelled by user")
        return 130, list(tail)
    return proc.returncode, list(tail)


# --------------------------------------------------------------------------
# Downloading
# --------------------------------------------------------------------------

def explain_failure(tail: list[str]) -> None:
    blob = "\n".join(tail).lower()
    for needles, message, hint in ERROR_HINTS:
        if any(needle in blob for needle in needles):
            fail(message, hint)
            return
    fail("yt-dlp failed; see the output above.")


def final_path_from(tail: list[str]) -> str | None:
    """Last final file path seen in yt-dlp output."""
    last = None
    for line in tail:
        match = re.search(r'Merging formats into "(.+)"$', line)
        if not match:
            match = re.search(r"\[ExtractAudio\] Destination: (.+)$", line)
        if not match:
            match = re.search(r"\[download\] Destination: (.+)$", line)
        if match:
            last = match.group(1).strip().strip('"')
    return last


def download_one(url: str, opts: argparse.Namespace, config: dict) -> int:
    # --- 1. validate arguments (before looking at dependencies) ----------
    audio_format = None
    if opts.audio is not None:
        # `-a` without a value uses audio_format from config.toml (mp3).
        audio_format = (opts.audio or str(config.get("audio_format") or "mp3")).lower()
        if audio_format not in AUDIO_FORMATS:
            fail(f"unsupported audio format: {audio_format}")
            emit(f"        use one of: {', '.join(AUDIO_FORMATS)}")
            return EXIT_USAGE

    quality = str(opts.quality or config["default_quality"]).lower()
    if quality not in QUALITIES:
        fail(f"invalid quality: {quality}")
        emit(f"        use one of: {', '.join(QUALITIES)}")
        return EXIT_USAGE

    section = None
    if opts.trim:
        try:
            start, end = parse_range(opts.trim)
        except ValueError as exc:
            fail(str(exc))
            return EXIT_USAGE
        section = f"*{start}-{end}"

    try:
        output_dir = resolve_output_dir(opts.output or config["output_dir"])
    except ValueError as exc:
        fail(str(exc))
        return EXIT_USAGE

    # --- 2. dependencies --------------------------------------------------
    yt_dlp = find_tool("yt-dlp")
    if not yt_dlp:
        fail("yt-dlp is not installed (or not on PATH).")
        emit("        winget install --id yt-dlp.yt-dlp -e --accept-package-agreements")
        emit("        (then open a new terminal so PATH refreshes)")
        return EXIT_SETUP

    ffmpeg = find_tool("ffmpeg")
    has_deno = find_tool("deno") is not None
    has_node = find_tool("node") is not None

    # --- 3. check ffmpeg BEFORE downloading -------------------------------
    if not ffmpeg:
        if audio_format:
            fail("ffmpeg is missing; audio extraction/conversion needs it.")
            emit("        winget install --id Gyan.FFmpeg -e --accept-package-agreements")
            return EXIT_SETUP
        if quality == "best" or int(quality) >= 1080:
            fail(
                "ffmpeg is missing: without it I cannot merge video+audio "
                "or go above 720p."
            )
            emit("        winget install --id Gyan.FFmpeg -e --accept-package-agreements")
            emit("        (or ask for a lower quality: yt -q 720 <url>)")
            return EXIT_SETUP
        warn(
            f"ffmpeg is not installed: downloading a single file up to {quality}p "
            "(no track merging)."
        )

    # --- command ----------------------------------------------------------
    template = str(opts.filename or config["filename"])
    if section:
        template = add_clip_tag(template, clip_tag(start, end))

    # One archive per mode: the same video may be downloaded as video, as audio
    # or cut, without one blocking the other. Cuts use no archive at all: the
    # range in the filename already prevents duplicates.
    if section:
        archive = None
    elif audio_format:
        archive = ARCHIVE_PATH.with_name(".archive-audio")
    else:
        archive = ARCHIVE_PATH

    cmd = [yt_dlp]

    cmd += [
        "--trim-filenames", "150",
        "--no-overwrites",
        "--retries", "10",
        "--newline",
        "--no-playlist",
        "--encoding", "utf-8",
        "-P", f"home:{output_dir}",
        "-o", template,
    ]
    if IS_WINDOWS:
        cmd += ["--windows-filenames"]
    if archive:
        cmd += ["--download-archive", str(archive)]

    rate = str(config.get("rate_limit") or "").strip()
    if rate:
        cmd += ["--limit-rate", rate]

    cookies = (opts.cookies_from_browser or config.get("cookies_from_browser") or "").strip()
    if cookies:
        cmd += ["--cookies-from-browser", cookies]

    cmd += js_runtime_flags(has_deno, has_node)

    components = str(config.get("remote_components") or "").strip()
    if components and (has_deno or has_node):
        cmd += ["--remote-components", components]

    if section:
        cmd += ["--download-sections", section, "--force-keyframes-at-cuts"]

    if audio_format:
        cmd += [
            "-f", "ba/b",
            "-x",
            "--audio-format", audio_format,
            "--audio-quality", "0",
            "--embed-metadata",
            "--embed-thumbnail",
        ]
    elif ffmpeg:
        cmd += ["-f", video_format(quality), "--merge-output-format", "mp4"]
    else:
        cmd += ["-f", f"b[height<={quality}]/b"]

    cmd.append(url)

    # --- header + run -----------------------------------------------------
    emit("")
    mode = (
        f"audio {audio_format.upper()}"
        if audio_format
        else ("video (best)" if quality == "best" else f"video {quality}p")
    )
    emit(f">> {mode} - {url}")
    emit(f"   destination: {output_dir}")
    if section:
        emit(f"   clip: {section.lstrip('*')}")
    if not has_deno and not has_node:
        warn(
            "no JavaScript runtime (deno/node): YouTube may refuse high qualities. "
            "Install deno: winget install DenoLand.Deno"
        )
    emit("")

    code, tail = stream(cmd)
    blob = "\n".join(tail).lower()

    if code == 0:
        if any(marker in blob for marker in ALREADY_MARKERS):
            emit("")
            emit("= Already downloaded: file exists (or is in the archive), skipping.")
            return EXIT_SKIPPED
        path = final_path_from(tail)
        emit("")
        emit(f"= Done{f': {path}' if path else '.'}")
        return EXIT_OK

    if code == 130:
        return 130

    # Cover art in M4A can fail without AtomicParsley: retry without it.
    if audio_format == "m4a" and (
        "atomicparsley" in blob or "embedding thumbnail" in blob or "thumbnail" in blob
    ):
        warn("could not embed the cover art in M4A; retrying without it.")
        drop = {"--embed-thumbnail", "--no-overwrites"}
        retry = [arg for arg in cmd if arg not in drop]
        # The failed attempt may have left an entry in the archive: force.
        retry += ["--no-download-archive", "--force-overwrites"]
        code, tail = stream(retry)
        if code == 0:
            emit("")
            emit("= Done (M4A audio, without cover art).")
            return EXIT_OK

    emit("")
    explain_failure(tail)
    return EXIT_DOWNLOAD


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt",
        description="Local YouTube downloader (yt-dlp + ffmpeg).",
        epilog=(
            "examples:  yt <url>   |   yt -q 1080 <url>   |   yt -a <url>   |   "
            "yt -t 1:30-2:45 <url>   |   yt update"
        ),
        add_help=True,
    )
    parser.add_argument("urls", nargs="*", help="YouTube URL(s)")
    parser.add_argument(
        "-q", "--quality",
        metavar="Q",
        help=f"max video quality: {', '.join(QUALITIES)}",
    )
    parser.add_argument(
        "-a", "--audio",
        nargs="?", const="", metavar="FMT",
        help="audio only: mp3 (default, or audio_format from config.toml) or m4a",
    )
    parser.add_argument(
        "-t", "--trim",
        metavar="START-END",
        help="cut, e.g. 1:30-2:45, 5:00- or -0:30- (last 30 seconds)",
    )
    parser.add_argument(
        "-o", "--output",
        metavar="DIR",
        help="destination folder (default: the one in config.toml)",
    )
    parser.add_argument(
        "--filename", metavar="TEMPLATE",
        help="yt-dlp output template override",
    )
    parser.add_argument(
        "--cookies-from-browser", metavar="BROWSER",
        help="use cookies from a browser (chrome, firefox, edge...)",
    )
    parser.add_argument(
        "--version", action="store_true",
        help="show this script and dependency versions",
    )
    return parser


def show_versions() -> int:
    emit("yt 1.0 (local CLI on top of yt-dlp)")
    yt_dlp = find_tool("yt-dlp")
    ok = True

    if yt_dlp:
        stream([yt_dlp, "--version"], echo=True)
    else:
        ok = False
        emit("yt-dlp:   NOT INSTALLED -> winget install --id yt-dlp.yt-dlp -e")

    ffmpeg = find_tool("ffmpeg")
    if not ffmpeg:
        ok = False
    emit(f"ffmpeg:   {'OK  ' + ffmpeg if ffmpeg else 'NOT INSTALLED (no merging or MP3)'}")

    js = "deno" if find_tool("deno") else ("node" if find_tool("node") else None)
    emit(f"runtime:  {js if js else 'none (high qualities may fail)'}")

    return EXIT_OK if ok else EXIT_SETUP


def main(argv: list[str]) -> int:
    for stream_obj in (sys.stdout, sys.stderr):
        try:
            stream_obj.reconfigure(errors="replace")
        except (AttributeError, OSError):
            pass

    if argv and argv[0].lower() in ("update", "--update", "-u"):
        yt_dlp = find_tool("yt-dlp")
        if not yt_dlp:
            fail("yt-dlp is not installed (or not on PATH).")
            emit("        winget install --id yt-dlp.yt-dlp -e --accept-package-agreements")
            return EXIT_SETUP
        return run_update(yt_dlp)

    parser = build_parser()
    opts = parser.parse_args(argv)

    if opts.version:
        return show_versions()

    # `yt -a <url>`: argparse takes the URL as the value of -a.
    if opts.audio is not None and opts.audio and opts.audio.lower() not in AUDIO_FORMATS:
        if not opts.urls:
            opts.urls = [opts.audio]
            opts.audio = ""
        else:
            fail(f"unsupported audio format: {opts.audio}")
            emit(f"        use one of: {', '.join(AUDIO_FORMATS)}")
            return EXIT_USAGE

    if not opts.urls:
        parser.print_help()
        return EXIT_USAGE

    config = load_config()

    exit_code = EXIT_OK
    for index, url in enumerate(opts.urls):
        if index:
            emit("")
        code = download_one(url, opts, config)
        if code != EXIT_OK:
            exit_code = code
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        emit("")
        sys.exit(130)
