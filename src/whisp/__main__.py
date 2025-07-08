import sys
import argparse
from whisp.core.config import AppConfig
from whisp.utils.hotkey_probe import get_record_shortcut

from whisp.paths import CONFIG_FILE, resource_path
import shutil, yaml

def ensure_user_config() -> dict:
    if not CONFIG_FILE.exists():
        default_tpl = resource_path("defaults/config.yaml")
        shutil.copy(default_tpl, CONFIG_FILE)
    return yaml.safe_load(CONFIG_FILE.read_text())

def main():
    parser = argparse.ArgumentParser(description="Whisp App Entry Point", add_help=False)
    # NOTE: we intentionally disable the automatic -h/--help so that when the user
    # runs `whisp --cli -h` the `-h` flag is forwarded to the CLI parser instead
    # of being swallowed here. We will render top-level help manually when no
    # sub-mode flag is provided and -h/--help is present.
    # Mutually-exclusive launch mode flags (simpler UX)
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--gui", action="store_true", help="Launch Whisp in GUI mode")
    mode_group.add_argument("--cli", action="store_true", help="Launch Whisp in CLI mode")
    mode_group.add_argument("--tray", action="store_true", help="Launch Whisp tray-only mode (background)")
    parser.add_argument(
        "--trigger-record",
        action="store_true",
        help="(Internal) signal the running Whisp App to start recording"
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
        from whisp.utils.ipc_client import send_trigger
        send_trigger()
        sys.exit(0)

    cfg = AppConfig()
    if args.cli:
        mode = "cli"
    elif args.gui:
        mode = "gui"
    elif args.tray:
        mode = "whisp"  # internal identifier for tray mode
    else:
        mode = "whisp"

    if args.diagnose:
        print(f"[Diagnose] Current mode: {mode}")
        key_dbg = get_record_shortcut() or "(none detected)"
        print(f"[Diagnose] Detected shortcut: {key_dbg}")
        sys.exit(0)

    print(f"Launching Whisp app in '{mode}' mode...")

    # show detected shortcut or hint
    key = get_record_shortcut()
    if mode == "cli":
        if key:
            print(f"[Whisp] Record shortcut detected: {key}")
        else:
            print("[Whisp] Tip: create a global shortcut that runs `bash -c 'whisp --trigger-record'` (e.g. Super+R)")

    if mode == "cli":
        # Forward unknown args to cli_main
        from whisp.cli import cli_main as cli_main_mod
        sys.argv = [sys.argv[0]] + unknown
        cli_main_mod.main()
    elif mode == "gui":
        from whisp.gui.gui_main import main as gui_main
        gui_main()
    elif mode == "whisp":
        from whisp.tray.tray_main import main as tray_main
        tray_main()
    else:
        print(f"[__main__] ❌ Unknown app_mode: {mode}")
        sys.exit(1)

if __name__ == "__main__":
    main()
