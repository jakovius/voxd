import sys
import argparse
import subprocess
import os
from voxt.core.config import AppConfig

from voxt.paths import CONFIG_FILE, resource_path
import shutil, yaml

def ensure_user_config() -> dict:
    if not CONFIG_FILE.exists():
        default_tpl = resource_path("defaults/config.yaml")
        shutil.copy(default_tpl, CONFIG_FILE)
    return yaml.safe_load(CONFIG_FILE.read_text())

def main():
    parser = argparse.ArgumentParser(description="VOXT App Entry Point", add_help=False)
    # NOTE: we intentionally disable the automatic -h/--help so that when the user
    # runs `voxt --cli -h` the `-h` flag is forwarded to the CLI parser instead
    # of being swallowed here. We will render top-level help manually when no
    # sub-mode flag is provided and -h/--help is present.
    # Mutually-exclusive launch mode flags (simpler UX)
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--gui", action="store_true", help="Launch VOXT in GUI mode")
    mode_group.add_argument("--cli", action="store_true", help="Launch VOXT in CLI mode")
    mode_group.add_argument("--tray", action="store_true", help="Launch VOXT tray-only mode (background)")
    parser.add_argument(
        "--trigger-record",
        action="store_true",
        help="(Internal) signal the running VOXT App to start recording"
    )
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="Print configuration and hotkey status"
    )
    args, unknown = parser.parse_known_args()

    # ------------------------------------------------------------
    #         Top-level help handling (only when no sub-mode)
    # ------------------------------------------------------------
    if not any([args.cli, args.gui, args.tray]):
        if "-h" in unknown or "--help" in unknown or len(sys.argv) == 1:
            parser.print_help()
            sys.exit(0)

    # If we're just the hotkey sender, dispatch and exit immediately
    if args.trigger_record:
        from voxt.utils.ipc_client import send_trigger
        send_trigger()
        sys.exit(0)

    cfg = AppConfig()
    if args.cli:
        mode = "cli"
    elif args.gui:
        mode = "gui"
    elif args.tray:
        mode = "tray"  # internal identifier for tray mode
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

    print(f"Launching VOXT app in '{mode}' mode...")

    # show shortcut hint
    if mode == "cli":
        print("[VOXT] Tip: create a global shortcut that runs `bash -c 'voxt --trigger-record'` (e.g. Super+R)")
        print("[VOXT] Use './hotkey_setup.sh guide' for setup instructions")

    if mode == "cli":
        # Forward unknown args to cli_main
        from voxt.cli import cli_main as cli_main_mod
        sys.argv = [sys.argv[0]] + unknown
        cli_main_mod.main()
    elif mode == "gui":
        from voxt.gui.gui_main import main as gui_main
        gui_main()
    elif mode == "tray":
        from voxt.tray.tray_main import main as tray_main
        tray_main()
    else:
        print(f"[__main__] ❌ Unknown app_mode: {mode}")
        sys.exit(1)

if __name__ == "__main__":
    main()
