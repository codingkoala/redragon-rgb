"""Command line interface: redragon-rgb-cli."""

from __future__ import annotations

import argparse
import sys

from . import config
from .backends import BACKENDS, BackendError, screen_hex
from . import device as mouse_drv
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


def _print_state(state) -> None:
    for i, p in enumerate(state.profiles):
        mark = "*" if i == state.active_profile else " "
        levels = "  ".join(f"{lv.dpi:>5}{'' if lv.enabled else '(off)'}" for lv in p.levels)
        poll = f"{p.poll_rate} Hz" if p.poll_rate else "?"
        print(f"{mark} profile {i + 1}: {levels}   report rate {poll}")


def _mouse_dpi(args) -> int:
    with mouse_drv.CobraMouse() as m:
        state = m.read_state()
        if not (args.levels or args.enabled or args.poll):
            _print_state(state)
            return 0
        idx = state.active_profile if args.profile is None else args.profile - 1
        if not 0 <= idx < mouse_drv.PROFILES:
            raise ValueError("profile must be 1-5")
        levels = [mouse_drv.DpiLevel(lv.enabled, lv.dpi) for lv in state.profiles[idx].levels]
        if args.levels:
            values = [int(v) for v in args.levels.split(",")]
            if len(values) != mouse_drv.DPI_LEVELS:
                raise ValueError("--levels needs exactly 5 values")
            for lv, v in zip(levels, values):
                lv.dpi = v
        if args.enabled:
            flags = [v.strip() not in ("0", "") for v in args.enabled.split(",")]
            if len(flags) != mouse_drv.DPI_LEVELS:
                raise ValueError("--enabled needs exactly 5 values")
            for lv, f in zip(levels, flags):
                lv.enabled = f
        for lv in levels:
            q = mouse_drv.quantize_dpi(lv.dpi)
            if q != lv.dpi:
                print(f"note: {lv.dpi} DPI is stored as {q} (firmware steps of ~44)", file=sys.stderr)
        m.write_profile(idx, levels, args.poll)
        after = m.read_state()
    _print_state(after)
    wanted = [(lv.enabled, mouse_drv.quantize_dpi(lv.dpi)) for lv in levels]
    got = [(lv.enabled, lv.dpi) for lv in after.profiles[idx].levels]
    if wanted != got or (args.poll and after.profiles[idx].poll_rate != args.poll):
        print("error: read-back does not match what was written", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="redragon-rgb-cli",
                                     description="Configure the RGB lighting of Redragon M711 mice and K556 keyboards")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list detected devices")
    _add_set_parser(sub, "mouse")
    _add_set_parser(sub, "keyboard")
    dpi = sub.add_parser("mouse-dpi", help="show, or set, the DPI levels and report rate of a mouse profile")
    dpi.add_argument("--profile", type=int, help="profile to change (1-5); default: the active one")
    dpi.add_argument("--levels", help="five DPI values, e.g. 400,800,1600,3200,6400")
    dpi.add_argument("--enabled", help="which levels the DPI button cycles through, e.g. 1,1,1,1,0")
    dpi.add_argument("--poll", type=int, choices=sorted(mouse_drv.POLL_CODES), help="report rate in Hz")
    prof = sub.add_parser("mouse-profile", help="switch the active mouse profile")
    prof.add_argument("profile", type=int, choices=range(1, mouse_drv.PROFILES + 1))
    sub.add_parser("status", help="show the lighting and DPI currently stored in the mouse")
    wb = sub.add_parser("white-balance", help="show or set the per-channel LED gains of a device")
    wb.add_argument("device", choices=list(BACKENDS))
    wb.add_argument("gains", nargs="*", type=int, metavar="PERCENT",
                    help="red green blue in percent (30-100), e.g. 90 100 85; 'reset' = 100 100 100")
    wb.add_argument("--reset", action="store_true", help="back to 100 100 100")
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
        elif args.cmd == "white-balance":
            if args.reset:
                config.save_balance(args.device, config.NEUTRAL)
            elif args.gains:
                if len(args.gains) != 3 or not all(30 <= g <= 100 for g in args.gains):
                    raise ValueError("give three values between 30 and 100 (red green blue)")
                config.save_balance(args.device, tuple(g / 100 for g in args.gains))
            gains = config.load_balance(args.device)
            print(f"{args.device}: red {gains[0]:.0%}  green {gains[1]:.0%}  blue {gains[2]:.0%}")
            if args.reset or args.gains:
                print("re-apply the lighting (or run `restore`) to see the change")
        elif args.cmd == "status":
            with mouse_drv.CobraMouse() as m:
                lit = m.read_lighting()
                state = m.read_state()
            wb = config.load_balance("mouse")
            print(f"lighting: {lit.effect or 'unknown mode'}  color {screen_hex(lit.color, wb)}"
                  f" (LED levels #{bytes(lit.color).hex()})"
                  f"  speed {lit.speed}  brightness {lit.brightness}")
            _print_state(state)
        elif args.cmd == "mouse-dpi":
            return _mouse_dpi(args)
        elif args.cmd == "mouse-profile":
            with mouse_drv.CobraMouse() as m:
                m.set_active_profile(args.profile - 1)
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
    except (BackendError, KeyboardError, mouse_drv.DeviceError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
