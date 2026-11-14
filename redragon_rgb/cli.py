"""Command line interface: redragon-rgb-cli."""

from __future__ import annotations

import argparse
import sys

from . import config
from .backends import BACKENDS, BackendError
from .config import Settings, hex_to_rgb
from .keyboard import KEYS, KEYS_BY_NAME, KeyboardError, RedragonKeyboard


def _add_set_parser(sub, key: str) -> None:
    b = BACKENDS[key]
    p = sub.add_parser(key, help=f"set the {b.title.lower()} lighting")
    p.add_argument("effect", choices=[e.key for e in b.effects])
    p.add_argument("-c", "--color", default="#ff1e3c", help="hex color, e.g. #00ff88")
    lo, hi = b.speed_range
    p.add_argument("-s", "--speed", type=int, default=(lo + hi) // 2, help=f"speed {lo}-{hi}")
    lo, hi = b.brightness_range
    p.add_argument("-b", "--brightness", type=int, default=hi, help=f"brightness {lo}-{hi}")
    if key == "keyboard":
        p.add_argument("-d", "--direction", choices=["left", "right", "up", "down"], default="left")
        p.add_argument("-m", "--multicolor", action="store_true", help="random / rainbow colors")
        p.add_argument("--fill", metavar="HEX", help="custom: paint every key with this color")
        p.add_argument("--key", metavar="NAME=HEX", action="append", default=[],
                       help="custom: paint one key, e.g. --key w=ff0000 (repeatable; see list-keys)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="redragon-rgb-cli",
                                     description="Configure the RGB lighting of Redragon M711 mice and K556 keyboards")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list detected devices")
    _add_set_parser(sub, "mouse")
    _add_set_parser(sub, "keyboard")
    sub.add_parser("list-keys", help="list the key names usable with --key")
    sub.add_parser("restore", help="re-apply the last saved settings to every device")
    probe = sub.add_parser("probe-keyboard", help="diagnostics: send a raw mode code (0-20)")
    probe.add_argument("code", type=lambda v: int(v, 0))
    probe.add_argument("--dir", type=lambda v: int(v, 0), default=0, help="raw direction code (0-5)")
    args = parser.parse_args(argv)

    try:
        if args.cmd == "list":
            found = False
            for b in BACKENDS.values():
                name = b.detect()
                print(f"{b.title}:\t{name or 'not found'}")
                found |= name is not None
            return 0 if found else 1
        if args.cmd in BACKENDS:
            s = Settings(args.effect, "#" + args.color.lstrip("#"), args.speed, args.brightness,
                         getattr(args, "direction", "left"), getattr(args, "multicolor", False))
            hex_to_rgb(s.color)
            if args.cmd == "keyboard" and args.effect == "custom":
                s.keys = {} if args.fill else dict(config.load("keyboard").keys)
                if args.fill:
                    s.keys = {k.name: "#" + args.fill.lstrip("#") for k in KEYS}
                for item in args.key:
                    name, _, color = item.partition("=")
                    if name not in KEYS_BY_NAME:
                        raise ValueError(f"unknown key '{name}' (see list-keys)")
                    s.keys[name] = "#" + color.lstrip("#")
                for color in s.keys.values():
                    hex_to_rgb(color)
            BACKENDS[args.cmd].apply(s)
            config.save(args.cmd, s)
        elif args.cmd == "list-keys":
            print(" ".join(k.name for k in KEYS))
        elif args.cmd == "restore":
            rc = 0
            for key, b in BACKENDS.items():
                if b.detect():
                    try:
                        b.apply(config.load(key))
                    except BackendError as exc:
                        print(f"error ({b.title}): {exc}", file=sys.stderr)
                        rc = 1
            return rc
        elif args.cmd == "probe-keyboard":
            if not 0 <= args.code <= 0x14:
                raise ValueError("code out of range (0x00-0x14)")
            with RedragonKeyboard() as k:
                if not 0 <= args.dir <= 5:
                    raise ValueError("direction code out of range (0-5)")
                k.send_raw_mode(args.code, direction=args.dir)
    except (BackendError, KeyboardError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
