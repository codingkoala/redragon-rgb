#!/bin/sh
# Installs the udev rule that gives the desktop user access to the mouse.
set -e
if [ "$(id -u)" -ne 0 ]; then
    echo "Esegui con sudo: sudo $0" >&2
    exit 1
fi
install -m 644 "$(dirname "$0")/udev/70-redragon-m711.rules" /etc/udev/rules.d/
udevadm control --reload-rules
udevadm trigger --subsystem-match=usb --attr-match=idVendor=04d9
echo "Regola udev installata. Se non funziona subito, scollega e ricollega il mouse."
