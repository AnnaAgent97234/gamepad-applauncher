#!/usr/bin/env python3
"""
Shared helpers for detecting whether Kodi / Steam / Brave (normal or the
YouTube-TV kiosk) are currently running.

Implemented with plain /proc parsing so the only runtime dependency stays
PyGObject (which is already required for GTK4 / D-Bus) - no psutil needed.

Run this file directly to print the current detection state, useful for
verifying everything matches your actual process names before wiring up
the rest of the system:

    python3 proc_utils.py
"""
import os

# Process name candidates (as seen in /proc/<pid>/comm, max 15 chars).
# Extend these if `python3 proc_utils.py` shows your binaries use different names.
STEAM_NAMES = {"steam", "steamwebhelper"}
KODI_NAMES = {"kodi", "kodi.bin", "kodi-standalone"}
BRAVE_NAMES = {"brave", "brave-browser"}

# Must match the --user-data-dir marker used in youtube-tv.sh, so we can tell
# the YouTube-TV kiosk apart from a normal Brave window (both are process
# name "brave").
YOUTUBE_PROFILE_MARKER = "BraveYouTubeTV"


def _iter_procs():
    """Yield (comm_name, cmdline_list) for every readable process."""
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/comm", "r") as f:
                name = f.read().strip()
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue

        cmdline = []
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                raw = f.read()
            if raw:
                cmdline = raw.decode(errors="replace").rstrip("\x00").split("\x00")
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass

        yield name.strip().lower(), cmdline


def is_any_running(names):
    for name, _ in _iter_procs():
        if name in names:
            return True
    return False


def steam_or_kodi_running():
    """The condition that should suspend (blank) the AntiMicroX profile."""
    return is_any_running(STEAM_NAMES) or is_any_running(KODI_NAMES)


def youtube_kiosk_running():
    """True if the youtube-tv.sh kiosk instance specifically is running."""
    for name, cmdline in _iter_procs():
        if name in BRAVE_NAMES and any(YOUTUBE_PROFILE_MARKER in arg for arg in cmdline):
            return True
    return False


def brave_normal_running():
    """True if a Brave process is running that is NOT the YouTube-TV kiosk."""
    for name, cmdline in _iter_procs():
        if name in BRAVE_NAMES and not any(YOUTUBE_PROFILE_MARKER in arg for arg in cmdline):
            return True
    return False


def brave_running_any():
    return is_any_running(BRAVE_NAMES)


def any_target_app_running():
    """Used by the launcher to decide whether it should re-present itself."""
    return steam_or_kodi_running() or brave_running_any()


def scan_status():
    """Single /proc pass returning every detection result at once.

    The individual helpers above (steam_or_kodi_running, brave_running_any,
    etc.) are each a full /proc scan on their own, so calling several of them
    back-to-back (as a naive poll loop would) re-scans /proc repeatedly for
    no reason. Anything that needs more than one of these values in the same
    poll tick (the launcher's periodic UI refresh, the profile monitor)
    should call this instead and read off the dict.
    """
    steam = False
    kodi = False
    youtube = False
    brave = False

    for name, cmdline in _iter_procs():
        if name in STEAM_NAMES:
            steam = True
        elif name in KODI_NAMES:
            kodi = True
        elif name in BRAVE_NAMES:
            if any(YOUTUBE_PROFILE_MARKER in arg for arg in cmdline):
                youtube = True
            else:
                brave = True

    return {
        "kodi": kodi,
        "steam": steam,
        "youtube": youtube,
        "brave": brave,
        "steam_or_kodi": steam or kodi,
        "any_target": steam or kodi or youtube or brave,
    }


if __name__ == "__main__":
    print("Steam running       :", is_any_running(STEAM_NAMES))
    print("Kodi running         :", is_any_running(KODI_NAMES))
    print("Brave (any) running   :", brave_running_any())
    print("  - YouTube-TV kiosk  :", youtube_kiosk_running())
    print("  - normal Brave      :", brave_normal_running())
    print()
    print("steam_or_kodi_running() [suspends AntiMicroX] :", steam_or_kodi_running())
    print("any_target_app_running() [keeps launcher hidden] :", any_target_app_running())
    print()
    print("scan_status() [single-pass, used by the hot poll loops]:")
    print(" ", scan_status())
