import sys
import argparse
import subprocess
import os
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
        print(importlib.metadata.version("voxd"))
        sys.exit(0)

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
                print(f"\nVOXD version: {importlib.metadata.version('voxd')}")
            except Exception:
                pass
            # Also show CLI quick actions help for convenience
            try:
                from voxd.cli.cli_main import build_parser as _build_cli_parser
                print("\n[CLI quick actions] You can use these directly; they run in CLI mode:\n")
                print(_build_cli_parser().format_help())
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
