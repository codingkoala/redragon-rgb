#!/bin/sh
# Installs the udev rule that gives the desktop user access to mouse and keyboard.
set -e
if [ "$(id -u)" -ne 0 ]; then
    echo "Esegui con sudo: sudo $0" >&2
    exit 1
fi
rm -f /etc/udev/rules.d/70-redragon-m711.rules
install -m 644 "$(dirname "$0")/udev/70-redragon-rgb.rules" /etc/udev/rules.d/
udevadm control --reload-rules
udevadm trigger --subsystem-match=usb --subsystem-match=hidraw
echo "Regola udev installata. Se non funziona subito, scollega e ricollega mouse e tastiera."
