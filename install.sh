#!/bin/sh
# Per-user install: copies the app to ~/.local and adds a launcher + menu entry.
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.local/share/cobra-rgb"
BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
mkdir -p "$DEST" "$BIN" "$APPS"
rm -rf "$DEST/cobra_rgb"
cp -r "$SRC/cobra_rgb" "$DEST/"
cat > "$BIN/cobra-rgb" <<EOS
#!/bin/sh
PYTHONPATH="$DEST" exec /usr/bin/python3 -m cobra_rgb "\$@"
EOS
cat > "$BIN/cobra-rgb-cli" <<EOS
#!/bin/sh
PYTHONPATH="$DEST" exec /usr/bin/python3 -m cobra_rgb.cli "\$@"
EOS
chmod +x "$BIN/cobra-rgb" "$BIN/cobra-rgb-cli"
sed "s|^Exec=.*|Exec=$BIN/cobra-rgb|" "$SRC/data/io.github.codingkoala.CobraRGB.desktop" > "$APPS/io.github.codingkoala.CobraRGB.desktop"
echo "Installato. Avvia 'Cobra RGB' dal menu applicazioni oppure con: cobra-rgb"
