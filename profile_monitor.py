#!/usr/bin/env python3
"""
gamepad-profile-monitor

Independent daemon (runs regardless of whether the Launcher app is open).

Watches for Steam or Kodi. While either is running, it tells the already
running AntiMicroX instance (over D-Bus) to switch to Set 2 (blank), so the
gamepad passes straight through to Steam/Kodi's own native controller
support. When neither is running, it switches back to Set 1 (the navigation
mappings used by the Launcher).

This does NOT rely on AntiMicroX's "auto profile per window" feature, which
is not supported on Wayland - it uses AntiMicroX's documented D-Bus API
instead (io.github.antimicrox / InputDevice.setActiveSetNumber).
"""
import logging
import os
import sys
import time

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proc_utils

ANTIMICROX_BUS_NAME = "io.github.antimicrox"
ANTIMICROX_IFACE = "io.github.antimicrox.InputDevice"
MAX_DEVICE_PROBE = 5          # how many /InputDevice/N objects to try
DBUS_CALL_TIMEOUT_MS = 2000

SET_NAV = 0     # Set 1 (1-based "Set 1" in the UI) - navigation mappings
SET_BLANK = 1   # Set 2 (1-based "Set 2" in the UI) - blank / pass-through

POLL_INTERVAL_SECONDS = 2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s gamepad-profile-monitor %(levelname)s: %(message)s",
)
log = logging.getLogger(__name__)


class AntiMicroXController:
    """Thin wrapper around the AntiMicroX D-Bus InputDevice interface."""

    def __init__(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.device_index = None

    def _call(self, index, method, args=None):
        return self.bus.call_sync(
            ANTIMICROX_BUS_NAME,
            f"/InputDevice/{index}",
            ANTIMICROX_IFACE,
            method,
            args,
            None,
            Gio.DBusCallFlags.NONE,
            DBUS_CALL_TIMEOUT_MS,
            None,
        )

    def _discover_device(self):
        for index in range(MAX_DEVICE_PROBE):
            try:
                result = self._call(index, "getSDLName")
                name = result.unpack()[0]
                log.info("Found controller at /InputDevice/%d: %s", index, name)
                return index
            except GLib.Error:
                continue
        return None

    def set_active_set(self, set_number):
        if self.device_index is None:
            self.device_index = self._discover_device()
            if self.device_index is None:
                log.warning(
                    "No AntiMicroX controller found on D-Bus yet "
                    "(is antimicrox running and is the gamepad connected?)"
                )
                return False
        try:
            self._call(
                self.device_index,
                "setActiveSetNumber",
                GLib.Variant("(i)", (set_number,)),
            )
            return True
        except GLib.Error as e:
            log.warning(
                "D-Bus call to AntiMicroX failed (%s) - will re-discover the device",
                e.message,
            )
            self.device_index = None
            return False


def main():
    log.info("Starting - polling every %ss for Steam/Kodi", POLL_INTERVAL_SECONDS)
    controller = AntiMicroXController()
    last_state = None  # None = unknown yet, force an initial sync

    while True:
        suspended = proc_utils.scan_status()["steam_or_kodi"]

        if suspended != last_state:
            target_set = SET_BLANK if suspended else SET_NAV
            if controller.set_active_set(target_set):
                log.info(
                    "Steam/Kodi %s -> AntiMicroX switched to %s",
                    "detected" if suspended else "no longer running",
                    "Set 2 (blank)" if suspended else "Set 1 (navigation)",
                )
                last_state = suspended
            # If the D-Bus call failed we deliberately leave last_state as-is
            # so we keep retrying every loop until AntiMicroX/the controller
            # becomes reachable.

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
