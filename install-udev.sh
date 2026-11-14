#!/bin/sh
# Installs the udev rule that gives the desktop user access to mouse and keyboard.
set -e
if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo $0" >&2
    exit 1
fi
rm -f /etc/udev/rules.d/70-redragon-m711.rules
install -m 644 "$(dirname "$0")/udev/70-redragon-rgb.rules" /etc/udev/rules.d/
udevadm control --reload-rules
udevadm trigger --subsystem-match=usb --subsystem-match=hidraw
echo "udev rule installed. If it does not work right away, unplug and replug mouse and keyboard."
