# Redragon RGB

Configure the RGB lighting of the **Redragon M711 Cobra** mouse and the **Redragon K556**
keyboard on Linux — a native GTK4 / libadwaita app for GNOME plus a CLI for scripting.
No vendor software, no Windows, no pip dependencies.

| Device | USB ID | Status |
|---|---|---|
| M711 Cobra | `04d9:fc30` | tested |
| M711-FPS-1 Cobra FPS | `04d9:fc62` | untested |
| K556 (EVision controller) | `320f:5000` | tested (static); other effects being verified |
| K556 (SONiX controller) | `0c45:5004` | untested |

## Features

- One tab per device (Mouse / Keyboard) with an animated preview of the effect
- **Mouse:** static, breathing, flashing, rainbow, rainbow breathing, wave, reactive, off
- **Keyboard:** static, breathing, wave, vertical rainbow, rainbow circle, hurricane, accumulate,
  starlight (fast/slow), visor, ripple, reactive line, off — single color or multicolor, with direction
- Color picker with quick presets, speed and brightness sliders; colors are gamma-corrected so
  the LEDs match what you see on screen
- Optional live apply; the last settings of each device are remembered
- Settings are stored in the devices' own memory (all 5 mouse profiles), so they persist across
  reboots and on other computers

## Requirements

Ubuntu 24.04+ or any distribution with GTK 4 and libadwaita ≥ 1.5:

```sh
sudo apt install python3-gi gir1.2-adw-1 libusb-1.0-0
```

## Installation

```sh
git clone https://github.com/codingkoala/redragon-rgb.git
cd redragon-rgb
sudo ./install-udev.sh   # once: USB/hidraw access for the desktop user
./install.sh             # launcher in ~/.local/bin + application menu entry
```

Unplug and replug the devices after installing the udev rule. To try it without installing:
`python3 -m redragon_rgb`.

## CLI

```sh
redragon-rgb-cli list
redragon-rgb-cli mouse static -c "#00e5ff" -b 3
redragon-rgb-cli mouse breathing -c ff1e3c -s 5
redragon-rgb-cli keyboard wave -m -s 4 -d right
redragon-rgb-cli keyboard static -c 2f6bff -b 4
redragon-rgb-cli keyboard off
redragon-rgb-cli restore        # re-apply the last saved settings to every device
```

## How it works

### M711 mouse

The mouse is driven with USB control transfers (HID `SET_REPORT`, report `0x02`) on vendor
interface 2, through libusb loaded with `ctypes`. hidraw cannot be used because the mouse's report
descriptor declares no feature reports.

| Frame | Meaning |
|---|---|
| `02 F5 00` | unlock (starts every sequence) |
| `02 F3 <addr> <len> 00 00 00 <data>` | write |
| `02 F1 02 04` | apply |
| `02 F5 01` | lock (ends every sequence — mandatory) |

LED of profile *n* (0–4): `0x0449 + 8n` → `R, G, B, mode1, speed, mode2`; brightness:
`0x044F + 8n`. Color and mode are always written together: writing only the color while a
color-less effect is active freezes the LED animation.

Protocol knowledge comes from [dokutan/mouse_m908](https://github.com/dokutan/mouse_m908),
[OpenRGB](https://gitlab.com/CalcProgrammer1/OpenRGB) and
[SK2674/m711-port](https://github.com/SK2674/m711-port), which measured the transport and the
firmware pitfalls on real hardware.

### K556 keyboard

64-byte HID output reports (report `0x04`) on the vendor interface (usage page `0xFF1C`) via
hidraw, with a checksum of bytes 3–63; the keyboard acknowledges every packet. Each command is
wrapped in `begin` (`0x01`) / `end` (`0x02`); parameter 0 sets mode, brightness (0–4),
speed (5 slow → 0 fast), direction, multicolor flag and RGB.

Mode codes differ between firmware revisions. Only the codes on which OpenRGB's EVision driver
and the hardware-probed controller from
[syndicalt/openrgb-reddragonk556-controller](https://github.com/syndicalt/openrgb-reddragonk556-controller)
agree are exposed. To map the others on your keyboard: `redragon-rgb-cli probe-keyboard 0x04`.

## Roadmap

- [x] K556 keyboard (effects)
- [ ] K556 per-key colors
- [ ] Read the current state back from the mouse
- [ ] Per-profile settings and DPI

## License

GPL-3.0-or-later
