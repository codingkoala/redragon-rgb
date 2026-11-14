"""Command line interface: cobra-rgb-cli."""

from __future__ import annotations

import argparse
import sys

from .config import Settings, hex_to_rgb
from .device import BRIGHTNESS_RANGE, EFFECTS, SPEED_RANGE, CobraMouse, DeviceError, find_devices


def apply_settings(settings: Settings) -> None:
    with CobraMouse() as mouse:
        mouse.set_lighting(settings.effect, hex_to_rgb(settings.color), settings.speed, settings.brightness)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cobra-rgb-cli", description="Configura i LED del Redragon M711 Cobra")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="elenca i mouse rilevati")
    s = sub.add_parser("set", help="imposta effetto, colore, velocità e luminosità")
    s.add_argument("effect", choices=[e.key for e in EFFECTS])
    s.add_argument("-c", "--color", default="#ff1e3c", help="colore esadecimale, es. #00ff88")
    s.add_argument("-s", "--speed", type=int, default=4, help=f"velocità {SPEED_RANGE[0]}-{SPEED_RANGE[1]}")
    s.add_argument("-b", "--brightness", type=int, default=3, help=f"luminosità {BRIGHTNESS_RANGE[0]}-{BRIGHTNESS_RANGE[1]}")
    sub.add_parser("restore", help="riapplica le ultime impostazioni salvate")
    args = parser.parse_args(argv)

    try:
        if args.cmd == "list":
            devices = find_devices()
            for d in devices:
                print(f"{d.name}\t04d9:{d.product_id:04x}")
            return 0 if devices else 1
        if args.cmd == "set":
            settings = Settings(args.effect, "#" + args.color.lstrip("#"), args.speed, args.brightness)
            hex_to_rgb(settings.color)
            apply_settings(settings)
            settings.save()
        elif args.cmd == "restore":
            apply_settings(Settings.load())
    except (DeviceError, ValueError) as exc:
        print(f"errore: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
