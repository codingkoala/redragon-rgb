"""GTK4 / libadwaita user interface."""

from __future__ import annotations

import colorsys
import math
import sys
import threading

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import __version__, config  # noqa: E402
from . import device as mouse_drv  # noqa: E402
from .backends import BACKENDS, MOUSE_LOCK, Backend, BackendError  # noqa: E402
from .config import Settings, hex_to_rgb, rgb_to_hex  # noqa: E402
from .effects import DIRECTIONS  # noqa: E402
from .keyboard import KEYS as KB_KEYS  # noqa: E402

APP_ID = "io.github.codingkoala.RedragonRGB"
PRESETS = ["#ff1e3c", "#ff7a00", "#ffd000", "#3cff6e", "#00e5ff", "#2f6bff", "#9b4dff", "#ff3df2", "#ffffff"]

CSS = """
.preview-card {
  border-radius: 24px;
  background: radial-gradient(circle at 50% 40%, #23252d 0%, #121318 70%);
}
.swatch {
  min-width: 30px; min-height: 30px;
  padding: 0; border-radius: 999px;
  border: 2px solid alpha(white, 0.15);
  box-shadow: none;
}
.swatch:hover { border-color: alpha(white, 0.6); }
.effect-title { font-weight: 800; font-size: 20pt; color: white; }
.effect-sub { color: alpha(white, 0.6); }
"""


def _hsv(h, s=1.0, v=1.0):
    return colorsys.hsv_to_rgb(h % 1.0, s, v)


def _hash(*vals) -> float:
    """Cheap deterministic pseudo-random number in [0, 1)."""
    x = math.sin(sum(v * k for v, k in zip(vals, (12.9898, 78.233, 37.719)))) * 43758.5453
    return x - math.floor(x)


# --- previews ----------------------------------------------------------------
class Preview(Gtk.DrawingArea):
    """Animated preview. Subclasses implement draw_scene()."""

    def __init__(self):
        super().__init__(hexpand=True, vexpand=True)
        self.s = Settings()
        self._now = 0.0
        self._start = None
        self.last_hit = -10.0
        self.hit_pos = (0.5, 0.5)
        self.set_draw_func(self._draw)
        self.add_tick_callback(self._tick)
        click = Gtk.GestureClick()
        click.connect("pressed", self._on_click)
        self.add_controller(click)

    @property
    def t(self):
        return self._now - (self._start or self._now)

    @property
    def bright(self):
        return 1.0

    def _on_click(self, _g, _n, x, y):
        self.last_hit = self.t
        w, h = self.get_width(), self.get_height()
        self.hit_pos = (x / max(w, 1), y / max(h, 1))

    def _tick(self, _w, clock):
        self._now = clock.get_frame_time() / 1e6
        if self._start is None:
            self._start = self._now
        if self.t - self.last_hit > 2.2:  # simulate key presses for reactive modes
            self.last_hit = self.t
            self.hit_pos = (_hash(self.t, 1), _hash(self.t, 2))
        self.queue_draw()
        return GLib.SOURCE_CONTINUE

    def _draw(self, _area, cr, w, h):
        self.draw_scene(cr, w, h)

    def draw_scene(self, cr, w, h):
        raise NotImplementedError


def mouse_led(s: Settings, t: float, pos: float, hit: float):
    base = hex_to_rgb(s.color)
    base = tuple(c / 255 for c in base)
    rate = 0.25 + s.speed * 0.18
    e = s.effect
    if e == "off":
        return (0, 0, 0, 0.0)
    if e == "static":
        return (*base, 1.0)
    if e == "breathing":
        return (*base, 0.12 + 0.88 * (0.5 - 0.5 * math.cos(t * rate * 2.2)))
    if e == "flashing":
        return (*base, 1.0 if (t * rate * 1.5) % 1.0 < 0.5 else 0.05)
    if e == "rainbow":
        return (*_hsv(t * rate * 0.25), 1.0)
    if e == "rainbow_breathing":
        phase = t * rate * 2.2
        cycle = math.floor((phase + math.pi) / (2 * math.pi))
        return (*_hsv(cycle * 0.17), 0.12 + 0.88 * (0.5 - 0.5 * math.cos(phase)))
    if e == "wave":
        return (*_hsv(t * rate * 0.3 + pos * 0.8), 1.0)
    if e == "reactive":
        return (*base, max(0.0, 1.0 - hit * 1.6))
    return (*base, 1.0)


def _rounded(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


class MousePreview(Preview):
    def draw_scene(self, cr, w, h):
        s, t = self.s, self.t
        hit = t - self.last_hit
        bright = {1: 0.45, 2: 0.72, 3: 1.0}.get(s.brightness, 1.0)
        scale = min(w / 260, h / 380)
        cr.translate(w / 2 - 100 * scale, h / 2 - 162 * scale)
        cr.scale(scale, scale)

        def color(pos):
            r, g, b, i = mouse_led(s, t, pos, hit)
            return r, g, b, i * bright

        r, g, b, i = color(0.5)
        glow = cairo.RadialGradient(100, 170, 20, 100, 170, 210)
        glow.add_color_stop_rgba(0, r, g, b, 0.55 * i)
        glow.add_color_stop_rgba(1, r, g, b, 0)
        cr.set_source(glow)
        cr.arc(100, 170, 210, 0, 2 * math.pi)
        cr.fill()

        # body
        cr.new_path()
        cr.move_to(100, 8)
        cr.curve_to(150, 8, 182, 40, 186, 105)
        cr.curve_to(190, 170, 186, 240, 168, 280)
        cr.curve_to(150, 314, 124, 316, 100, 316)
        cr.curve_to(76, 316, 50, 314, 32, 280)
        cr.curve_to(14, 240, 10, 170, 14, 105)
        cr.curve_to(18, 40, 50, 8, 100, 8)
        cr.close_path()
        body = cairo.LinearGradient(0, 0, 200, 320)
        body.add_color_stop_rgb(0, 0.17, 0.18, 0.21)
        body.add_color_stop_rgb(1, 0.06, 0.06, 0.08)
        cr.set_source(body)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 0.08)
        cr.set_line_width(2)
        cr.stroke()

        # side LED strips
        segments = 28
        for side in (-1, 1):
            for n in range(segments):
                pos = n / (segments - 1)
                y = 70 + pos * 190
                x = 100 + side * (84 - 10 * (pos - 0.45) ** 2 * 4)
                r, g, b, i = color(pos)
                cr.set_source_rgba(r, g, b, 0.25 * i)
                cr.arc(x, y, 9, 0, 2 * math.pi)
                cr.fill()
                cr.set_source_rgba(r * i + (1 - i) * 0.1, g * i + (1 - i) * 0.1, b * i + (1 - i) * 0.12, 1)
                cr.arc(x, y, 3.2, 0, 2 * math.pi)
                cr.fill()

        # buttons
        cr.set_source_rgba(0, 0, 0, 0.6)
        cr.set_line_width(3)
        cr.move_to(100, 10)
        cr.line_to(100, 120)
        cr.stroke()
        cr.move_to(22, 128)
        cr.curve_to(60, 118, 140, 118, 178, 128)
        cr.stroke()

        # wheel
        r, g, b, i = color(0.1)
        cr.set_source_rgba(0.05, 0.05, 0.06, 1)
        _rounded(cr, 90, 36, 20, 50, 9)
        cr.fill()
        cr.set_source_rgba(r, g, b, 0.35 * i + 0.05)
        _rounded(cr, 93, 40, 14, 42, 7)
        cr.fill()

        # logo
        r, g, b, i = color(0.7)
        logo = cairo.RadialGradient(100, 225, 2, 100, 225, 40)
        logo.add_color_stop_rgba(0, r, g, b, 0.9 * i)
        logo.add_color_stop_rgba(1, r, g, b, 0)
        cr.set_source(logo)
        cr.arc(100, 225, 40, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgba(r * i + 0.12 * (1 - i), g * i + 0.12 * (1 - i), b * i + 0.14 * (1 - i), 1)
        cr.move_to(100, 200)
        cr.line_to(118, 236)
        cr.line_to(100, 228)
        cr.line_to(82, 236)
        cr.close_path()
        cr.fill()


KB_W = max(k.x + k.w for k in KB_KEYS)
KB_H = max(k.y + k.h for k in KB_KEYS)


def keyboard_led(s: Settings, t: float, x: float, y: float, seed: float, hit: float, hit_pos):
    """Color of the key at normalised position (x, y)."""
    base = tuple(c / 255 for c in hex_to_rgb(s.color))
    multi = s.multicolor
    rate = 0.2 + s.speed * 0.22
    e = s.effect
    sign = -1 if s.direction in ("right", "down") else 1

    def pick(hue_hint):
        return _hsv(hue_hint) if multi else base

    if e == "off":
        return (0, 0, 0, 0)
    if e == "static":
        return (*pick(x * 0.8), 1)
    if e == "breathing":
        phase = t * rate * 2
        cycle = math.floor((phase + math.pi) / (2 * math.pi))
        c = _hsv(cycle * 0.21) if multi else base
        return (*c, 0.1 + 0.9 * (0.5 - 0.5 * math.cos(phase)))
    if e == "wave":
        v = (x * 1.4 + sign * t * rate * 0.5)
        if multi:
            return (*_hsv(v), 1)
        return (*base, 0.15 + 0.85 * (0.5 + 0.5 * math.sin(v * 2 * math.pi)))
    if e == "wave_short":
        v = (x * 3.2 + sign * t * rate * 0.6)
        if multi:
            return (*_hsv(v), 1)
        return (*base, 0.1 + 0.9 * max(0.0, math.sin(v * 2 * math.pi)) ** 2)
    if e == "spectrum":
        return (*_hsv(t * rate * 0.12), 1)
    if e == "rain":
        col = round(x * 22)
        cs = _hash(col, 5.1)
        drop = (t * rate * (0.35 + 0.3 * cs) + cs) % 1.4 - 0.2
        i = max(0.0, 1 - (drop - y) * 4) if drop >= y else 0.0
        return (*pick(cs), 0.04 + 0.96 * i)
    if e == "blooming":
        return (*_hsv(seed + t * rate * 0.04 * (0.5 + seed)), 1)
    if e == "reactive":
        d = math.hypot((x - hit_pos[0]) * 2.4, y - hit_pos[1])
        i = max(0.0, 1 - hit * 0.7) if d < 0.07 else 0.0
        return (*pick(seed), 0.04 + 0.96 * i)
    if e == "vertical_rainbow":
        return (*_hsv(y * 0.9 + sign * t * rate * 0.4), 1)
    if e == "rainbow_circle":
        d = math.hypot((x - 0.5) * 2.4, y - 0.5)
        return (*_hsv(d - t * rate * 0.4), 1)
    if e == "hurricane":
        a = math.atan2(y - 0.5, (x - 0.5) * 2.4) / (2 * math.pi)
        if multi:
            return (*_hsv(a + t * rate * 0.4), 1)
        return (*base, 0.15 + 0.85 * (0.5 + 0.5 * math.sin((a + t * rate * 0.4) * 4 * math.pi)))
    if e == "accumulate":
        period = 4.0 / rate
        fill = (t % period) / period
        on = seed < fill * 1.15
        return (*pick(seed), 1 if on else 0.05)
    if e in ("starlight", "starlight_slow"):
        k = 0.5 if e == "starlight_slow" else 1.2
        phase = (t * rate * k + seed * 7) % 1.0
        i = max(0.0, 1 - abs(phase - 0.5) * 6) if _hash(seed, math.floor(t * rate * k + seed * 7)) > 0.55 else 0
        return (*pick(_hash(seed, 3)), 0.04 + 0.96 * i)
    if e == "visor":
        pos = 0.5 + 0.5 * math.sin(t * rate * 1.6)
        i = max(0.0, 1 - abs(x - pos) * 5)
        return (*pick(x), 0.05 + 0.95 * i)
    if e == "ripple":
        d = math.hypot((x - hit_pos[0]) * 2.4, y - hit_pos[1])
        i = max(0.0, 1 - abs(d - hit * rate * 1.2) * 5) * max(0.0, 1 - hit / 2.2)
        return (*pick(d), 0.04 + 0.96 * i)
    if e == "reactive_line":
        on_row = abs(y - hit_pos[1]) < 0.12
        d = abs(x - hit_pos[0]) * 2.4
        i = max(0.0, 1 - abs(d - hit * rate * 1.5) * 4) * max(0.0, 1 - hit / 2.2) if on_row else 0
        return (*pick(x), 0.04 + 0.96 * i)
    return (*base, 1)


ARROWS = {"\u2191": -math.pi / 2, "\u2193": math.pi / 2, "\u2190": math.pi, "\u2192": 0.0}


def _arrow(cr, cx, cy, size, angle):
    """Filled triangle pointing at `angle` (cairo's toy text API has no glyph fallback)."""
    pts = [(size, 0), (-size * 0.7, -size * 0.8), (-size * 0.7, size * 0.8)]
    ca, sa = math.cos(angle), math.sin(angle)
    for n, (x, y) in enumerate(pts):
        (cr.move_to if n == 0 else cr.line_to)(cx + x * ca - y * sa, cy + x * sa + y * ca)
    cr.close_path()
    cr.fill()


class KeyboardPreview(Preview):
    """Keyboard preview; in the custom effect, click or drag on keys to paint them."""

    def __init__(self):
        super().__init__()
        self.on_paint = None  # callback(key_name), set by the page
        self._geom = None
        self._painted = set()
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        self.add_controller(drag)
        self._drag_origin = (0, 0)

    def key_at(self, px, py):
        if not self._geom:
            return None
        ox, oy, unit = self._geom
        x, y = (px - ox) / unit, (py - oy) / unit
        for k in KB_KEYS:
            if k.x <= x < k.x + k.w and k.y <= y < k.y + k.h:
                return k.name
        return None

    def _paint_at(self, px, py):
        if self.s.effect != "custom" or not self.on_paint:
            return
        name = self.key_at(px, py)
        if name and name not in self._painted:
            self._painted.add(name)
            self.on_paint(name)

    def _drag_begin(self, _g, x, y):
        self._painted = set()
        self._drag_origin = (x, y)
        self._paint_at(x, y)

    def _drag_update(self, _g, dx, dy):
        self._paint_at(self._drag_origin[0] + dx, self._drag_origin[1] + dy)

    def draw_scene(self, cr, w, h):
        s, t = self.s, self.t
        hit = t - self.last_hit
        bright = 0.35 + 0.65 * (s.brightness - 1) / 3
        unit = min((w - 40) / (KB_W + 1), (h - 40) / (KB_H + 1))
        ox = (w - KB_W * unit) / 2
        oy = (h - KB_H * unit) / 2
        self._geom = (ox, oy, unit)
        pad = unit * 0.5
        custom = s.effect == "custom"

        cr.set_source_rgb(0.07, 0.07, 0.09)
        _rounded(cr, ox - pad, oy - pad, KB_W * unit + 2 * pad, KB_H * unit + 2 * pad, unit * 0.4)
        cr.fill()
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)

        hp = ((self.hit_pos[0] * w - ox) / (KB_W * unit), (self.hit_pos[1] * h - oy) / (KB_H * unit))
        for idx, k in enumerate(KB_KEYS):
            if custom:
                hexcol = s.keys.get(k.name)
                r, g, b = (c / 255 for c in hex_to_rgb(hexcol)) if hexcol else (0, 0, 0)
                i = 1.0 if (r or g or b) else 0.0
            else:
                cx = (k.x + k.w / 2) / KB_W
                cy = (k.y + k.h / 2) / KB_H
                r, g, b, i = keyboard_led(s, t, cx, cy, _hash(idx, 0.37), hit, hp)
            i *= bright
            x0, y0 = ox + k.x * unit, oy + k.y * unit
            kw_px, kh_px = k.w * unit, k.h * unit
            cr.set_source_rgba(r, g, b, 0.65 * i)
            _rounded(cr, x0 + 1, y0 + 1, kw_px - 2, kh_px - 2, unit * 0.12)
            cr.fill()
            m = unit * 0.1
            cr.set_source_rgba(0.1 + 0.62 * r * i, 0.1 + 0.62 * g * i, 0.12 + 0.62 * b * i, 1)
            _rounded(cr, x0 + m, y0 + m, kw_px - 2 * m, kh_px - 2 * m, unit * 0.1)
            cr.fill()
            legend = (0.55 + 0.45 * max(r, 0.3) * i + 0.25 * (1 - i), 0.55 + 0.45 * max(g, 0.3) * i + 0.25 * (1 - i),
                      0.58 + 0.42 * max(b, 0.3) * i + 0.25 * (1 - i), 0.95)
            # legend, lit by the key's LED
            if k.label in ARROWS:
                cr.set_source_rgba(*legend)
                _arrow(cr, x0 + kw_px / 2, y0 + kh_px / 2, unit * 0.16, ARROWS[k.label])
            elif k.label:
                cr.set_font_size(unit * (0.34 if len(k.label) <= 2 else 0.24))
                ext = cr.text_extents(k.label)
                cr.move_to(x0 + kw_px / 2 - ext.width / 2 - ext.x_bearing,
                           y0 + kh_px / 2 - ext.height / 2 - ext.y_bearing)
                cr.set_source_rgba(*legend)
                cr.show_text(k.label)


# --- generic device page -----------------------------------------------------
class DevicePage(Gtk.Box):
    def __init__(self, window: "RedragonWindow", backend: Backend, preview: Preview):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self.window = window
        self.backend = backend
        self.preview = preview
        self.settings = config.load(backend.key)
        if self.settings.effect not in backend.effects_by_key:
            self.settings.effect = backend.effects[0].key
        self._lock = threading.Lock()
        self._pending = None
        self._loading = True
        self.device_name = None

        self.append(self._build_preview())
        self.append(self._build_controls())
        self._load_into_widgets()
        self._loading = False

    @property
    def effect(self):
        return self.backend.effects_by_key[self.settings.effect]

    # -- layout --------------------------------------------------------
    def _build_preview(self):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                       margin_top=18, margin_bottom=18, margin_start=18, margin_end=6,
                       hexpand=True, width_request=420)
        card.add_css_class("preview-card")
        self.preview.set_margin_top(18)
        self.preview.set_margin_start(12)
        self.preview.set_margin_end(12)
        card.append(self.preview)
        self.effect_title = Gtk.Label(css_classes=["effect-title"])
        self.effect_sub = Gtk.Label(css_classes=["effect-sub"], margin_bottom=24)
        card.append(self.effect_title)
        card.append(self.effect_sub)
        return card

    def _build_controls(self):
        page = Adw.PreferencesPage(width_request=440)

        self.profile_row = None
        if self.backend.key == "mouse":
            target = Adw.PreferencesGroup()
            self.profile_row = Adw.ComboRow(
                title="Apply to", subtitle="Each mouse profile can have its own lighting",
                model=Gtk.StringList.new(["All profiles"] + [f"Profile {i}" for i in range(1, 6)]))
            self.profile_row.connect("notify::selected", self._on_target_profile)
            target.add(self.profile_row)
            page.add(target)

        effects = Adw.PreferencesGroup(title="Effect")
        self.effect_checks = {}
        leader = None
        for e in self.backend.effects:
            row = Adw.ActionRow(title=e.label, subtitle=e.description)
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            if leader:
                check.set_group(leader)
            else:
                leader = check
            check.connect("toggled", self._on_effect_toggled, e.key)
            row.add_prefix(check)
            row.set_activatable_widget(check)
            effects.add(row)
            self.effect_checks[e.key] = check
        page.add(effects)

        color_group = Adw.PreferencesGroup(title="Color")
        self.multi_row = Adw.SwitchRow(title="Multicolor", subtitle="Use rainbow colors instead of the chosen one")
        self.multi_row.connect("notify::active", self._on_multi)
        color_group.add(self.multi_row)
        self.color_row = Adw.ActionRow(title="LED color")
        self.color_button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), valign=Gtk.Align.CENTER)
        self.color_button.connect("notify::rgba", self._on_color_changed)
        self.color_row.add_suffix(self.color_button)
        color_group.add(self.color_row)
        self.swatch_row = Adw.PreferencesRow(activatable=False)
        swatches = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=9,
                               min_children_per_line=5, column_spacing=8, row_spacing=8,
                               margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        for idx, hexcol in enumerate(PRESETS):
            btn = Gtk.Button(tooltip_text=hexcol, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
            btn.add_css_class("swatch")
            btn.add_css_class(f"swatch-{idx}")
            btn.connect("clicked", self._on_swatch, hexcol)
            swatches.append(btn)
        self.swatch_row.set_child(swatches)
        color_group.add(self.swatch_row)
        page.add(color_group)

        self.keys_group = None
        if isinstance(self.preview, KeyboardPreview):
            self.preview.on_paint = self._on_paint_key
            self.keys_group = Adw.PreferencesGroup(
                title="Per-key colors",
                description="Click or drag on the keys in the preview to paint them with the LED color.")
            for label, handler in (("Fill all keys", self._on_fill_all), ("Clear all keys", self._on_clear_all)):
                row = Adw.ButtonRow(title=label)
                row.connect("activated", handler)
                self.keys_group.add(row)
            page.add(self.keys_group)

        anim = Adw.PreferencesGroup(title="Animation")
        self.speed_row, self.speed_scale = self._scale_row("Speed", *self.backend.speed_range, "speed")
        self.bright_row, self.bright_scale = self._scale_row("Brightness", *self.backend.brightness_range, "brightness")
        self.dir_row = Adw.ComboRow(title="Direction")
        self.dir_row.connect("notify::selected", self._on_direction)
        anim.add(self.speed_row)
        anim.add(self.bright_row)
        anim.add(self.dir_row)
        page.add(anim)

        wb_group = Adw.PreferencesGroup(
            title="White balance",
            description="If white looks tinted on the device, lower the channel that is too strong. "
                        "Use \u201cShow white\u201d to compare.")
        self.wb_scales = []
        for idx, name in enumerate(("Red", "Green", "Blue")):
            row = Adw.ActionRow(title=name)
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 30, 100, 1)
            scale.set_hexpand(True)
            scale.set_size_request(200, -1)
            scale.set_draw_value(True)
            scale.set_value_pos(Gtk.PositionType.RIGHT)
            scale.set_format_value_func(lambda _s, v: f"{v:.0f}%")
            scale.connect("value-changed", self._on_balance)
            row.add_suffix(scale)
            wb_group.add(row)
            self.wb_scales.append(scale)
        for label, handler in (("Show white", self._on_show_white), ("Reset", self._on_reset_balance)):
            brow = Adw.ButtonRow(title=label)
            brow.connect("activated", handler)
            wb_group.add(brow)
        page.add(wb_group)

        apply_group = Adw.PreferencesGroup()
        self.live_row = Adw.SwitchRow(title="Apply live",
                                      subtitle="Send changes to the device as you make them", active=True)
        apply_group.add(self.live_row)
        btn = Gtk.Button(label=f"Apply to {self.backend.title.lower()}", halign=Gtk.Align.CENTER, margin_top=18)
        btn.add_css_class("suggested-action")
        btn.add_css_class("pill")
        btn.connect("clicked", lambda *_: self.apply(show_toast=True))
        apply_group.add(btn)
        page.add(apply_group)
        return page

    def _scale_row(self, title, lo, hi, attr):
        row = Adw.ActionRow(title=title)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, 1)
        scale.set_hexpand(True)
        scale.set_size_request(200, -1)
        scale.set_draw_value(False)
        scale.set_round_digits(0)
        for v in range(lo, hi + 1):
            scale.add_mark(v, Gtk.PositionType.BOTTOM, None)
        # One handler per slider: a shared one would read the other slider
        # while it still holds its initial minimum during startup.
        scale.connect("value-changed", self._on_scale_changed, attr)
        row.add_suffix(scale)
        return row, scale

    # -- state ---------------------------------------------------------
    def _load_into_widgets(self):
        s = self.settings
        self.effect_checks[s.effect].set_active(True)
        rgba = Gdk.RGBA()
        rgba.parse(s.color)
        self.color_button.set_rgba(rgba)
        self.speed_scale.set_value(s.speed)
        self.bright_scale.set_value(s.brightness)
        self.multi_row.set_active(s.multicolor)
        if self.profile_row is not None:
            self.profile_row.set_selected(max(0, min(5, s.profile)))
        for scale, gain in zip(self.wb_scales, config.load_balance(self.backend.key)):
            scale.set_value(round(gain * 100))
        self._sync()

    def _sync(self):
        e, s = self.effect, self.settings
        self.preview.s = s
        self.effect_title.set_label(e.label)
        self.effect_sub.set_label(e.description)
        optional_multi = e.random == "optional"
        self.multi_row.set_visible(optional_multi)
        colored = e.uses_color and not (optional_multi and s.multicolor)
        self.color_row.set_sensitive(colored)
        self.swatch_row.set_sensitive(colored)
        self.speed_row.set_sensitive(e.uses_speed)
        self.bright_row.set_sensitive(not e.is_off)
        # direction choices depend on the effect
        self.dir_row.set_visible(e.direction is not None)
        if self.keys_group is not None:
            self.keys_group.set_visible(e.key == "custom")
        if e.direction:
            choices = DIRECTIONS[e.direction]
            keys = [k for k, _ in choices]
            if s.direction not in keys:
                s.direction = keys[0]
            # Never replace the model needlessly: this also runs from the
            # row's own notify::selected handler, and swapping the model of a
            # ComboRow from inside that signal hangs GTK.
            self._loading_dir = True
            try:
                if getattr(self, "_dir_kind", None) != e.direction:
                    self.dir_row.set_model(Gtk.StringList.new([label for _, label in choices]))
                    self._dir_kind = e.direction
                wanted = keys.index(s.direction)
                if self.dir_row.get_selected() != wanted:
                    self.dir_row.set_selected(wanted)
            finally:
                self._loading_dir = False
        self.preview.queue_draw()

    def _changed(self):
        if self._loading:
            return
        self._sync()
        if self.live_row.get_active():
            if self._pending:
                GLib.source_remove(self._pending)
            self._pending = GLib.timeout_add(220, self._debounced)

    def _debounced(self):
        self._pending = None
        self.apply(show_toast=False)
        return GLib.SOURCE_REMOVE

    def _on_effect_toggled(self, check, key):
        if check.get_active():
            self.settings.effect = key
            if key == "custom" and not self.settings.keys:
                self.settings.keys = {k.name: self.settings.color for k in KB_KEYS}
            self._changed()

    def _on_paint_key(self, name):
        self.settings.keys[name] = self.settings.color
        self._changed()

    def _on_fill_all(self, *_):
        self.settings.keys = {k.name: self.settings.color for k in KB_KEYS}
        self._changed()

    def _on_clear_all(self, *_):
        self.settings.keys = {}
        self._changed()

    def _on_color_changed(self, button, _p):
        c = button.get_rgba()
        self.settings.color = rgb_to_hex((round(c.red * 255), round(c.green * 255), round(c.blue * 255)))
        self._changed()

    def _on_swatch(self, _b, hexcol):
        rgba = Gdk.RGBA()
        rgba.parse(hexcol)
        self.color_button.set_rgba(rgba)

    def _on_scale_changed(self, scale, attr):
        setattr(self.settings, attr, int(round(scale.get_value())))
        self._changed()

    def _on_multi(self, row, _p):
        self.settings.multicolor = row.get_active()
        self._changed()

    def _on_direction(self, row, _p):
        if getattr(self, "_loading_dir", False) or not self.effect.direction:
            return
        idx = row.get_selected()
        choices = DIRECTIONS[self.effect.direction]
        if 0 <= idx < len(choices):
            self.settings.direction = choices[idx][0]
            self._changed()

    def _on_target_profile(self, row, _p):
        if self._loading:
            return
        self.settings.profile = row.get_selected()
        config.save(self.backend.key, self.settings)
        # show what that profile currently has, without writing anything
        self._read_from_device()

    def _on_balance(self, _scale):
        if self._loading:
            return
        config.save_balance(self.backend.key, tuple(sc.get_value() / 100 for sc in self.wb_scales))
        if self.live_row.get_active():
            self._changed()

    def _on_show_white(self, *_):
        self.effect_checks["static"].set_active(True)
        self._on_swatch(None, "#ffffff")
        # apply right away even if nothing changed (e.g. already static white)
        self.apply(show_toast=False)

    def _on_reset_balance(self, *_):
        for sc in self.wb_scales:
            sc.set_value(100)

    # -- device --------------------------------------------------------
    def refresh(self):
        self.device_name = self.backend.detect()
        if self.device_name and self.backend._read is not None:
            self._read_from_device()
        return self.device_name

    def _read_from_device(self):
        """Show what is stored on the device instead of the last saved settings."""
        base = self.settings.copy()

        def worker():
            try:
                read = self.backend.read(base)
            except BackendError:
                read = None
            GLib.idle_add(self._show_read, read)

        threading.Thread(target=worker, daemon=True).start()

    def _show_read(self, read):
        if read is not None and read.effect in self.backend.effects_by_key and read != self.settings:
            self.settings = read
            self._loading = True
            try:
                self._load_into_widgets()
            finally:
                self._loading = False
            config.save(self.backend.key, self.settings)
        return False

    def apply(self, show_toast: bool):
        s = self.settings.copy()
        config.save(self.backend.key, s)

        def worker():
            with self._lock:
                try:
                    self.backend.apply(s)
                    GLib.idle_add(self.window.on_applied, self, None, show_toast)
                except BackendError as exc:
                    GLib.idle_add(self.window.on_applied, self, exc, show_toast)

        threading.Thread(target=worker, daemon=True).start()


# --- mouse DPI / profiles ----------------------------------------------------
class MouseDpiPage(Adw.PreferencesPage):
    """Active profile, DPI levels and report rate, read from and written to the mouse."""

    def __init__(self, window: "RedragonWindow"):
        super().__init__()
        self.window = window
        self.backend = BACKENDS["mouse"]
        self.device_name = None
        self.state: mouse_drv.MouseState | None = None
        self._updating = False

        prof = Adw.PreferencesGroup(
            title="Profile",
            description="The mouse stores five profiles, each with its own DPI levels and report rate.")
        self.profile_row = Adw.ComboRow(
            title="Active profile",
            model=Gtk.StringList.new([f"Profile {i + 1}" for i in range(mouse_drv.PROFILES)]))
        self.profile_row.connect("notify::selected", self._on_profile)
        prof.add(self.profile_row)
        self.add(prof)

        dpi = Adw.PreferencesGroup(
            title="DPI levels",
            description="The DPI button under the wheel cycles through the enabled levels. "
                        "Values are rounded to the steps the sensor supports.")
        self.level_rows = []
        lo, hi = mouse_drv.DPI_RANGE
        for j in range(mouse_drv.DPI_LEVELS):
            row = Adw.SpinRow(title=f"Level {j + 1}",
                              adjustment=Gtk.Adjustment(lower=lo, upper=hi, step_increment=50, page_increment=400),
                              digits=0)
            switch = Gtk.Switch(valign=Gtk.Align.CENTER, tooltip_text="Include this level in the DPI cycle")
            row.add_prefix(switch)
            row.connect("notify::value", self._on_edit)
            switch.connect("notify::active", self._on_edit)
            dpi.add(row)
            self.level_rows.append((row, switch))
        self.poll_row = Adw.ComboRow(
            title="Report rate", subtitle="How often the mouse reports its position",
            model=Gtk.StringList.new([f"{hz} Hz" for hz in sorted(mouse_drv.POLL_CODES)]))
        dpi.add(self.poll_row)
        self.add(dpi)

        actions = Adw.PreferencesGroup()
        box = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER, margin_top=6)
        self.reload_button = Gtk.Button(label="Reload from mouse")
        self.reload_button.add_css_class("pill")
        self.reload_button.connect("clicked", lambda *_: self.reload())
        self.apply_button = Gtk.Button(label="Write to mouse")
        self.apply_button.add_css_class("pill")
        self.apply_button.add_css_class("suggested-action")
        self.apply_button.connect("clicked", lambda *_: self._write())
        box.append(self.reload_button)
        box.append(self.apply_button)
        actions.add(box)
        self.add(actions)
        self._set_busy(True)

    # -- helpers ---------------------------------------------------------
    def _set_busy(self, busy: bool):
        for w in (self.profile_row, self.poll_row, self.apply_button, self.reload_button):
            w.set_sensitive(not busy)
        for row, switch in self.level_rows:
            row.set_sensitive(not busy)

    def _run(self, job, done):
        """Run job(mouse) in a thread with the mouse lock, then done(result, error) on the UI thread."""
        self._set_busy(True)

        def worker():
            try:
                with MOUSE_LOCK, mouse_drv.CobraMouse() as m:
                    result = job(m)
                GLib.idle_add(self._finish, done, result, None)
            except (mouse_drv.DeviceError, ValueError) as exc:
                GLib.idle_add(self._finish, done, None, exc)

        threading.Thread(target=worker, daemon=True).start()

    def _finish(self, done, result, error):
        self._set_busy(self.state is None)
        if error is not None:
            if isinstance(error, mouse_drv.DevicePermissionError):
                self.window._update_banner("Missing permissions: run  sudo ./install-udev.sh  and replug the device.")
            elif isinstance(error, mouse_drv.DeviceNotFound):
                self.device_name = None
                self.window._update_banner()
            else:
                self.window.toasts.add_toast(Adw.Toast(title=str(error), timeout=4))
        done(result, error)
        return False

    def _show(self, state: mouse_drv.MouseState):
        self.state = state
        self._updating = True
        self.profile_row.set_selected(state.active_profile)
        prof = state.profiles[state.active_profile]
        for (row, switch), lv in zip(self.level_rows, prof.levels):
            row.set_value(lv.dpi)
            switch.set_active(lv.enabled)
        rates = sorted(mouse_drv.POLL_CODES)
        if prof.poll_rate in rates:
            self.poll_row.set_selected(rates.index(prof.poll_rate))
        self._updating = False
        self._on_edit()
        self._set_busy(False)

    # -- device ----------------------------------------------------------
    def refresh(self):
        self.device_name = self.backend.detect()
        if self.device_name:
            self.reload()
        return self.device_name

    def reload(self):
        self._run(lambda m: m.read_state(), lambda st, err: st and self._show(st))

    def _on_profile(self, row, _p):
        if self._updating or self.state is None:
            return
        idx = row.get_selected()
        self._run(lambda m: (m.set_active_profile(idx), m.read_state())[1],
                  lambda st, err: st and self._show(st))

    def _on_edit(self, *_):
        if self._updating:
            return
        enabled = 0
        for row, switch in self.level_rows:
            want = int(row.get_value())
            q = mouse_drv.quantize_dpi(want)
            row.set_subtitle("" if q == want else f"stored as {q} DPI")
            enabled += switch.get_active()
        self.apply_button.set_sensitive(enabled > 0 and self.state is not None)
        self.apply_button.set_tooltip_text(None if enabled else "Enable at least one DPI level")

    def _write(self):
        idx = self.profile_row.get_selected()
        levels = [mouse_drv.DpiLevel(sw.get_active(), int(row.get_value())) for row, sw in self.level_rows]
        poll = sorted(mouse_drv.POLL_CODES)[self.poll_row.get_selected()]

        def job(m):
            m.write_profile(idx, levels, poll)
            return m.read_state()

        def done(state, error):
            if state is None:
                return
            self._show(state)
            got = [(lv.enabled, lv.dpi) for lv in state.profiles[idx].levels]
            want = [(lv.enabled, mouse_drv.quantize_dpi(lv.dpi)) for lv in levels]
            ok = got == want and state.profiles[idx].poll_rate == poll
            self.window.toasts.add_toast(Adw.Toast(
                title=f"Profile {idx + 1} saved to the mouse" if ok else "The mouse did not store the values as sent",
                timeout=3))

        self._run(job, done)


# --- window ------------------------------------------------------------------
class RedragonWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Redragon RGB", default_width=1100, default_height=720)
        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)
        menu = Gtk.MenuButton(icon_name="open-menu-symbolic", tooltip_text="Menu")
        m = Gio.Menu()
        m.append("Rescan devices", "win.refresh")
        m.append("About Redragon RGB", "app.about")
        menu.set_menu_model(m)
        header.pack_end(menu)
        view.add_top_bar(header)

        self.banner = Adw.Banner(button_label="Retry")
        self.banner.connect("button-clicked", lambda *_: self.refresh_devices())
        view.add_top_bar(self.banner)

        self.pages = {
            "mouse": DevicePage(self, BACKENDS["mouse"], MousePreview()),
            "keyboard": DevicePage(self, BACKENDS["keyboard"], KeyboardPreview()),
        }
        for key, page in self.pages.items():
            b = page.backend
            sp = self.stack.add_titled_with_icon(page, key, b.title, b.icon)
            page.stack_page = sp
        self.dpi_page = MouseDpiPage(self)
        self.dpi_page.stack_page = self.stack.add_titled_with_icon(
            self.dpi_page, "mouse-dpi", "Mouse DPI", "preferences-system-symbolic")
        self.stack.connect("notify::visible-child", lambda *_: self._update_banner())
        view.set_content(self.stack)
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        act = Gio.SimpleAction.new("refresh", None)
        act.connect("activate", lambda *_: self.refresh_devices())
        self.add_action(act)
        self.refresh_devices()

    def current(self) -> DevicePage:
        return self.stack.get_visible_child()

    def refresh_devices(self):
        first_found = None
        self.dpi_page.refresh()
        for key, page in self.pages.items():
            name = page.refresh()
            page.stack_page.set_needs_attention(False)
            if name and first_found is None:
                first_found = key
        if first_found and not self.current().device_name:
            self.stack.set_visible_child_name(first_found)
        self._update_banner()

    def _update_banner(self, message: str | None = None):
        page = self.current()
        if page is None:
            return
        if message:
            self.banner.set_title(message)
            self.banner.set_revealed(True)
        elif page.device_name is None:
            self.banner.set_title(f"{page.backend.title}: no Redragon device detected. Plug it in and press Retry.")
            self.banner.set_revealed(True)
        else:
            self.banner.set_revealed(False)

    def on_applied(self, page: DevicePage, error, show_toast):
        if error is None:
            if page is self.current():
                self._update_banner()
            if show_toast:
                self.toasts.add_toast(Adw.Toast(title="Settings applied", timeout=2))
        elif error.kind == "permission":
            self._update_banner("Missing permissions: run  sudo ./install-udev.sh  and replug the device.")
        elif error.kind == "notfound":
            page.refresh()
            self._update_banner()
        else:
            self.toasts.add_toast(Adw.Toast(title=str(error), timeout=4))
        return False


class RedragonApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.connect("activate", self._on_activate)
        self.connect("startup", self._on_startup)

    def _on_startup(self, _app):
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS + "\n".join(
            f".swatch-{i} {{ background: {c}; }}" for i, c in enumerate(PRESETS)))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", self._on_about)
        self.add_action(about)

    def _on_activate(self, _app):
        win = self.props.active_window or RedragonWindow(self)
        win.present()

    def _on_about(self, *_):
        dialog = Adw.AboutDialog(
            application_name="Redragon RGB",
            application_icon="input-mouse",
            version=__version__,
            comments="Configure the RGB lighting of Redragon mice and keyboards on Linux",
            license_type=Gtk.License.GPL_3_0,
            website="https://github.com/codingkoala/redragon-rgb",
        )
        dialog.add_credit_section("Protocol research", [
            "dokutan/mouse_m908", "OpenRGB", "SK2674/m711-port", "syndicalt/openrgb-reddragonk556-controller"])
        dialog.present(self.props.active_window)


def main() -> int:
    return RedragonApp().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
