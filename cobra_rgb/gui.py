"""GTK4 / libadwaita user interface."""

from __future__ import annotations

import colorsys
import math
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from . import __version__  # noqa: E402
from .config import Settings, hex_to_rgb, rgb_to_hex  # noqa: E402
from .device import (  # noqa: E402
    BRIGHTNESS_RANGE,
    EFFECTS,
    EFFECTS_BY_KEY,
    SPEED_RANGE,
    CobraMouse,
    DeviceError,
    DeviceNotFound,
    DevicePermissionError,
    find_devices,
)

APP_ID = "io.github.codingkoala.CobraRGB"

PRESETS = ["#ff1e3c", "#ff7a00", "#ffd000", "#3cff6e", "#00e5ff", "#2f6bff", "#9b4dff", "#ff3df2", "#ffffff"]

DESCRIPTIONS = {
    "static": "Colore fisso",
    "breathing": "Il colore pulsa lentamente",
    "flashing": "Il colore lampeggia",
    "rainbow": "Ciclo continuo di tutti i colori",
    "rainbow_breathing": "Pulsazione con colore che cambia",
    "wave": "Onda di colori che scorre",
    "reactive": "Si illumina quando premi i tasti",
    "off": "LED spenti",
}

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
.effect-title { font-weight: 800; font-size: 20pt; }
.effect-sub { opacity: 0.6; }
"""


# --- preview animation -------------------------------------------------------
def _hue(rgb, shift):
    h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
    r, g, b = colorsys.hsv_to_rgb((h + shift) % 1.0, max(s, 0.85), max(v, 0.9))
    return r, g, b


def led_color(effect: str, rgb, t: float, pos: float, speed: int, reactive_hit: float):
    """Return (r, g, b, intensity) in 0..1 for a LED at position pos (0..1)."""
    base = tuple(c / 255 for c in rgb)
    rate = 0.25 + speed * 0.18  # cycles per second-ish
    if effect == "off":
        return (0, 0, 0, 0.0)
    if effect == "static":
        return (*base, 1.0)
    if effect == "breathing":
        return (*base, 0.12 + 0.88 * (0.5 - 0.5 * math.cos(t * rate * 2.2)))
    if effect == "flashing":
        return (*base, 1.0 if (t * rate * 1.5) % 1.0 < 0.5 else 0.05)
    if effect == "rainbow":
        r, g, b = colorsys.hsv_to_rgb((t * rate * 0.25) % 1.0, 1, 1)
        return (r, g, b, 1.0)
    if effect == "rainbow_breathing":
        phase = t * rate * 2.2
        cycle = math.floor((phase + math.pi) / (2 * math.pi))
        r, g, b = colorsys.hsv_to_rgb((cycle * 0.17) % 1.0, 1, 1)
        return (r, g, b, 0.12 + 0.88 * (0.5 - 0.5 * math.cos(phase)))
    if effect == "wave":
        r, g, b = colorsys.hsv_to_rgb((t * rate * 0.3 + pos * 0.8) % 1.0, 1, 1)
        return (r, g, b, 1.0)
    if effect == "reactive":
        return (*base, max(0.0, 1.0 - reactive_hit * 1.6))
    return (*base, 1.0)


def _mouse_path(cr):
    """Outline of a gaming mouse in a 200x320 box, seen from above."""
    cr.new_path()
    cr.move_to(100, 8)
    cr.curve_to(150, 8, 182, 40, 186, 105)
    cr.curve_to(190, 170, 186, 240, 168, 280)
    cr.curve_to(150, 314, 124, 316, 100, 316)
    cr.curve_to(76, 316, 50, 314, 32, 280)
    cr.curve_to(14, 240, 10, 170, 14, 105)
    cr.curve_to(18, 40, 50, 8, 100, 8)
    cr.close_path()


class MousePreview(Gtk.DrawingArea):
    def __init__(self):
        super().__init__(hexpand=True, vexpand=True)
        self.effect = "static"
        self.rgb = (255, 30, 60)
        self.speed = 4
        self.brightness = 3
        self._start = None
        self._last_hit = 0.0
        self.set_draw_func(self._draw)
        self.add_tick_callback(self._tick)
        click = Gtk.GestureClick()
        click.connect("pressed", lambda *_: self._hit())
        self.add_controller(click)

    def _hit(self):
        self._last_hit = self._now

    def _tick(self, widget, clock):
        self._now = clock.get_frame_time() / 1e6
        if self._start is None:
            self._start = self._now
        if self.effect == "reactive" and self._now - self._last_hit > 1.8:
            self._last_hit = self._now  # simulate a click now and then
        self.queue_draw()
        return GLib.SOURCE_CONTINUE

    def _draw(self, area, cr, w, h):
        t = getattr(self, "_now", 0.0) - (self._start or 0.0)
        hit = getattr(self, "_now", 0.0) - self._last_hit
        bright = {1: 0.45, 2: 0.72, 3: 1.0}.get(self.brightness, 1.0)
        scale = min(w / 260, h / 380)
        cr.translate(w / 2 - 100 * scale, h / 2 - 162 * scale)
        cr.scale(scale, scale)

        def color(pos):
            r, g, b, i = led_color(self.effect, self.rgb, t, pos, self.speed, hit)
            return r, g, b, i * bright

        # Ambient glow under the mouse
        import cairo

        r, g, b, i = color(0.5)
        glow = cairo.RadialGradient(100, 170, 20, 100, 170, 210)
        glow.add_color_stop_rgba(0, r, g, b, 0.55 * i)
        glow.add_color_stop_rgba(1, r, g, b, 0)
        cr.set_source(glow)
        cr.arc(100, 170, 210, 0, 2 * math.pi)
        cr.fill()

        # Body
        _mouse_path(cr)
        body = cairo.LinearGradient(0, 0, 200, 320)
        body.add_color_stop_rgb(0, 0.17, 0.18, 0.21)
        body.add_color_stop_rgb(1, 0.06, 0.06, 0.08)
        cr.set_source(body)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 0.08)
        cr.set_line_width(2)
        cr.stroke()

        # Side LED strips (drawn as many short segments so "wave" can flow)
        segments = 28
        for side in (-1, 1):
            for s in range(segments):
                pos = s / (segments - 1)
                y = 70 + pos * 190
                x = 100 + side * (84 - 10 * (pos - 0.45) ** 2 * 4)
                r, g, b, i = color(pos)
                cr.set_source_rgba(r, g, b, 0.25 * i)
                cr.arc(x, y, 9, 0, 2 * math.pi)
                cr.fill()
                cr.set_source_rgba(r * i + (1 - i) * 0.1, g * i + (1 - i) * 0.1, b * i + (1 - i) * 0.12, 1)
                cr.arc(x, y, 3.2, 0, 2 * math.pi)
                cr.fill()

        # Button split and buttons
        cr.set_source_rgba(0, 0, 0, 0.6)
        cr.set_line_width(3)
        cr.move_to(100, 10)
        cr.line_to(100, 120)
        cr.stroke()
        cr.move_to(22, 128)
        cr.curve_to(60, 118, 140, 118, 178, 128)
        cr.stroke()

        # Scroll wheel
        r, g, b, i = color(0.1)
        cr.set_source_rgba(0.05, 0.05, 0.06, 1)
        self._rounded(cr, 90, 36, 20, 50, 9)
        cr.fill()
        cr.set_source_rgba(r, g, b, 0.35 * i + 0.05)
        self._rounded(cr, 93, 40, 14, 42, 7)
        cr.fill()

        # Logo
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

    @staticmethod
    def _rounded(cr, x, y, w, h, r):
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()


# --- main window -------------------------------------------------------------
class CobraWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Cobra RGB", default_width=1000, default_height=680)
        self.settings = Settings.load()
        if self.settings.effect not in EFFECTS_BY_KEY:
            self.settings.effect = "static"
        self._apply_lock = threading.Lock()
        self._pending = None
        self._loading = True

        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.title = Adw.WindowTitle(title="Cobra RGB", subtitle="Ricerca mouse…")
        header.set_title_widget(self.title)
        menu = Gtk.MenuButton(icon_name="open-menu-symbolic", tooltip_text="Menu")
        menu_model = Gio_menu()
        menu.set_menu_model(menu_model)
        header.pack_end(menu)
        view.add_top_bar(header)

        self.banner = Adw.Banner(button_label="Riprova")
        self.banner.connect("button-clicked", lambda *_: self.refresh_device())
        view.add_top_bar(self.banner)

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        body.append(self._build_preview())
        body.append(self._build_controls())
        view.set_content(body)
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        self._load_into_widgets()
        self._loading = False
        self.refresh_device()

    # -- layout --------------------------------------------------------
    def _build_preview(self):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                       margin_top=18, margin_bottom=18, margin_start=18, margin_end=6,
                       hexpand=True, width_request=380)
        card.add_css_class("preview-card")
        self.preview = MousePreview()
        self.preview.set_margin_top(24)
        card.append(self.preview)
        self.effect_title = Gtk.Label(css_classes=["effect-title"])
        self.effect_sub = Gtk.Label(css_classes=["effect-sub"], margin_bottom=24)
        card.append(self.effect_title)
        card.append(self.effect_sub)
        return card

    def _build_controls(self):
        page = Adw.PreferencesPage(width_request=440)

        # Effects
        effects = Adw.PreferencesGroup(title="Effetto")
        self.effect_checks = {}
        group_leader = None
        for e in EFFECTS:
            row = Adw.ActionRow(title=e.label, subtitle=DESCRIPTIONS[e.key])
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            if group_leader:
                check.set_group(group_leader)
            else:
                group_leader = check
            check.connect("toggled", self._on_effect_toggled, e.key)
            row.add_prefix(check)
            row.set_activatable_widget(check)
            effects.add(row)
            self.effect_checks[e.key] = check
        page.add(effects)

        # Colour
        color_group = Adw.PreferencesGroup(title="Colore")
        self.color_row = Adw.ActionRow(title="Colore LED")
        self.color_button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), valign=Gtk.Align.CENTER)
        self.color_button.connect("notify::rgba", self._on_color_changed)
        self.color_row.add_suffix(self.color_button)
        color_group.add(self.color_row)

        swatch_row = Adw.PreferencesRow(activatable=False)
        swatches = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=9,
                               min_children_per_line=5, column_spacing=8, row_spacing=8,
                               margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        provider = Gtk.CssProvider()
        rules = []
        for idx, hexcol in enumerate(PRESETS):
            btn = Gtk.Button(tooltip_text=hexcol, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
            btn.add_css_class("swatch")
            btn.add_css_class(f"swatch-{idx}")
            rules.append(f".swatch-{idx} {{ background: {hexcol}; }}")
            btn.connect("clicked", self._on_swatch, hexcol)
            swatches.append(btn)
        provider.load_from_string("\n".join(rules))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        swatch_row.set_child(swatches)
        self.swatch_row = swatch_row
        color_group.add(swatch_row)
        page.add(color_group)

        # Animation
        anim = Adw.PreferencesGroup(title="Animazione")
        self.speed_row, self.speed_scale = self._scale_row("Velocità", *SPEED_RANGE)
        self.bright_row, self.bright_scale = self._scale_row("Luminosità", *BRIGHTNESS_RANGE)
        anim.add(self.speed_row)
        anim.add(self.bright_row)
        page.add(anim)

        # Apply
        apply_group = Adw.PreferencesGroup()
        self.live_row = Adw.SwitchRow(title="Applica in tempo reale",
                                      subtitle="Invia le modifiche al mouse mentre le fai", active=True)
        apply_group.add(self.live_row)
        self.apply_button = Gtk.Button(label="Applica al mouse", halign=Gtk.Align.CENTER, margin_top=18)
        self.apply_button.add_css_class("suggested-action")
        self.apply_button.add_css_class("pill")
        self.apply_button.connect("clicked", lambda *_: self.apply(show_toast=True))
        apply_group.add(self.apply_button)
        page.add(apply_group)
        return page

    def _scale_row(self, title, lo, hi):
        row = Adw.ActionRow(title=title)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, 1)
        scale.set_hexpand(True)
        scale.set_size_request(200, -1)
        scale.set_draw_value(False)
        scale.set_round_digits(0)
        for v in range(lo, hi + 1):
            scale.add_mark(v, Gtk.PositionType.BOTTOM, None)
        scale.connect("value-changed", self._on_scale_changed)
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
        self._sync_preview()

    def _sync_preview(self):
        s = self.settings
        e = EFFECTS_BY_KEY[s.effect]
        p = self.preview
        p.effect, p.rgb, p.speed, p.brightness = s.effect, hex_to_rgb(s.color), s.speed, s.brightness
        self.effect_title.set_label(e.label)
        self.effect_sub.set_label(DESCRIPTIONS[e.key])
        self.color_row.set_sensitive(e.uses_color)
        self.swatch_row.set_sensitive(e.uses_color)
        self.speed_row.set_sensitive(e.uses_speed)
        self.bright_row.set_sensitive(e.key != "off")

    def _changed(self):
        if self._loading:
            return
        self._sync_preview()
        if self.live_row.get_active():
            self._schedule_apply()

    def _on_effect_toggled(self, check, key):
        if check.get_active():
            self.settings.effect = key
            self._changed()

    def _on_color_changed(self, button, _pspec):
        c = button.get_rgba()
        self.settings.color = rgb_to_hex((round(c.red * 255), round(c.green * 255), round(c.blue * 255)))
        self._changed()

    def _on_swatch(self, _btn, hexcol):
        rgba = Gdk.RGBA()
        rgba.parse(hexcol)
        self.color_button.set_rgba(rgba)  # triggers _on_color_changed

    def _on_scale_changed(self, _scale):
        self.settings.speed = int(round(self.speed_scale.get_value()))
        self.settings.brightness = int(round(self.bright_scale.get_value()))
        self._changed()

    # -- device --------------------------------------------------------
    def refresh_device(self):
        try:
            devices = find_devices()
        except DeviceError as exc:
            devices = []
            self.banner.set_title(str(exc))
        if devices:
            self.title.set_subtitle(f"{devices[0].name} · connesso")
            self.banner.set_revealed(False)
        else:
            self.title.set_subtitle("Mouse non trovato")
            self.banner.set_title("Nessun Redragon M711 rilevato. Collega il mouse e premi Riprova.")
            self.banner.set_revealed(True)

    def _schedule_apply(self):
        # Debounce: sliders and colour picker fire many events.
        if self._pending:
            GLib.source_remove(self._pending)
        self._pending = GLib.timeout_add(220, self._debounced_apply)

    def _debounced_apply(self):
        self._pending = None
        self.apply(show_toast=False)
        return GLib.SOURCE_REMOVE

    def apply(self, show_toast: bool):
        s = Settings(**vars(self.settings))
        s.save()

        def worker():
            with self._apply_lock:
                try:
                    with CobraMouse() as mouse:
                        mouse.set_lighting(s.effect, hex_to_rgb(s.color), s.speed, s.brightness)
                    GLib.idle_add(self._applied, None, show_toast)
                except DeviceError as exc:
                    GLib.idle_add(self._applied, exc, show_toast)

        threading.Thread(target=worker, daemon=True).start()

    def _applied(self, error, show_toast):
        if error is None:
            self.banner.set_revealed(False)
            if show_toast:
                self.toasts.add_toast(Adw.Toast(title="Impostazioni applicate", timeout=2))
            return False
        if isinstance(error, DevicePermissionError):
            self.banner.set_title("Permessi USB mancanti: esegui  sudo ./install-udev.sh  e ricollega il mouse.")
            self.banner.set_revealed(True)
        elif isinstance(error, DeviceNotFound):
            self.refresh_device()
        else:
            self.toasts.add_toast(Adw.Toast(title=str(error), timeout=4))
        return False


def Gio_menu():
    from gi.repository import Gio

    menu = Gio.Menu()
    menu.append("Informazioni su Cobra RGB", "app.about")
    return menu


class CobraApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.connect("activate", self._on_activate)
        self.connect("startup", self._on_startup)

    def _on_startup(self, _app):
        from gi.repository import Gio

        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", self._on_about)
        self.add_action(about)

    def _on_activate(self, _app):
        win = self.props.active_window or CobraWindow(self)
        win.present()

    def _on_about(self, *_):
        dialog = Adw.AboutDialog(
            application_name="Cobra RGB",
            application_icon="input-mouse",
            version=__version__,
            comments="Configura i LED del Redragon M711 Cobra su Linux",
            license_type=Gtk.License.GPL_3_0,
            website="https://github.com/codingkoala/cobra-rgb",
            credits_section=None,
        )
        dialog.add_credit_section("Protocollo", ["dokutan/mouse_m908", "OpenRGB", "SK2674/m711-port"])
        dialog.present(self.props.active_window)


def main() -> int:
    return CobraApp().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
