# Gamepad App Launcher

A resident, gamepad-navigable launcher for **Kodi**, **Steam**, **YouTube (TV)**
and **Brave**, built for GNOME/Wayland (e.g. CachyOS). Pick an app and launch it
with a controller; when it closes, the launcher returns to the front. No mouse.

```
 gamepad → AntiMicroX → arrows / Enter / Esc → GTK4 launcher
 Steam or Kodi running? → profile monitor switches AntiMicroX to
 pass-through, so the gamepad controls the app directly
```

## How it works

| Module | Role |
|---|---|
| `launcher.py` | GTK4/libadwaita UI: tile grid, wallpaper, keyboard nav, launch + running state. Polls app state on a background thread and applies it on the GTK loop via `GLib.idle_add`, so I/O never blocks the UI. |
| `profile_monitor.py` | Daemon. While Steam/Kodi runs, switches AntiMicroX (D-Bus `setActiveSetNumber`) to a pass-through set; otherwise restores navigation. Works around AntiMicroX auto-per-window profiles, unsupported on Wayland. |
| `proc_utils.py` | `/proc`-only detection (no psutil). Distinguishes the YouTube-TV kiosk from a normal Brave window via a dedicated-profile marker. |

Resident by design: closing the window **hides** it (`Ctrl+Q` quits). Tiles are
keyboard-focused, which keeps them gamepad-friendly. The launcher only handles
keyboard input — gamepad translation is AntiMicroX's job.

## Prerequisites

- **Wayland** session (GNOME or equivalent), on Linux (developed on CachyOS).
- **Python 3** + **PyGObject** (`Gtk 4.0`, `Adw 1`).
- **AntiMicroX** running, controller connected, **Set 1** mapped: arrows, A→Enter, B→Escape.
- Target apps installed: **Kodi**, **Steam**, **Brave**.
- **YouTube tile**: `~/.local/bin/youtube-tv.sh` launching Brave kiosk with a dedicated profile (see below).
- Optional: `icons/wallpaper.*` and `icons/youtube.*`.

## Usage

```bash
python3 profile_monitor.py   # run as a background / autostart daemon
python3 launcher.py          # the launcher window
python3 proc_utils.py        # self-test: prints live detection state
```

| Input | Action |
|---|---|
| Arrows (D-pad / stick) | Move between tiles |
| Enter (A) | Launch the focused app |
| Escape (B) | Hide launcher (stays resident) |
| `Ctrl+Q` | Quit |
| `F11` | Toggle fullscreen |

When Kodi or Steam closes, the launcher re-presents itself automatically.

## Adding a new app

Add an entry to the `APPS` list in `launcher.py`:

```python
{
    "id": "myapp",                          # unique id (tile key)
    "label": "My App",
    "icon_names": ["myapp"],                # system icon-theme name(s)
    "command": ["myapp"],                   # argv list to launch
    "is_running": lambda: proc_utils.is_any_running({"myapp"}),
}
```

Steps: (1) `command` is the argv list executed via `Gio.Subprocess`; (2) `is_running`
calls `proc_utils.is_any_running()` with your binary's `/proc/<pid>/comm` name
(add it to `proc_utils.py` if missing); (3) for a non-system icon, drop
`icons/<id>.{svg,png,…}` (same mechanism as the YouTube tile). Tiles, navigation
and running-state pick the new entry up automatically.

## YouTube vs. the other apps

YouTube is **not a separate app** — it's a Brave instance run as a TV kiosk
(`youtube-tv.sh`) using its own dedicated profile. That creates two special
cases the other tiles don't have:

- **Detection** — both the kiosk and a normal Brave window show as the process
  `brave`. `proc_utils.py` tells them apart by inspecting `cmdline` for a marker
  in `--user-data-dir` (`BraveYouTubeTV`), so the two tiles track independently.
- **Duplicate launch** — relaunching an already-open app is usually harmless
  (re-focus), but a second kiosk profile would open a competing window. The
  YouTube tile guards against this and shows a toast instead.
