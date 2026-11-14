#!/bin/sh
# Per-user install: copies the app to ~/.local and adds a launcher + menu entry.
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.local/share/redragon-rgb"
BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
mkdir -p "$DEST" "$BIN" "$APPS"
rm -rf "$DEST/redragon_rgb"
cp -r "$SRC/redragon_rgb" "$DEST/"
cat > "$BIN/redragon-rgb" <<EOS
#!/bin/sh
PYTHONPATH="$DEST" exec /usr/bin/python3 -m redragon_rgb "\$@"
EOS
cat > "$BIN/redragon-rgb-cli" <<EOS
#!/bin/sh
PYTHONPATH="$DEST" exec /usr/bin/python3 -m redragon_rgb.cli "\$@"
EOS
chmod +x "$BIN/redragon-rgb" "$BIN/redragon-rgb-cli"
sed "s|^Exec=.*|Exec=$BIN/redragon-rgb|" "$SRC/data/io.github.codingkoala.RedragonRGB.desktop" > "$APPS/io.github.codingkoala.RedragonRGB.desktop"
echo "Installed. Start 'Redragon RGB' from the application menu or run: redragon-rgb"
