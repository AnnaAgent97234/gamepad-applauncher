#!/usr/bin/env python3
"""
Gamepad Launcher

Native GTK4 / libadwaita launcher for Kodi, Steam, YouTube (TV) and Brave.
Navigable with a gamepad via AntiMicroX Set 1, which is expected to map:

    D-Pad / left stick  -> Arrow keys
    A / South button    -> Enter
    B / East button     -> Escape

The app itself only ever deals in plain keyboard input; all gamepad-to-key
translation is AntiMicroX's job.

Behaviour:
  - A background thread polls every 2s for whether Kodi/Steam/Brave (which
    covers both the "Brave" tile and the YouTube-TV kiosk) are still
    running, doing a single /proc scan per tick (see proc_utils.scan_status).
    Results are handed back to the GTK main thread via GLib.idle_add, so the
    polling itself never blocks the UI. The moment none of the target apps
    are running, the launcher re-presents itself.
  - Closing the window hides it instead of quitting (it's meant to stay
    resident). Ctrl+Q quits for real.
  - Because this is a GApplication with a unique application ID, invoking
    it again (e.g. clicking its icon in the GNOME app grid) will simply
    re-present the existing window rather than starting a second copy -
    a handy manual "bring launcher to front" button if you ever need one.
  - The background is a static image you provide at icons/wallpaper.*
    (any of svg/png/jpg/jpeg/webp), loaded once at startup.
"""
import os
import sys
import threading
from pathlib import Path
import glob

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proc_utils

APP_ID = "com.cachyos.GamepadLauncher"
APP_DIR = Path(__file__).resolve().parent
ICONS_DIR = APP_DIR / "icons"

TILE_ICON_SIZE = 72
TILE_SIZE = 200
POLL_INTERVAL_SECONDS = 2

APPS = [
    {
        "id": "kodi",
        "label": "Kodi",
        "icon_names": ["kodi"],
        "command": ["kodi"],
        "is_running": lambda: proc_utils.is_any_running(proc_utils.KODI_NAMES),
    },
    {
        "id": "steam",
        "label": "Steam",
        "icon_names": ["steam"],
        "command": ["steam"],
        "is_running": lambda: proc_utils.is_any_running(proc_utils.STEAM_NAMES),
    },
    {
        "id": "youtube",
        "label": "YouTube",
        "icon_base": "youtube",  # looked up as icons/youtube.{svg,png,jpg,...}
        "command": [str(Path.home() / ".local/bin/youtube-tv.sh")],
        "is_running": proc_utils.youtube_kiosk_running,
        # youtube-tv.sh uses its own dedicated browser profile, so unlike
        # Steam/Kodi/Brave, launching it again while already open would
        # actually spawn a second competing kiosk window instead of being
        # harmlessly ignored - so we guard against that specifically.
        "guard_duplicate": True,
    },
    {
        "id": "brave",
        "label": "Brave",
        "icon_names": ["brave-browser", "brave-desktop", "brave"],
        "command": ["brave"],
        "is_running": proc_utils.brave_normal_running,
    },
]

CSS = b"""
.launcher-scrim {
    background-color: alpha(black, 0.32);
}
.launcher-tile {
    padding: 20px;
    border-radius: 50%;
    background-color: alpha(black, 0.28);
}
.launcher-tile:focus, .launcher-tile:selected {
    background-color: alpha(@accent_bg_color, 0.45);
    outline: 3px solid @accent_color;
    outline-offset: -3px;
}
.launcher-tile.running .running-dot {
    opacity: 1;
}
.running-dot {
    opacity: 0;
    color: @success_color;
    font-size: 10px;
}
.launcher-title {
    font-size: 1.45em;
    margin-top: 10px;
    font-weight: bold;
    color: #ffffff;
    text-shadow: 0 1px 4px rgba(0, 0, 0, 0.7);
}
"""

LOCAL_ICON_EXTENSIONS = ["svg", "png", "jpg", "jpeg", "webp"]

# Some packages (notably several AUR-packaged browsers) only ship an
# unthemed icon under /usr/share/pixmaps, which GTK4's icon theme lookup
# does NOT search by default - only properly "hicolor"-themed icons are
# found automatically. We add pixmaps to the search path AND, as a last
# resort, glob these directories directly for a matching file.
SYSTEM_ICON_GLOBS = [
    "/usr/share/pixmaps/{name}.{ext}",
    "/usr/share/icons/hicolor/*/apps/{name}.{ext}",
    "/usr/local/share/icons/hicolor/*/apps/{name}.{ext}",
    str(Path.home() / ".local/share/icons/hicolor/*/apps/{name}.{ext}"),
]


def find_local_icon_file(base_name):
    """Look for icons/<base_name>.<ext> for any supported extension.

    Used both for app icons (youtube.*) and for the background image
    (wallpaper.*) so there's a single place that defines "how do we look up
    a user-provided image by base name".
    """
    for ext in LOCAL_ICON_EXTENSIONS:
        candidate = ICONS_DIR / f"{base_name}.{ext}"
        if candidate.exists():
            return candidate
    return None


def find_system_icon_file(names):
    """Manual filesystem fallback for icons the running icon theme misses."""
    for name in names:
        for ext in ("svg", "png"):
            for pattern in SYSTEM_ICON_GLOBS:
                for match in glob.glob(pattern.format(name=name, ext=ext)):
                    return Path(match)
    return None


def _image_from_file(path, pixel_size):
    img = Gtk.Image.new_from_file(str(path))
    img.set_pixel_size(pixel_size)
    return img


def load_icon_image(app_entry, pixel_size=TILE_ICON_SIZE):
    icon_base = app_entry.get("icon_base")
    if icon_base:
        local_file = find_local_icon_file(icon_base)
        if local_file:
            return _image_from_file(local_file, pixel_size)
        print(f"[launcher] no {icon_base}.* file found in {ICONS_DIR}", file=sys.stderr)

    names = app_entry.get("icon_names", [])
    display = Gdk.Display.get_default()
    theme = Gtk.IconTheme.get_for_display(display)
    for name in names:
        if theme.has_icon(name):
            img = Gtk.Image.new_from_icon_name(name)
            img.set_pixel_size(pixel_size)
            return img

    system_file = find_system_icon_file(names)
    if system_file:
        return _image_from_file(system_file, pixel_size)

    print(
        f"[launcher] no icon found for '{app_entry['id']}' (tried {names}), using a placeholder",
        file=sys.stderr,
    )
    img = Gtk.Image.new_from_icon_name("application-x-executable")
    img.set_pixel_size(pixel_size)
    return img


class LauncherWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Launcher")
        self.set_default_size(1280, 650)

        self.tiles = {}  # app_id -> Gtk.FlowBoxChild

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())

        self.toast_overlay = Adw.ToastOverlay()

        # Adw.Clamp's job is constraining WIDTH (it centers a column when
        # the window is wider than maximum-size) - it is not a general
        # purpose 2D-centering container, and asking it to also vertically
        # center itself via valign is not what it's built/tested for, which
        # is what made the outer centering unreliable. So: let the clamp
        # simply FILL all available height (its real job stays width-only),
        # and let the FlowBox itself - a plain, standard widget that
        # reliably respects valign/halign - do the actual 2D centering
        # within whatever height that ends up being (the window's content
        # area, not the monitor).
        clamp = Adw.Clamp(maximum_size=1400)
        clamp.set_hexpand(True)
        clamp.set_vexpand(True)

        self.flowbox = Gtk.FlowBox(
            valign=Gtk.Align.CENTER,
            halign=Gtk.Align.CENTER,
            homogeneous=True,
            row_spacing=24,
            column_spacing=24,
            max_children_per_line=5,
            selection_mode=Gtk.SelectionMode.SINGLE,
        )
        self.flowbox.set_activate_on_single_click(True)
        self.flowbox.connect("child-activated", self._on_child_activated)

        for app_entry in APPS:
            self.flowbox.append(self._build_tile(app_entry))

        clamp.set_child(self.flowbox)
        self.toast_overlay.set_child(clamp)
        self.toast_overlay.set_hexpand(True)
        self.toast_overlay.set_vexpand(True)

        # A dark scrim over the wallpaper, purely for text/icon contrast.
        scrim_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True)
        scrim_box.add_css_class("launcher-scrim")
        scrim_box.append(self.toast_overlay)

        # The wallpaper itself. Deliberately a plain Gtk.Box styled with a
        # CSS background-image rather than a Gtk.Picture inside a
        # Gtk.Overlay: a Gtk.Overlay measures its own size from its MAIN
        # child only, so using the wallpaper Picture as that main child
        # made the window's natural size track the wallpaper's actual
        # pixel dimensions (i.e. close to your monitor's resolution) -
        # which is exactly why centering looked like it was based on the
        # desktop instead of the launcher window. A CSS background-image
        # never participates in layout/size measurement at all, so this
        # box's size is driven purely by its content (the tile grid), and
        # the wallpaper just fills whatever size that ends up being.
        self.background_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True)
        self.background_box.append(scrim_box)
        self._load_wallpaper()

        toolbar_view.set_content(self.background_box)
        self.set_content(toolbar_view)

        self.connect("close-request", self._on_close_request)

        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

        # Grab focus on the first tile once mapped, so a gamepad user can
        # navigate immediately without needing a mouse click first.
        self.connect("map", lambda *_: self.flowbox.child_focus(Gtk.DirectionType.TAB_FORWARD))

    def _load_wallpaper(self):
        """Static background image provided by the user (icons/wallpaper.*).

        Loaded once at startup - this is a fixed file you supply, not the
        live desktop wallpaper, so there's nothing to watch for changes.
        Applied as a CSS background-image (see class docstring above for
        why, vs. a Gtk.Picture) via a small runtime-generated CSS provider,
        since the actual file path is only known once the app is running.
        """
        path = find_local_icon_file("wallpaper")
        if not path:
            print(
                f"[launcher] no wallpaper.* file found in {ICONS_DIR} - "
                "using the default theme background",
                file=sys.stderr,
            )
            return

        uri = Gio.File.new_for_path(str(path)).get_uri()
        css = (
            ".launcher-wallpaper {"
            f'background-image: url("{uri}");'
            "background-size: cover;"
            "background-position: center;"
            "background-repeat: no-repeat;"
            "}"
        )
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode("utf-8"))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        self.background_box.add_css_class("launcher-wallpaper")

    def _build_tile(self, app_entry):
        # halign+valign=CENTER (rather than the box's default FILL) is what
        # actually centers the icon/label/dot both horizontally AND
        # vertically inside the tile's 200x200 area - a Box that fills its
        # allocation does NOT center its children within the extra space on
        # its own, it just leaves them packed at one end.
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=6,
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.CENTER,
        )
        box.append(load_icon_image(app_entry))

        label = Gtk.Label(label=app_entry["label"])
        label.add_css_class("launcher-title")
        box.append(label)

        dot = Gtk.Label(label="\u25cf")  # running indicator, invisible until state says so
        dot.add_css_class("running-dot")
        box.append(dot)

        child = Gtk.FlowBoxChild()
        child.set_child(box)
        child.add_css_class("launcher-tile")
        # Force an exact square: CSS min-width/min-height are only a floor,
        # and a longer label (e.g. "YouTube") could push the natural width
        # or height past 200px on its own, making the tile non-square -
        # which then makes the border-radius:50% circle lopsided and the
        # content look off-center inside it. set_size_request pins both
        # dimensions to exactly TILE_SIZE regardless of label width.
        child.set_size_request(TILE_SIZE, TILE_SIZE)
        child.app_entry = app_entry
        self.tiles[app_entry["id"]] = child
        return child

    def _on_key_pressed(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_F11:
            if self.is_fullscreen():
                self.unfullscreen()
            else:
                self.fullscreen()
            return True
        return False

    def _on_close_request(self, *_args):
        # Keep the launcher resident; hide instead of destroying it so it
        # can be re-presented later. Use Ctrl+Q to actually quit.
        self.set_visible(False)
        return True

    def _on_child_activated(self, flowbox, child):
        self.launch_app(child.app_entry)

    def launch_app(self, app_entry):
        if app_entry.get("guard_duplicate") and app_entry["is_running"]():
            self._toast(f"{app_entry['label']} is already running")
            return

        command = app_entry["command"]
        try:
            Gio.Subprocess.new(command, Gio.SubprocessFlags.NONE)
        except GLib.Error as e:
            self._toast(f"Failed to launch {app_entry['label']}: {e.message}")
            print(f"[launcher] failed to launch {command}: {e.message}", file=sys.stderr)

    def _toast(self, message):
        self.toast_overlay.add_toast(Adw.Toast.new(message))

    def apply_running_state(self, running_map):
        """Apply a precomputed {app_id: bool} map to the tiles' CSS state.

        Takes the result of a single proc_utils.scan_status() call (done on
        a background thread) rather than each tile independently re-scanning
        /proc, which is what made the old per-tile refresh redundant.
        """
        for app_id, child in self.tiles.items():
            if running_map.get(app_id):
                child.add_css_class("running")
            else:
                child.remove_css_class("running")


class LauncherApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.window = None
        self._was_running = False
        self._poll_stop = threading.Event()
        self._poll_thread = None

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Control>q"])

    def do_activate(self):
        if not self.window:
            style_provider = Gtk.CssProvider()
            style_provider.load_from_data(CSS)
            display = Gdk.Display.get_default()
            Gtk.StyleContext.add_provider_for_display(
                display,
                style_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
            # Some packages only ship an unthemed icon under /usr/share/pixmaps,
            # which isn't in GTK4's default icon theme search path.
            Gtk.IconTheme.get_for_display(display).add_search_path("/usr/share/pixmaps")

            self.window = LauncherWindow(self)
            self._was_running = proc_utils.scan_status()["any_target"]
            self._poll_thread = threading.Thread(target=self._poll_worker, daemon=True)
            self._poll_thread.start()

        self.window.present()

    def do_shutdown(self):
        # Signal the background poll thread to stop so it doesn't keep
        # scanning /proc (or try to touch a destroyed window) after quit.
        self._poll_stop.set()
        super().do_shutdown()

    def _poll_worker(self):
        """Runs on a background thread: all the /proc I/O happens here, off
        the GTK main thread, so a slow or busy system can never make the UI
        stutter. Only the plain-data result crosses back over, via
        GLib.idle_add, to actually touch any GTK widgets."""
        while not self._poll_stop.is_set():
            status = proc_utils.scan_status()
            GLib.idle_add(self._apply_poll_result, status)
            self._poll_stop.wait(POLL_INTERVAL_SECONDS)

    def _apply_poll_result(self, status):
        # Runs on the main thread (scheduled via GLib.idle_add) - safe to
        # touch GTK widgets here.
        running = status["any_target"]
        if self._was_running and not running:
            print("[launcher] all target apps closed - re-presenting launcher", file=sys.stderr)
            self.window.present()
        self._was_running = running
        self.window.apply_running_state(status)
        return GLib.SOURCE_REMOVE


def main():
    app = LauncherApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
