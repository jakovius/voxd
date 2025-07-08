# pyright: reportAttributeAccessIssue=false
import subprocess
import argparse
import sys
import threading
from typing import Any, cast

from voxt.core.config import AppConfig
from voxt.core.logger import SessionLogger
from voxt.core.transcriber import voxterTranscriber
from voxt.core.aipp import get_final_text
from voxt.utils.core_runner import AudioRecorder, ClipboardManager, SimulatedTyper
from voxt.utils.ipc_server import start_ipc_server
from voxt.utils.libw import verbo
        
def print_help():
    print("""
[ CLI Mode Commands ]
  r      Start recording (stop with Enter)
  rh     Wait for hotkey to start and stop recording
  l      Show current session log
  cfg    Edit configuration
  x      Exit
  h      Show this help
""")

def edit_config(config_path="config.yaml"):
    verbo("[cli] Opening config file...")
    from voxt.core.config import CONFIG_PATH
    subprocess.run(["xdg-open", str(CONFIG_PATH)])

def cli_main(cfg: AppConfig, logger: SessionLogger, args: argparse.Namespace):
    hotkey_event = threading.Event()

    def on_ipc_trigger():
        verbo("\n[IPC] Hotkey trigger received.")
        hotkey_event.set()

    # Start IPC server for hotkey triggers
    start_ipc_server(on_ipc_trigger)

    print("🌀 VOXT CLI Mode:\n--- ALWAYS picking up into clipboard\n--- Type 'h' for help")

    while True:
        cmd = input("\VOXT> ").strip().lower()
        if cmd == "r":
            print(" Simple mode | Recording... (ENTER to stop and output into the terminal)")
            recorder = AudioRecorder()
            transcriber = WhisperTranscriber(cfg.model_path, cfg.whisper_binary, delete_input=not args.save_audio)
            clipboard = ClipboardManager()
            typer = SimulatedTyper(delay=cfg.typing_delay, start_delay=cfg.typing_start_delay)

            recorder.start_recording()
            input()
            rec_path = recorder.stop_recording(preserve=args.save_audio)
            verbo("Stopping recording...")

            tscript, orig_tscript = transcriber.transcribe(rec_path)
            if not tscript:
                print("[core_runner] No transcript returned.")
                continue

            final_text = get_final_text(tscript, cfg)  # type: ignore[arg-type]
            clipboard.copy(final_text)
            if cfg.aipp_enabled:
                logger.log_entry(f"[original] {tscript}")
                if final_text != tscript:
                    logger.log_entry(f"[aipp] {final_text}")
            else:
                logger.log_entry(final_text)
            print(f"📝 ---> {final_text}")

        elif cmd == "rh":
            print("Continuous mode | hotkey to rec/stop | Ctrl+C to exit\n*** You can now go to ANY other app to VOICE-TYPE - leave this active in the background ***")
            # Create reusable instances outside the loop
            recorder = AudioRecorder()
            transcriber = WhisperTranscriber(cfg.model_path, cfg.whisper_binary, delete_input=not args.save_audio)
            clipboard = ClipboardManager()
            typer = SimulatedTyper(delay=cfg.typing_delay, start_delay=cfg.typing_start_delay)

            try:
                while True:
                    verbo("\n[cli] Awaiting hotkey to start recording...")
                    hotkey_event.clear()
                    hotkey_event.wait()

                    recorder.start_recording()
                    print("Recording...")
                    hotkey_event.clear()
                    hotkey_event.wait()
                    verbo("[cli] Hotkey received: stopping recording.")

                    rec_path = recorder.stop_recording(preserve=args.save_audio)
                    verbo("[recorder] Stopping recording...")

                    tscript, orig_tscript = transcriber.transcribe(rec_path)
                    if not tscript:
                        print("[core_runner] No transcript returned.")
                        continue

                    final_text = get_final_text(tscript, cfg)  # type: ignore[arg-type]
                    clipboard.copy(final_text)
                    print(f"\n📝 ---> ")
                    if cfg.simulate_typing:
                        typer.type(final_text)
                    print()
                    if cfg.aipp_enabled:
                        logger.log_entry(f"[original] {tscript}")
                        if final_text != tscript:
                            logger.log_entry(f"[aipp] {final_text}")
                    else:
                        logger.log_entry(final_text)

            except KeyboardInterrupt:
                print("\n[cli] Exiting continuous recording mode...")

        elif cmd == "l":
            logger.show()
            save = input("Save session log to file? (Y/N): ").strip().lower()
            if save == "y":
                logger.save()

        elif cmd == "cfg":
            edit_config()

        elif cmd == "h":
            print_help()

        elif cmd == "x":
            verbo("[cli] Exiting.")
            break

        elif cmd == "":
            continue

        else:
            print("[cli] Unknown command. Type 'h' for help.")

def main():
    parser = argparse.ArgumentParser(description="VOXT CLI Mode")
    parser.add_argument("--save-audio", action="store_true", help="Preserve audio recordings.")
    # --- Quick action flags (non-interactive shortcuts) ---
    qa = parser.add_argument_group("Quick actions")
    qa.add_argument("--record", action="store_true", help="One-shot microphone recording and exit")
    qa.add_argument("--rh", action="store_true", help="Hotkey-controlled continuous recording")
    qa.add_argument("--transcribe", type=str, metavar="FILE", help="Transcribe an existing audio FILE and exit (file is preserved)")
    qa.add_argument("--log", action="store_true", help="Show current session log and exit")
    qa.add_argument("--cfg", action="store_true", help="Open configuration file for editing and exit")
    # --- AIPP CLI flags ---
    parser.add_argument("--aipp", action="store_true", help="Enable AI post-processing (AIPP) for this run")
    parser.add_argument("--no-aipp", action="store_true", help="Disable AI post-processing (AIPP) for this run")
    parser.add_argument("--aipp-prompt", type=str, help="AIPP prompt key to use (default, prompt1, prompt2, prompt3)")
    parser.add_argument("--aipp-provider", type=str, help="AIPP provider override (ollama, openai, anthropic, xai)")
    parser.add_argument("--aipp-model", type=str, help="AIPP model override for the selected provider")
    args = parser.parse_args()

    cfg = cast(Any, AppConfig())
    logger = SessionLogger(cfg.log_enabled, cfg.log_location)

    # --- Apply CLI AIPP overrides (in-memory only) ---
    if args.aipp:
        cfg.data["aipp_enabled"] = True
        cfg.aipp_enabled = True
    if args.no_aipp:
        cfg.data["aipp_enabled"] = False
        cfg.aipp_enabled = False
    if args.aipp_prompt:
        if args.aipp_prompt in cfg.data.get("aipp_prompts", {}):
            cfg.data["aipp_active_prompt"] = args.aipp_prompt
            cfg.aipp_active_prompt = args.aipp_prompt
        else:
            print(f"[cli] Unknown AIPP prompt key: {args.aipp_prompt}")
    if args.aipp_provider:
        if args.aipp_provider in ("ollama", "openai", "anthropic", "xai"):
            cfg.data["aipp_provider"] = args.aipp_provider
            cfg.aipp_provider = args.aipp_provider
        else:
            print(f"[cli] Unknown AIPP provider: {args.aipp_provider}")
    if args.aipp_model:
        prov = cfg.data.get("aipp_provider", "ollama")
        if args.aipp_model in cfg.data.get("aipp_models", {}).get(prov, []):
            cfg.data["aipp_selected_models"][prov] = args.aipp_model
            cfg.aipp_model = args.aipp_model
        else:
            print(f"[cli] Unknown model '{args.aipp_model}' for provider '{prov}'")

    try:
        # --- Quick actions ---
        if args.record:
            print("Recording... (press ENTER to stop)")
            recorder = AudioRecorder()
            transcriber = WhisperTranscriber(cfg.model_path, cfg.whisper_binary, delete_input=not args.save_audio)
            clipboard = ClipboardManager()
            typer = SimulatedTyper(delay=cfg.typing_delay, start_delay=cfg.typing_start_delay)

            recorder.start_recording()
            input()
            rec_path = recorder.stop_recording(preserve=args.save_audio)
            tscript, _ = transcriber.transcribe(rec_path)
            if not tscript:
                print("[cli] No transcript returned.")
                sys.exit(1)
            final_text = get_final_text(tscript, cfg)  # type: ignore[arg-type]
            clipboard.copy(final_text)
            if cfg.simulate_typing:
                typer.type(final_text)
            print(f"\n📝 ---> {final_text}")
            if cfg.aipp_enabled:
                logger.log_entry(f"[original] {tscript}")
                if final_text != tscript:
                    logger.log_entry(f"[aipp] {final_text}")
            else:
                logger.log_entry(final_text)
            logger.save()
            return

        if args.rh:
            hotkey_event = threading.Event()
            def on_ipc_trigger():
                verbo("\n[IPC] Hotkey trigger received.")
                hotkey_event.set()
            start_ipc_server(on_ipc_trigger)
            print("Continuous mode | hotkey to rec/stop | Ctrl+C to exit")
            recorder = AudioRecorder()
            transcriber = WhisperTranscriber(cfg.model_path, cfg.whisper_binary, delete_input=not args.save_audio)
            clipboard = ClipboardManager()
            typer = SimulatedTyper(delay=cfg.typing_delay, start_delay=cfg.typing_start_delay)
            try:
                while True:
                    verbo("\n[cli] Awaiting hotkey to start recording...")
                    hotkey_event.clear()
                    hotkey_event.wait()
                    recorder.start_recording()
                    print("Recording...")
                    hotkey_event.clear()
                    hotkey_event.wait()
                    verbo("[cli] Hotkey received: stopping recording.")
                    rec_path = recorder.stop_recording(preserve=args.save_audio)
                    tscript, _ = transcriber.transcribe(rec_path)
                    if not tscript:
                        print("[cli] No transcript returned.")
                        continue
                    final_text = get_final_text(tscript, cfg)  # type: ignore[arg-type]
                    clipboard.copy(final_text)
                    if cfg.simulate_typing:
                        typer.type(final_text)
                    print(f"\n📝 ---> {final_text}")
                    if cfg.aipp_enabled:
                        logger.log_entry(f"[original] {tscript}")
                        if final_text != tscript:
                            logger.log_entry(f"[aipp] {final_text}")
                    else:
                        logger.log_entry(final_text)
            except KeyboardInterrupt:
                print("\n[cli] Exiting continuous recording mode...")
            return

        if args.transcribe:
            transcriber = WhisperTranscriber(cfg.model_path, cfg.whisper_binary, delete_input=False)
            tscript, _ = transcriber.transcribe(args.transcribe)
            final_text = get_final_text(tscript, cfg)  # type: ignore[arg-type]
            print(f"\n📝 ---> {final_text}")
            if cfg.aipp_enabled:
                logger.log_entry(f"[original] {tscript}")
                if final_text != tscript:
                    logger.log_entry(f"[aipp] {final_text}")
            logger.save()
            return

        if args.log:
            logger.show()
            return

        if args.cfg:
            edit_config()
            return

        # --- Interactive CLI ---
        original_get_final_text = get_final_text  # Save the original
        def get_final_text_for_cli(tscript, _cfg=None):
            return original_get_final_text(tscript, cfg)
        globals()['get_final_text'] = get_final_text_for_cli
        cli_main(cfg, logger, args)
    except KeyboardInterrupt:
        verbo("\n[cli] Interrupted. Exiting.")

if __name__ == "__main__":
    main()