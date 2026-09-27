# Gamepad App Launcher

A resident, gamepad-navigable launcher for **Kodi**, **Steam**, **YouTube (TV kiosk)** and **Brave**, designed for a GNOME/Wayland desktop (e.g. CachyOS). Close the launcher, launch an app from a tile, and when the app exits the launcher comes back to the front — no mouse required.

```
gamepad → AntiMicroX → arrow keys / Enter / Esc → GTK4 launcher
   ↑                ↑
Steam or Kodi running? → profile monitor flips AntiMicroX
to Set 2 (pass-through) so the gamepad drives the app natively
```

## Description

**Goal.** A single-screen, tile-based app menu you can drive entirely with a controller — a home-screen layer for a Linux desktop tuned for couch/kiosk use. The launcher stays resident in the background: closing the window only *hides* it, and re-launching it (or the moment your apps exit) brings that same window back to the front.

**Technical implementation** — three cooperating modules:

| Module | Role |
|---|---|
| `launcher.py` | The UI. A GTK4 / libadwaita `GApplication` (`com.cachyos.GamepadLauncher`) showing a `Gtk.FlowBox` of circular tiles (Kodi, Steam, YouTube, Brave) over a background wallpaper (`icons/wallpaper.*`). Navigation is pure keyboard focus (arrow keys, Enter to launch, Esc to dismiss), which is what makes it gamepad-friendly. A background thread polls process state every 2 s via `proc_utils.scan_status()` and hands the result back to the GTK main loop with `GLib.idle_add`, so `/proc` I/O never blocks the UI. While a target app is running, its tile shows a green "running" dot; when **all** target apps exit, the launcher re-presents itself automatically. |
| `profile_monitor.py` | An independent daemon (runs even when the launcher window is closed). It watches for Steam or Kodi via `/proc` and, over D-Bus (`io.github.antimicrox` → `InputDevice.setActiveSetNumber`), switches AntiMicroX sets: **Set 1** (navigation mappings) when no full app is running, **Set 2** (blank) while Steam/Kodi runs so the gamepad passes straight through to the app's native controller support. This deliberately avoids AntiMicroX's "auto profile per window" feature, which is **not supported on Wayland**. |
| `proc_utils.py` | Shared detection helpers built on raw `/proc/<pid>/comm` + `/proc/<pid>/cmdline` (no psutil). Recognises Kodi, Steam (`steam`/`steamwebhelper`) and Brave — and disambiguates the **YouTube TV kiosk** from a normal Brave window by looking for the dedicated profile marker (`BraveYouTubeTV`) in the kiosk's `--user-data-dir` argument. Running the file directly (`python3 proc_utils.py`) prints the live detection state as a self-test. |

The launcher itself only ever deals in **plain keyboard input** — all gamepad→key translation is AntiMicroX's job, which keeps the app simple and input-agnostic.

## Prerequisites

**System & session**
- A **Wayland** session (GNOME or a compatible compositor) — this is a GTK4/libadwaita app.
- Linux (developed on **CachyOS**).

**Runtime**
- **Python 3** with **PyGObject** (`gi`), providing `Gtk 4.0`, `Adw 1`, `Gio`, `GLib`.
- **AntiMicroX** installed and running, with a controller connected, configured in **Set 1** to map:
  - D-Pad / left stick → arrow keys
  - A / South → Enter
  - B / East → Escape
- The target apps installed: **Kodi**, **Steam**, **Brave**.

**YouTube TV kiosk (for the YouTube tile)**
- A launcher script at `~/.local/bin/youtube-tv.sh` that starts Brave in kiosk mode using a **dedicated user profile** whose `--user-data-dir` path contains the marker `BraveYouTubeTV` — this marker is how `proc_utils.py` distinguishes the kiosk from a normal Brave window. Without it, the YouTube tile's running-detection and duplicate-launch guard won't work.

**Artwork (optional)**
- A wallpaper image at `icons/wallpaper.{svg,png,jpg,jpeg,webp}` used as the background after a dark scrim; if absent, the theme background is used.
- App tiles prefer system icon-theme icons (`kodi`, `steam`, `brave-*`); the YouTube tile looks for `icons/youtube.{svg,png,jpg,jpeg,webp}`, falling back to a placeholder.

## How to use

**1. Start the profile monitor (background daemon).**

```bash
python3 profile_monitor.py
```

Point it at a desktop autostart entry or a `systemd --user` service so it runs continuously. Log lines confirm each time it flips AntiMicroX between Set 1 and Set 2.

**2. Launch the app launcher.**

```bash
python3 launcher.py
```

Navigation is purely keyboard (gamepad via AntiMicroX Set 1):

| Input | Action |
|---|---|
| Arrow keys (D-Pad / left stick) | Move between tiles |
| Enter (A / South) | Launch the focused app |
| Escape (B / East) | Dismiss / hide the launcher (stays resident) |
| `Ctrl+Q` | Actually quit the launcher |
| `F11` | Toggle fullscreen |

**Day-to-day flow**
- Launch **Kodi** or **Steam** from a tile → the profile monitor switches AntiMicroX to Set 2 so the controller drives the app natively; the tile keeps its green running dot.
- Quit the app and the profile monitor switches back to Set 1, and the launcher **re-presents itself automatically**.
- **Brave** and the **YouTube kiosk** are detected independently; the YouTube tile blocks a duplicate kiosk launch (it uses its own profile, so a second instance would open a competing window rather than being absorbed) and shows a toast instead.

**3. Verify detection (self-test).**

```bash
python3 proc_utils.py
```

Prints the live state of Steam / Kodi / Brave / YouTube detection plus the two decision values the app uses: `steam_or_kodi` (→ suspend AntiMicroX) and `any_target` (→ keep the launcher hidden). If a process name doesn't match your local binary, extend the `*_NAMES` sets in `proc_utils.py`.

**Notes & limits**
- The launcher is **resident by design** — closing the window hides it, it does not exit; use `Ctrl+Q` to end the session.
- Because it's a `GApplication` with a unique ID, a second `python3 launcher.py` (e.g. clicking the desktop icon) re-focuses the existing window instead of spawning a copy.
- The YouTube kiosk tile is guarded against duplicate launches (dedicated-profile Brave instance).
