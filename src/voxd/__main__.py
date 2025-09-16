import sys
import argparse
import subprocess
import os
from voxd.core.config import AppConfig

from voxd.paths import CONFIG_FILE, resource_path
import shutil, yaml
import importlib.metadata

def ensure_user_config() -> dict:
    if not CONFIG_FILE.exists():
        default_tpl = resource_path("defaults/config.yaml")
        shutil.copy(default_tpl, CONFIG_FILE)
    return yaml.safe_load(CONFIG_FILE.read_text())

def main():
    parser = argparse.ArgumentParser(description="VOXD App Entry Point", add_help=False)
    # NOTE: we intentionally disable the automatic -h/--help so that when the user
    # runs `voxd --cli -h` the `-h` flag is forwarded to the CLI parser instead
    # of being swallowed here. We will render top-level help manually when no
    # sub-mode flag is provided and -h/--help is present.
    # Mutually-exclusive launch mode flags (simpler UX)
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--gui", action="store_true", help="Launch VOXD in GUI mode")
    mode_group.add_argument("--cli", action="store_true", help="Launch VOXD in CLI mode")
    mode_group.add_argument("--tray", action="store_true", help="Launch VOXD tray-only mode (background)")
    mode_group.add_argument("--flux", action="store_true", help="Launch VOXD VAD-triggered dictation mode")
    mode_group.add_argument("--flux-tuner", action="store_true", help="Launch Flux Tuner (GUI)")
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print version and exit"
    )
    parser.add_argument(
        "--trigger-record",
        action="store_true",
        help="(Internal) signal the running VOXD App to start recording"
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

    # Recognize CLI quick-action flags at top-level to implicitly enter CLI mode
    cli_flags = {
        "--save-audio", "--record", "--rh", "--transcribe", "--log", "--cfg",
        "--aipp", "--no-aipp", "--aipp-prompt", "--aipp-provider", "--aipp-model",
    }
    unknown_flags = {u.split("=")[0] for u in unknown if u.startswith("-")}

    # ------------------------------------------------------------
    #         Top-level help handling (only when no sub-mode)
    # ------------------------------------------------------------
    if not any([args.cli, args.gui, args.tray]):
        if "-h" in unknown or "--help" in unknown or len(sys.argv) == 1:
            parser.print_help()
            # Show installed version
            try:
                print(f"\nVOXD version: {importlib.metadata.version('voxd')}")
            except Exception:
                pass
            # Also show CLI quick actions help for convenience
            try:
                from voxd.cli.cli_main import build_parser as _build_cli_parser
                print("\n[CLI quick actions] You can use these directly; they imply --cli:\n")
                print(_build_cli_parser().format_help())
            except Exception:
                pass
            sys.exit(0)

    # Implicit CLI mode if any CLI-specific flags are present without a mode
    if not any([args.cli, args.gui, args.tray]) and (unknown_flags & cli_flags):
        args.cli = True

    # If we're just the hotkey sender, dispatch and exit immediately
    if args.trigger_record:
        from voxd.utils.ipc_client import send_trigger
        send_trigger()
        sys.exit(0)

    cfg = AppConfig()
    if args.cli:
        mode = "cli"
    elif args.gui:
        mode = "gui"
    elif args.tray:
        mode = "tray"  # internal identifier for tray mode
    elif args.flux:
        mode = "flux"
    elif args.flux_tuner:
        mode = "flux_tuner"
    else:
        mode = "tray"

    if args.diagnose:
        print(f"[Diagnose] Current mode: {mode}")
        print(f"[Diagnose] Detected shortcut: (use './hotkey_setup.sh list' for hotkey detection)")
        
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

    print(f"Launching VOXD app in '{mode}' mode...")

    # show shortcut hint
    if mode == "cli":
        print("[VOXD] Tip: create a global shortcut that runs `bash -c 'voxd --trigger-record'` (e.g. Super+R)")
        print("[VOXD] Use './hotkey_setup.sh guide' for setup instructions")

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
