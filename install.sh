#!/bin/sh
# Installs the `yt` CLI for the current user (Linux, macOS, WSL, Git Bash).
# Usage:
#   ./install.sh                 # into ~/.local (bin + share/yt)
#   PREFIX=/usr/local ./install.sh
set -eu

PREFIX="${PREFIX:-$HOME/.local}"
DATA_DIR="$PREFIX/share/yt"
BIN_DIR="$PREFIX/bin"
HERE=$(cd "$(dirname "$0")" && pwd)

command -v python3 >/dev/null 2>&1 || {
    echo "python3 is required. Install it first (apt install python3 / brew install python)." >&2
    exit 1
}

mkdir -p "$DATA_DIR" "$BIN_DIR"
for f in yt.py README.md LICENSE config.example.toml; do
    [ -f "$HERE/$f" ] && cp "$HERE/$f" "$DATA_DIR/$f"
done

if [ -f "$DATA_DIR/config.toml" ]; then
    echo "  kept existing config.toml"
else
    cp "$DATA_DIR/config.example.toml" "$DATA_DIR/config.toml"
    echo "  created config.toml from config.example.toml"
fi

cat > "$BIN_DIR/yt" <<EOF
#!/bin/sh
exec python3 "$DATA_DIR/yt.py" "\$@"
EOF
chmod +x "$BIN_DIR/yt"

echo "  installed $BIN_DIR/yt"
echo
echo "Make sure $BIN_DIR is on your PATH, then check: yt --version"
