import argparse
import os
import sys
import csv
from datetime import datetime

from core.config import AppConfig
from utils.core_runner import run_core_process
from core.transcriber import WhisperTranscriber


PERF_LOG_FILE = "whisp_perf_data.csv"


def test_mode(cfg: AppConfig):
    print("==> Running TEST mode")
    t_start = datetime.now()
    tscript = run_core_process(cfg, preserve_audio=True)
    t_end = datetime.now()

    if tscript:
        duration = (t_end - t_start).total_seconds()
        print(f"[test] Transcript length: {len(tscript)} characters")
        print(f"[test] Duration: {duration:.2f} seconds")
        print("[test] Done.")
    else:
        print("[test] No transcript returned.")


def benchmark_mode(cfg: AppConfig, audio_file: str, models: list):
    print("==> Running BENCHMARK mode")
    if not os.path.exists(audio_file):
        print(f"[benchmark] File not found: {audio_file}")
        return

    rows = []

    for model_path in models:
        print(f"\n[benchmark] Using model: {model_path}")
        transcriber = WhisperTranscriber(model_path, cfg.whisper_binary)
        start = datetime.now()
        tscript, _ = transcriber.transcribe(audio_file)
        end = datetime.now()

        duration = (end - start).total_seconds()
        rows.append({
            "timestamp": datetime.now().isoformat(),
            "model": os.path.basename(model_path),
            "chars": len(tscript or ""),
            "duration": duration,
            "efficiency": duration / max(len(tscript or ""), 1)
        })

    save_benchmark_results(rows)


def save_benchmark_results(rows):
    fieldnames = ["timestamp", "model", "chars", "duration", "efficiency"]
    write_header = not os.path.exists(PERF_LOG_FILE)

    with open(PERF_LOG_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)

    print(f"[benchmark] Results saved to {PERF_LOG_FILE}")


def analyze_mode():
    print("==> Running ANALYZE mode")

    if not os.path.exists(PERF_LOG_FILE):
        print(f"[analyze] No performance log found at {PERF_LOG_FILE}")
        return

    with open(PERF_LOG_FILE, "r") as f:
        reader = csv.DictReader(f)
        entries = list(reader)

    if not entries:
        print("[analyze] No entries to analyze.")
        return

    total_runs = len(entries)
    total_time = sum(float(e["duration"]) for e in entries)
    avg_eff = sum(float(e["efficiency"]) for e in entries) / total_runs

    print(f"\nTotal runs: {total_runs}")
    print(f"Avg duration: {total_time / total_runs:.2f} sec")
    print(f"Avg efficiency: {avg_eff:.4f} sec/char")

    models = {}
    for e in entries:
        m = e["model"]
        models.setdefault(m, []).append(float(e["duration"]))

    for model, times in models.items():
        print(f"  {model}: {sum(times)/len(times):.2f} sec avg")


def diagnostics_mode(cfg: AppConfig):
    print("==> Running DIAGNOSTICS mode")

    print("[diag] Checking config file...")
    cfg.print_summary()

    print("[diag] Checking whisper binary...")
    if not os.path.exists(cfg.whisper_binary):
        print(f"❌ Binary not found: {cfg.whisper_binary}")
    else:
        print("✅ Whisper binary found.")

    print("[diag] Checking model...")
    if not os.path.exists(cfg.model_path):
        print(f"❌ Model not found: {cfg.model_path}")
    else:
        print("✅ Model file OK.")

    print("[diag] Checking clipboard...")
    try:
        import pyperclip
        pyperclip.copy("test")
        print("✅ Clipboard test passed.")
    except Exception as e:
        print(f"❌ Clipboard test failed: {e}")

    print("[diag] Checking mic...")
    try:
        import sounddevice
        sounddevice.query_devices()
        print("✅ Microphone check passed.")
    except Exception as e:
        print(f"❌ Mic check failed: {e}")

    print("[diag] Done.")


def dry_run():
    print("==> DRY RUN")
    print("Config + core modules load OK.")
    cfg = AppConfig()
    print("Model:", cfg.model_path)
    print("Whisper binary:", cfg.whisper_binary)
    print("Dry-run successful.")


def main():
    parser = argparse.ArgumentParser(description="Whisp Test Utility")
    parser.add_argument("mode", choices=["test", "benchmark", "analyze", "diagnostics", "dry"], help="Test mode to run")
    parser.add_argument("--audio", type=str, help="Audio file for benchmark mode")
    parser.add_argument("--models", nargs="+", help="List of model paths for benchmarking")

    args = parser.parse_args()
    cfg = AppConfig()

    if args.mode == "test":
        test_mode(cfg)
    elif args.mode == "benchmark":
        if not args.audio or not args.models:
            print("Please provide --audio and --models for benchmark.")
        else:
            benchmark_mode(cfg, args.audio, args.models)
    elif args.mode == "analyze":
        analyze_mode()
    elif args.mode == "diagnostics":
        diagnostics_mode(cfg)
    elif args.mode == "dry":
        dry_run()


if __name__ == "__main__":
    main()
