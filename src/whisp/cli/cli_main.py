
import subprocess
import argparse
import threading

from whisp.core.config import AppConfig
from whisp.core.logger import SessionLogger
from whisp.core.transcriber import WhisperTranscriber
from whisp.utils.core_runner import AudioRecorder, ClipboardManager, SimulatedTyper
from whisp.utils.ipc_server import start_ipc_server
from whisp.utils.libw import verbo
        
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
    subprocess.run(["xdg-open", config_path])

def cli_main(cfg: AppConfig, logger: SessionLogger, args: argparse.Namespace):
    hotkey_event = threading.Event()

    def on_ipc_trigger():
        verbo("\n[IPC] Hotkey trigger received.")
        hotkey_event.set()

    # Start IPC server for hotkey triggers
    start_ipc_server(on_ipc_trigger)

    print("🌀 Whisp CLI Mode:\n--- ALWAYS picking up into clipboard\n--- Type 'h' for help")

    while True:
        cmd = input("\nwhisp> ").strip().lower()
        if cmd == "r":
            print(" Simple mode | Recording... (ENTER to stop and output into the terminal)")
            recorder = AudioRecorder()
            transcriber = WhisperTranscriber(cfg.model_path, cfg.whisper_binary, delete_input=not args.save_audio)
            clipboard = ClipboardManager(backend=cfg.clipboard_backend)
            typer = SimulatedTyper(delay=cfg.typing_delay)

            recorder.start_recording()
            input()
            rec_path = recorder.stop_recording(preserve=args.save_audio)
            verbo("Stopping recording...")

            tscript, orig_tscript = transcriber.transcribe(rec_path)
            if not tscript:
                print("[core_runner] No transcript returned.")
                continue

            clipboard.copy(tscript)
            logger.log_entry(tscript)
            logger.save()
            print(f"📝 ---> {tscript}")

        elif cmd == "rh":
            print("Continuous mode | hotkey to rec/stop | Ctrl+C to exit\n*** You can now go to ANY other app to VOICE-TYPE - leave this active in the background ***")
            # Create reusable instances outside the loop
            recorder = AudioRecorder()
            transcriber = WhisperTranscriber(cfg.model_path, cfg.whisper_binary, delete_input=not args.save_audio)
            clipboard = ClipboardManager(backend=cfg.clipboard_backend)
            typer = SimulatedTyper(delay=cfg.typing_delay)

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

                    clipboard.copy(tscript)
                    print(f"\n📝 ---> ")
                    if cfg.simulate_typing:
                        typer.type(tscript)
                    print()
                    logger.log_entry(tscript)
                    logger.save()

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

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Whisp CLI Mode")
    parser.add_argument("--save-audio", action="store_true", help="Preserve audio recordings.")
    parser.add_argument("--test-file", type=str, help="Path to audio file to reuse.")
    args = parser.parse_args()

    cfg = AppConfig()
    logger = SessionLogger(cfg.log_enabled, cfg.log_file)

    try:
        if args.test_file:
            transcriber = WhisperTranscriber(cfg.model_path, cfg.whisper_binary)
            tscript, _ = transcriber.transcribe(args.test_file)
            print(f"\n📝 ---> {tscript}")
            logger.log_entry(tscript)
            logger.save()
        else:
            cli_main(cfg, logger, args)
    except KeyboardInterrupt:
        verbo("\n[cli] Interrupted. Exiting.")