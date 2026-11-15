#!/bin/sh
# Builds dist/redragon-rgb_<version>_all.deb from the source tree.
# Usage: packaging/build-deb.sh
set -eu
umask 022

SRC="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$SRC/redragon_rgb/__init__.py")"
[ -n "$VERSION" ] || { echo "cannot read __version__" >&2; exit 1; }
PKG=redragon-rgb
OUT="$SRC/dist"
ROOT="$(mktemp -d)"
chmod 755 "$ROOT"
trap 'rm -rf "$ROOT"' EXIT

# Python package (pure Python, no compiled files shipped)
install -d "$ROOT/usr/lib/python3/dist-packages/redragon_rgb"
install -m 644 "$SRC"/redragon_rgb/*.py "$ROOT/usr/lib/python3/dist-packages/redragon_rgb/"

# Launchers
install -d "$ROOT/usr/bin"
cat > "$ROOT/usr/bin/redragon-rgb" <<'EOF'
#!/usr/bin/python3
import sys
from redragon_rgb.gui import main
sys.exit(main())
EOF
cat > "$ROOT/usr/bin/redragon-rgb-cli" <<'EOF'
#!/usr/bin/python3
import sys
from redragon_rgb.cli import main
sys.exit(main())
EOF
chmod 755 "$ROOT/usr/bin/redragon-rgb" "$ROOT/usr/bin/redragon-rgb-cli"

# Desktop entry, udev rule, docs
install -D -m 644 "$SRC/data/io.github.codingkoala.RedragonRGB.desktop" \
    "$ROOT/usr/share/applications/io.github.codingkoala.RedragonRGB.desktop"
install -D -m 644 "$SRC/udev/70-redragon-rgb.rules" "$ROOT/usr/lib/udev/rules.d/70-redragon-rgb.rules"
install -D -m 644 "$SRC/README.md" "$ROOT/usr/share/doc/$PKG/README.md"
cat > "$ROOT/usr/share/doc/$PKG/copyright" <<EOF
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: $PKG
Source: https://github.com/codingkoala/redragon-rgb

Files: *
Copyright: 2026 codingkoala and contributors
License: GPL-3.0-or-later
 On Debian systems, the full text of the GNU General Public License
 version 3 can be found in /usr/share/common-licenses/GPL-3.
EOF

# Control files
install -d "$ROOT/DEBIAN"
SIZE="$(du -sk --exclude=DEBIAN "$ROOT" | cut -f1)"
cat > "$ROOT/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Installed-Size: $SIZE
Depends: python3 (>= 3.10), python3-gi, python3-gi-cairo, gir1.2-gtk-4.0, gir1.2-adw-1 (>= 1.6), libusb-1.0-0
Maintainer: codingkoala <908299+codingkoala@users.noreply.github.com>
Homepage: https://github.com/codingkoala/redragon-rgb
Description: RGB lighting control for Redragon M711 mice and K556 keyboards
 Native GTK4/libadwaita app and CLI to configure the RGB lighting of the
 Redragon M711 Cobra mouse (effects, DPI levels, report rate, profiles) and
 the Redragon K556 keyboard (18 effects and per-key colors) on Linux,
 without the vendor's Windows software. Includes the udev rule that gives
 the desktop user access to the devices.
EOF
cat > "$ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = configure ] && command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules || true
    udevadm trigger --subsystem-match=usb --subsystem-match=hidraw || true
fi
EOF
cat > "$ROOT/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = remove ] && command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules || true
fi
EOF
chmod 755 "$ROOT/DEBIAN/postinst" "$ROOT/DEBIAN/postrm"

mkdir -p "$OUT"
DEB="$OUT/${PKG}_${VERSION}_all.deb"
dpkg-deb --root-owner-group --build "$ROOT" "$DEB" >/dev/null
echo "$DEB"
