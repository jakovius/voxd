import sys
import argparse
import subprocess
import os
from pathlib import Path
if sys.version_info < (3, 9):
    print("[voxd] Python 3.9+ required. Please run the 'voxd' command (wrapper) so it can create/use a venv with a newer Python.")
    sys.exit(1)
from voxd.core.config import AppConfig

from voxd.paths import CONFIG_FILE, resource_path
from voxd.utils.libw import ORANGE, RESET
import shutil, yaml
import importlib.metadata

def _print_boxed(msg: str):
    """Print a single-line message inside a neat Unicode box.
    Supports ANSI-colored text by ignoring escape codes for width calc.
    """
    import re
    ansi = re.compile(r"\x1b\[[0-9;]*m")
    inner = f" {msg} "
    visible_len = len(ansi.sub('', inner))
    top = "┌" + "─" * visible_len + "┐"
    mid = "│" + inner + "│"
    bot = "└" + "─" * visible_len + "┘"
    print(top)
    print(mid)
    print(bot)

def ensure_user_config() -> dict:
    if not CONFIG_FILE.exists():
        default_tpl = resource_path("defaults/config.yaml")
        shutil.copy(default_tpl, CONFIG_FILE)
    return yaml.safe_load(CONFIG_FILE.read_text())

def _mic_autoset_if_enabled(cfg):
    """Best-effort: unmute default mic and set input gain to configured level.

    Uses wpctl → pactl → amixer if available. Silently skips on failure.
    """
    try:
        debug = bool(cfg.data.get("verbosity", False)) or bool(os.environ.get("VOXD_DEBUG_AUDIO"))
        def log(msg: str):
            if debug:
                print(f"[mic] {msg}")

        if not cfg.data.get("mic_autoset_enabled", False):
            log("autoset disabled; skipping")
            return
        try:
            level = float(cfg.data.get("mic_autoset_level", 0.40))
        except Exception:
            level = 0.40
        level = max(0.0, min(1.0, level))
        log(f"autoset enabled; target level={level:.2f}")

        def have(cmd: str) -> bool:
            found = shutil.which(cmd) is not None
            log(f"tool '{cmd}': {'found' if found else 'missing'}")
            return found

        # Prefer PipeWire's wpctl if present
        if have("wpctl"):
            try:
                log("trying wpctl … unmute")
                cp1 = subprocess.run(["wpctl", "set-mute", "@DEFAULT_SOURCE@", "0"],
                                     check=False, capture_output=True, timeout=2)
                log(f"wpctl set-mute rc={cp1.returncode}")
                log("trying wpctl … set-volume")
                cp2 = subprocess.run(["wpctl", "set-volume", "@DEFAULT_SOURCE@", f"{level:.2f}"],
                                     check=False, capture_output=True, timeout=2)
                log(f"wpctl set-volume rc={cp2.returncode}")
                return
            except Exception as e:
                log(f"wpctl path failed: {e}")

        # Fallback to PulseAudio pactl (also works on PipeWire's pulse shim)
        if have("pactl"):
            try:
                pct = str(int(round(level * 100))) + "%"
                log("trying pactl … unmute")
                cp1 = subprocess.run(["pactl", "set-source-mute", "@DEFAULT_SOURCE@", "0"],
                                     check=False, capture_output=True, timeout=2)
                log(f"pactl set-source-mute rc={cp1.returncode}")
                log(f"trying pactl … set-volume {pct}")
                cp2 = subprocess.run(["pactl", "set-source-volume", "@DEFAULT_SOURCE@", pct],
                                     check=False, capture_output=True, timeout=2)
                log(f"pactl set-source-volume rc={cp2.returncode}")
                return
            except Exception as e:
                log(f"pactl path failed: {e}")

        # Last resort: ALSA amixer (control names vary by card)
        if have("amixer"):
            try:
                pct = str(int(round(level * 100))) + "%"
                for ctl in ("Capture", "Mic"):
                    log(f"trying amixer on control '{ctl}' … {pct} unmute")
                    r = subprocess.run(["amixer", "-q", "set", ctl, pct, "unmute"],
                                       capture_output=True, timeout=2)
                    log(f"amixer rc={r.returncode}")
                    if r.returncode == 0:
                        return
            except Exception as e:
                log(f"amixer path failed: {e}")
        log("no suitable backend succeeded; leaving mic unchanged")
    except Exception as e:
        # absolutely no-op on any unexpected error
        try:
            if bool(os.environ.get("VOXD_DEBUG_AUDIO")):
                print(f"[mic] unexpected error: {e}")
        except Exception:
            pass
        return

def _get_version() -> str:
    """Get version from metadata, git tags, or pyproject.toml fallback."""
    try:
        return importlib.metadata.version("voxd")
    except Exception:
        # Fallback 1: Get from git tags (for dev/source installs)
        try:
            result = subprocess.run(
                ["git", "describe", "--tags", "--abbrev=0"],
                capture_output=True,
                text=True,
                timeout=2,
                cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            )
            if result.returncode == 0:
                version = result.stdout.strip()
                # Remove 'v' prefix if present (e.g., v1.3.1 -> 1.3.1)
                if version.startswith('v'):
                    version = version[1:]
                return version
        except Exception:
            pass
        
        # Fallback 2: Parse from pyproject.toml (installed or repo root)
        try:
            from pathlib import Path
            import re
            candidates = [
                Path("/opt/voxd/pyproject.toml"),
                Path(__file__).parents[2] / "pyproject.toml",
            ]
            for pyproject_path in candidates:
                if pyproject_path.exists():
                    content = pyproject_path.read_text()
                    match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
                    if match:
                        return match.group(1)
        except Exception:
            pass
        
        return "unknown"

def _parse_bool(s: str) -> bool:
    v = (s or "").strip().lower()
    if v in {"1", "true", "on", "yes", "y"}:
        return True
    if v in {"0", "false", "off", "no", "n"}:
        return False
    raise ValueError(f"expected true/false, got: {s}")

def _systemd_user_available() -> bool:
    try:
        # Fast probe; returns 0 and prints version if systemd is available for user
        r = subprocess.run(["systemctl", "--user", "--version"], capture_output=True)
        return r.returncode == 0
    except Exception:
        return False

def _ensure_voxd_tray_unit() -> None:
    """Ensure a voxd-tray.service user unit exists (packaged or per-user fallback)."""
    try:
        pkg_unit = Path("/usr/lib/systemd/user/voxd-tray.service")
        if pkg_unit.exists():
            return
        user_dir = Path.home() / ".config/systemd/user"
        try:
            user_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        unit_path = user_dir / "voxd-tray.service"
        if not unit_path.exists():
            unit_path.write_text(
                "[Unit]\n"
                "Description=VOXD tray mode (user)\n"
                "After=default.target\n\n"
                "[Service]\n"
                "Type=simple\n"
                "ExecStart=/usr/bin/voxd --tray\n"
                "Restart=on-failure\n"
                "RestartSec=2s\n"
                "Environment=YDOTOOL_SOCKET=%h/.ydotool_socket\n\n"
                "[Install]\n"
                "WantedBy=default.target\n"
            )
    except Exception:
        pass

def _xdg_autostart_path() -> Path:
    return Path.home() / ".config" / "autostart" / "voxd-tray.desktop"

def _ensure_xdg_entry() -> bool:
    try:
        p = _xdg_autostart_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_text(
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=VOXD (tray)\n"
                "Exec=voxd --tray\n"
                "X-GNOME-Autostart-enabled=true\n"
                "Hidden=false\n"
            )
        return True
    except Exception:
        return False

def _remove_xdg_entry() -> bool:
    try:
        p = _xdg_autostart_path()
        if p.exists():
            p.unlink()
        return True
    except Exception:
        return False

def _handle_autostart(arg_value: str) -> int:
    """Set autostart true/false; idempotently enable/disable user service or XDG fallback and report status."""
    desired = _parse_bool(arg_value)
    # Persist to config
    cfg = AppConfig()
    cfg.data["autostart"] = desired
    try:
        setattr(cfg, "autostart", desired)
    except Exception:
        pass
    try:
        cfg.save()
    except Exception:
        pass

    used_systemd = False
    enabled = False
    active = False

    # Try systemd --user first
    if _systemd_user_available():
        used_systemd = True
        _ensure_voxd_tray_unit()
        try:
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=False, capture_output=True)
        except Exception:
            pass

        def _is_enabled() -> bool:
            try:
                r = subprocess.run(["systemctl", "--user", "is-enabled", "voxd-tray.service"],
                                   check=False, capture_output=True)
                return r.returncode == 0
            except Exception:
                return False

        def _is_active() -> bool:
            try:
                r = subprocess.run(["systemctl", "--user", "is-active", "voxd-tray.service"],
                                   check=False, capture_output=True)
                return r.returncode == 0
            except Exception:
                return False

        if desired:
            subprocess.run(["systemctl", "--user", "enable", "--now", "voxd-tray.service"], check=False)
        else:
            subprocess.run(["systemctl", "--user", "disable", "--now", "voxd-tray.service"], check=False)

        enabled = _is_enabled()
        active = _is_active()

        # If enabling failed in a way that suggests no user bus, fall back to XDG
        if desired and not (enabled or active):
            used_systemd = False

    # XDG fallback
    if not used_systemd:
        if desired:
            xdg_ok = _ensure_xdg_entry()
            print(f"[autostart] enabled (xdg={xdg_ok})")
            return 0 if xdg_ok else 1
        else:
            xdg_ok = _remove_xdg_entry()
            print(f"[autostart] disabled (xdg={xdg_ok})")
            return 0 if xdg_ok else 1

    # Systemd path: concise status
    if desired:
        print(f"[autostart] enabled (enabled={enabled}, active={active})")
    else:
        print(f"[autostart] disabled (enabled={enabled}, active={active})")
    return 0

def main():
    parser = argparse.ArgumentParser(description="VOXD App Entry Point", add_help=False)
    # NOTE: we intentionally disable the automatic -h/--help. Sub-mode parsers
    # (and the CLI quick-actions parser) should receive -h/--help when relevant.
    # We render top-level help manually only when no sub-mode or quick-action is
    # present and -h/--help is provided.
    # Mutually-exclusive launch mode flags (simpler UX)
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--gui", action="store_true", help="Launch VOXD in GUI mode")
    mode_group.add_argument("--tray", action="store_true", help="Launch VOXD tray-only mode (background)")
    mode_group.add_argument("--flux", action="store_true", help="Launch VOXD VAD-triggered dictation mode")
    mode_group.add_argument("--flux-tuner", action="store_true", help="Launch Flux Tuner (GUI)")
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Run per-user setup (models, ydotool user service, desktop launchers) and exit",
    )
    parser.add_argument(
        "--setup-verbose",
        action="store_true",
        help="Run per-user setup with detailed diagnostics and exit",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print version and exit"
    )
    parser.add_argument(
        "--autostart",
        metavar="BOOL",
        help="Enable or disable VOXD user autostart (tray on login): true|false"
    )
    parser.add_argument(
        "--trigger-record",
        action="store_true",
        help="(Internal) signal the running VOXD App to start recording - use for system-wide HOTKEY setup"
    )
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="Print configuration and hotkey status"
    )
    args, unknown = parser.parse_known_args()

    if args.version:
        print(_get_version())
        sys.exit(0)

    if args.autostart is not None:
        try:
            rc = _handle_autostart(args.autostart)
            sys.exit(rc)
        except Exception as e:
            print(f"[autostart] error: {e}")
            sys.exit(1)

    if args.setup or args.setup_verbose:
        try:
            if args.setup_verbose:
                print("[setup] --setup-verbose is deprecated; --setup now prints detailed diagnostics by default.")
            from voxd.utils.setup_user import run_user_setup
            run_user_setup(verbose=True)
            print("[setup] Per-user setup complete.")
        except Exception as e:
            print(f"[setup] Per-user setup encountered issues: {e}")
        sys.exit(0)

    # Recognize CLI quick-action flags at top-level to implicitly enter CLI mode
    cli_flags = {
        "--save-audio", "--record", "--rh", "--transcribe", "--log", "--cfg",
        "--aipp", "--no-aipp", "--aipp-prompt", "--aipp-provider", "--aipp-model",
    }
    unknown_flags = {u.split("=")[0] for u in unknown if u.startswith("-")}

    # ------------------------------------------------------------
    #         Top-level help handling (only when no sub-mode or QA)
    # ------------------------------------------------------------
    if not any([args.gui, args.tray, args.flux, args.flux_tuner]) and not (unknown_flags & cli_flags):
        if "-h" in unknown or "--help" in unknown:
            parser.print_help()
            # Show installed version
            try:
                print(f"\nVOXD version: {_get_version()}")
            except Exception:
                pass
            # Also show CLI quick actions help for convenience
            try:
                from voxd.cli.cli_main import build_parser as _build_cli_parser
                print("\n[CLI quick actions] You can use these directly; they run in CLI mode:\n")
                print(_build_cli_parser().format_help())
            except Exception:
                pass
            # Autostart hint
            try:
                print("\n[Autostart] Enable VOXD tray on login: voxd --autostart true")
            except Exception:
                pass
            sys.exit(0)

    # Implicit CLI mode if any CLI-specific flags are present without a mode
    implied_cli = (not any([args.gui, args.tray, args.flux, args.flux_tuner]) and (unknown_flags & cli_flags))

    # If we're just the hotkey sender, dispatch and exit immediately
    if args.trigger_record:
        from voxd.utils.ipc_client import send_trigger
        send_trigger()
        sys.exit(0)

    cfg = AppConfig()
    if args.gui:
        mode = "gui"
    elif args.tray:
        mode = "tray"  # internal identifier for tray mode
    elif args.flux:
        mode = "flux"
    elif args.flux_tuner:
        mode = "flux_tuner"
    else:
        # Default to CLI when no explicit sub-mode selected
        mode = "cli" if implied_cli or True else "cli"

    if args.diagnose:
        print(f"[Diagnose] Current mode: {mode}")
        
        # Check ydotool daemon status on Wayland
        if os.environ.get("XDG_SESSION_TYPE") == "wayland":
            if shutil.which("ydotool"):
                try:
                    result = subprocess.run(
                        ["systemctl", "--user", "is-active", "ydotoold.service"],
                        capture_output=True, text=True, timeout=5
                    )
                    if result.returncode == 0:
                        print("[Diagnose] ydotool daemon: ✅ running")
                    else:
                        # Check if daemon is running manually
                        pgrep_result = subprocess.run(
                            ["pgrep", "-x", "ydotoold"],
                            capture_output=True, timeout=3
                        )
                        if pgrep_result.returncode == 0:
                            print("[Diagnose] ydotool daemon: ⚠️ running manually (not via systemd)")
                        else:
                            print(f"[Diagnose] ydotool daemon: ❌ {result.stdout.strip()}")
                            print("[Diagnose] → Fix: systemctl --user start ydotoold.service")
                except Exception:
                    print("[Diagnose] ydotool daemon: ❌ cannot check status")
            else:
                print("[Diagnose] ydotool: ❌ not installed")
        
        # Audio device diagnostics
        try:
            import sounddevice as sd
            print("[Diagnose] sounddevice default:", sd.default.device)
            try:
                inp = sd.query_devices(kind='input')
                print(f"[Diagnose] default input: {inp.get('name')} @ {inp.get('default_samplerate')} Hz")
            except Exception:
                pass
            # Enumerate devices
            try:
                devs = sd.query_devices()
                print("[Diagnose] Available devices:")
                for i, d in enumerate(devs):
                    name = d.get('name', 'unknown')
                    mi = d.get('max_input_channels', 0)
                    sr = d.get('default_samplerate', None)
                    print(f"  [{i}] {name} | in={mi} | default_sr={sr}")
                # Pulse hint
                names = [str(d.get('name','')).lower() for d in devs]
                has_pulse = any('pulse' in n for n in names)
                if not has_pulse:
                    print("[Diagnose] Hint: No 'pulse' device detected.")
                    if shutil.which('apt'):
                        print("  Debian/Ubuntu: sudo apt install alsa-plugins pavucontrol (ensure pulseaudio or pipewire-pulse active)")
                    elif shutil.which('dnf') or shutil.which('dnf5') or shutil.which('zypper'):
                        print("  Fedora/openSUSE: sudo dnf install alsa-plugins-pulseaudio pavucontrol (ensure pipewire-pulseaudio active)")
                    elif shutil.which('pacman'):
                        print("  Arch: sudo pacman -S alsa-plugins pipewire-pulse pavucontrol")
            except Exception:
                pass
        except Exception:
            print("[Diagnose] sounddevice not available")

        sys.exit(0)

    # Optionally ensure mic is on and set to desired level (best-effort)
    _mic_autoset_if_enabled(cfg)

    print()
    _print_boxed(f"Launching VOXD app in '{ORANGE}{mode}{RESET}' mode…")
    # show shortcut hint
    print(f"""Note:
- create a global {ORANGE}HOTKEY{RESET} shortcut (in your system) that runs {ORANGE}`bash -c 'voxd --trigger-record'`{RESET} (e.g. Super+Z)"
- directly start voice-typing by running {ORANGE}'voxd --rh'{RESET} in terminal.
- transcripts ALWAYS picked up into clipboard.
""")

    if mode == "cli":
        # Forward unknown args to cli_main
        from voxd.cli import cli_main as cli_main_mod
        sys.argv = [sys.argv[0]] + unknown
        cli_main_mod.main()
    elif mode == "gui":
        from voxd.gui.gui_main import main as gui_main
        gui_main()
    elif mode == "tray":
        from voxd.tray.tray_main import main as tray_main
        tray_main()
    elif mode == "flux":
        from voxd.flux.flux_main import main as flux_main
        sys.argv = [sys.argv[0]] + unknown
        flux_main()
    elif mode == "flux_tuner":
        from voxd.flux.flux_tuner import main as flux_tuner_main
        flux_tuner_main()
    else:
        print(f"[__main__] ❌ Unknown app_mode: {mode}")
        sys.exit(1)

if __name__ == "__main__":
    main()
