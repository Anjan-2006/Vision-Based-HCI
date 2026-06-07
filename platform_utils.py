"""
Platform Utilities — Cross-platform abstraction for brightness, volume, and environment analysis.
Supports Linux (Ubuntu/X11/Wayland) and macOS (Apple Silicon / Intel).
"""

import platform
import subprocess
import shutil
import os
import cv2
import numpy as np
import threading
import time

# Detect platform once at import time
PLATFORM = platform.system()  # "Linux" or "Darwin"

# Rate limiting: track last command times to prevent flooding
_last_brightness_time = 0
_last_brightness_value = -1
_BRIGHTNESS_MIN_INTERVAL = 0.15  # Max ~6-7 brightness changes per second

_last_volume_time = 0
_VOLUME_MIN_INTERVAL = 0.1


# =============================================
# BACKEND AUTO-DETECTION
# =============================================

def _detect_brightness_backend():
    """Auto-detect the first working brightness backend on the system."""
    if PLATFORM == "Linux":
        # Priority: GNOME dbus > brightnessctl > xrandr
        # Check if GNOME SettingsDaemon is available (works on both Wayland and X11)
        try:
            result = subprocess.run(
                "gdbus call --session --dest org.gnome.SettingsDaemon.Power "
                "--object-path /org/gnome/SettingsDaemon/Power "
                "--method org.freedesktop.DBus.Properties.Get "
                "org.gnome.SettingsDaemon.Power.Screen Brightness",
                shell=True, capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0 and "<" in result.stdout:
                print("[PLATFORM] BRIGHTNESS BACKEND: gnome-dbus (hardware backlight)")
                return "gnome_dbus"
        except Exception:
            pass

        if shutil.which("brightnessctl"):
            print("[PLATFORM] BRIGHTNESS BACKEND: brightnessctl")
            return "brightnessctl"
        elif shutil.which("xrandr"):
            print("[PLATFORM] BRIGHTNESS BACKEND: xrandr (software gamma only)")
            return "xrandr"
        else:
            print("[PLATFORM] WARNING: No brightness backend found!")
            return None
    elif PLATFORM == "Darwin":
        if shutil.which("brightness"):
            print("[PLATFORM] BRIGHTNESS BACKEND: brightness (CLI)")
            return "brightness_cli"
        else:
            print("[PLATFORM] BRIGHTNESS BACKEND: osascript (macOS)")
            return "osascript"
    return None


def get_display_name():
    """Get the primary display name for xrandr on Linux."""
    if PLATFORM != "Linux":
        return None
    try:
        result = subprocess.run(
            "xrandr --listmonitors | grep '+' | head -1 | awk '{print $NF}'",
            shell=True, capture_output=True, text=True, timeout=3
        )
        name = result.stdout.strip()
        if name:
            print(f"[PLATFORM] DISPLAY: {name}")
            return name
        return "eDP-1"
    except Exception:
        return "eDP-1"


# Cache at import time
_LINUX_DISPLAY = get_display_name() if PLATFORM == "Linux" else None
_BRIGHTNESS_BACKEND = _detect_brightness_backend()

# Session type for informational logging
_SESSION_TYPE = os.environ.get("XDG_SESSION_TYPE", "unknown")
print(f"[PLATFORM] SESSION: {_SESSION_TYPE}")


# =============================================
# NON-BLOCKING COMMAND EXECUTION
# =============================================

def _run_async(cmd):
    """Fire-and-forget: run command in background thread."""
    def _exec():
        try:
            subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, timeout=5)
        except Exception:
            pass
    thread = threading.Thread(target=_exec, daemon=True)
    thread.start()


# =============================================
# BRIGHTNESS CONTROL
# =============================================

def set_brightness(percent):
    """
    Set REAL hardware screen brightness (0-100).
    Uses GNOME D-Bus on Ubuntu (works on Wayland + X11).
    Rate-limited to prevent flooding.
    """
    global _last_brightness_time, _last_brightness_value

    percent = max(5, min(100, int(percent)))

    # Rate limit: skip if called too frequently with same value
    now = time.time()
    if (now - _last_brightness_time) < _BRIGHTNESS_MIN_INTERVAL:
        return
    if percent == _last_brightness_value:
        return

    _last_brightness_time = now
    _last_brightness_value = percent

    if _BRIGHTNESS_BACKEND is None:
        return

    if _BRIGHTNESS_BACKEND == "gnome_dbus":
        # GNOME SettingsDaemon D-Bus — controls REAL hardware backlight
        cmd = (f'gdbus call --session '
               f'--dest org.gnome.SettingsDaemon.Power '
               f'--object-path /org/gnome/SettingsDaemon/Power '
               f'--method org.freedesktop.DBus.Properties.Set '
               f'org.gnome.SettingsDaemon.Power.Screen Brightness '
               f'"<int32 {percent}>"')
    elif _BRIGHTNESS_BACKEND == "brightnessctl":
        cmd = f"brightnessctl set {percent}%"
    elif _BRIGHTNESS_BACKEND == "xrandr":
        val = max(0.1, percent / 100.0)
        cmd = f"xrandr --output {_LINUX_DISPLAY} --brightness {val:.2f}"
    elif _BRIGHTNESS_BACKEND == "brightness_cli":
        val = percent / 100.0
        cmd = f"brightness {val:.2f}"
    elif _BRIGHTNESS_BACKEND == "osascript":
        val = percent / 100.0
        cmd = f"osascript -e 'do shell script \"brightness {val:.2f}\"' 2>/dev/null"
    else:
        return

    print(f"[BRIGHTNESS] SETTING: {percent}%")
    _run_async(cmd)


# =============================================
# VOLUME CONTROL
# =============================================

def set_volume(percent):
    """
    Set system volume (0-100). Non-blocking, rate-limited.
    """
    global _last_volume_time

    percent = max(0, min(100, int(percent)))

    now = time.time()
    if (now - _last_volume_time) < _VOLUME_MIN_INTERVAL:
        return
    _last_volume_time = now

    if PLATFORM == "Linux":
        cmd = (f"amixer set Master {percent}% > /dev/null 2>&1 || "
               f"amixer -D pulse sset Master {percent}% > /dev/null 2>&1")
    elif PLATFORM == "Darwin":
        cmd = f"osascript -e 'set volume output volume {percent}'"
    else:
        return

    _run_async(cmd)


# =============================================
# ENVIRONMENT ANALYSIS
# =============================================

def analyze_frame_brightness(frame):
    """
    Analyze the ambient brightness of a camera frame.
    Returns a value 0-255 representing mean brightness.
    Extremely lightweight — uses cv2.mean on grayscale.
    """
    if frame is None:
        return 128  # Neutral default
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mean_val = cv2.mean(gray)[0]
    return mean_val


def get_platform_name():
    """Return a human-friendly platform string."""
    if PLATFORM == "Linux":
        return "LINUX"
    elif PLATFORM == "Darwin":
        return "macOS"
    return PLATFORM.upper()
