import subprocess, json, re
from typing import Optional

__all__ = ["get_record_shortcut"]

def _probe_gnome() -> Optional[str]:
    """Return binding string if GNOME custom keybinding executes voxt trigger."""
    try:
        paths_raw = subprocess.check_output([
            "gsettings", "get",
            "org.gnome.settings-daemon.plugins.media-keys",
            "custom-keybindings",
        ], text=True)
        # Output looks like "@as []" or  "[ '/org/gnome/.../custom0/', ... ]"
        paths_raw = paths_raw.strip()
        if not paths_raw or paths_raw == "@as []":
            return None
        paths = json.loads(paths_raw.replace("'", '"'))
        for p in paths:
            cmd = subprocess.check_output(["gsettings", "get", p, "command"], text=True).strip("' \n")
            if "voxt --trigger-record" in cmd:
                key = subprocess.check_output(["gsettings", "get", p, "binding"], text=True).strip("' \n")
                return key
    except Exception:
        return None
    return None

def _probe_kde() -> Optional[str]:
    """Probe KDE GlobalAccel via qdbus."""
    try:
        out = subprocess.check_output([
            "qdbus", "org.kde.kglobalaccel", "/component/voxt",
            "org.kde.kglobalaccel.Component.shortcutList"], text=True)
        m = re.search(r"voxt --trigger-record.*key:\s*([^\n]+)", out)
        if m:
            return m.group(1).strip()
    except Exception:
        return None
    return None

def get_record_shortcut() -> Optional[str]:
    """Return the keybinding string for the voxt trigger shortcut, or None."""
    for fn in (_probe_gnome, _probe_kde):
        key = fn()
        if key:
            return key
    return None 