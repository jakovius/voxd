from whisp.core.recorder import AudioRecorder
from whisp.core.transcriber import WhisperTranscriber
from whisp.core.clipboard import ClipboardManager
from whisp.core.typer import SimulatedTyper
from whisp.core.logger import SessionLogger
from whisp.core.config import AppConfig
from whisp.core.aipp import run_aipp
from whisp.utils.benchmark_utils import write_perf_entry

from time import time
from datetime import datetime
from pathlib import Path
import psutil

import sys
if "PyQt6" in sys.modules:
    from PyQt6.QtWidgets import QInputDialog


def run_core_process(cfg: AppConfig, *, preserve_audio=False, simulate_typing=False, apply_aipp=False, logger=None):
    print("[core_runner] Running core process...")

    recorder = AudioRecorder()
    transcriber = WhisperTranscriber(cfg.model_path, cfg.whisper_binary, delete_input=not preserve_audio)
    clipboard = ClipboardManager(backend=cfg.clipboard_backend)
    typer = SimulatedTyper(delay=cfg.typing_delay)
    if logger is None:
        logger = SessionLogger(cfg.log_enabled, cfg.log_file)

    # === Record
    recorder.start_recording()
    input("[core_runner] Press ENTER to stop recording...")
    rec_start = datetime.now()
    rec_path = recorder.stop_recording(preserve=preserve_audio)
    rec_end = datetime.now()

    # === Transcribe
    trans_start = time()
    tscript, orig_tscript = transcriber.transcribe(rec_path)
    trans_end = time()

    if not tscript:
        print("[core_runner] No transcript returned.")
        return None

    # === AIPP
    aipp_start = aipp_end = None
    ai_output = None
    if apply_aipp and cfg.aipp_enabled:
        aipp_start = time()
        ai_output = run_aipp(tscript, cfg)
        aipp_end = time()
        if ai_output:
            print("[core_runner] AIPP result:", ai_output)

    # === Clipboard
    clipboard.copy(tscript)

    # === Simulated Typing
    if simulate_typing and cfg.simulate_typing:
        typer.type(tscript)

    # === Logging
    logger.log_entry(tscript)
    if ai_output:
        logger.log_entry(f"[ai output] {ai_output}")
    logger.save()

    if not preserve_audio:
        recorder.cleanup_temp()

    # === Accuracy rating
    usr_trans_acc = None
    if cfg.collect_metrics:
        if "PyQt6" in sys.modules:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance() or QApplication(sys.argv)
            try:
                input_str, ok = QInputDialog.getText(None, "Accuracy Rating", "Rate transcription accuracy (0-100%):")
                if ok:
                    usr_trans_acc = float(input_str.strip())
            except Exception:
                usr_trans_acc = 0.0
        else:
            print("\n[core_runner] Please rate the transcription accuracy (0-100%)")
            print("Transcript:\n", tscript)
            try:
                usr_trans_acc = float(input("Enter accuracy % (or leave blank): ").strip() or 0.0)
            except ValueError:
                usr_trans_acc = 0.0

    # === Performance Logging
    if cfg.collect_metrics:
        perf_entry = {
            "date": rec_start.strftime("%Y-%m-%d"),
            "rec_start_time": rec_start.strftime("%H:%M:%S"),
            "rec_end_time": rec_end.strftime("%H:%M:%S"),
            "rec_dur": (rec_end - rec_start).total_seconds(),
            "trans_start_time": datetime.fromtimestamp(trans_start).strftime("%H:%M:%S"),
            "trans_end_time": datetime.fromtimestamp(trans_end).strftime("%H:%M:%S"),
            "trans_dur": trans_end - trans_start,
            "trans_eff": (trans_end - trans_start) / max(len(tscript), 1),
            "transcript": tscript,
            "usr_trans_acc": usr_trans_acc,
            "aipp_start_time": datetime.fromtimestamp(aipp_start).strftime("%H:%M:%S") if aipp_start else None,
            "aipp_end_time": datetime.fromtimestamp(aipp_end).strftime("%H:%M:%S") if aipp_end else None,
            "aipp_dur": (aipp_end - aipp_start) if aipp_start and aipp_end else None,
            "ai_model": cfg.aipp_model if cfg.aipp_enabled else None,
            "ai_provider": cfg.aipp_provider if cfg.aipp_enabled else None,
            "ai_prompt": cfg.aipp_prompt_default if cfg.aipp_enabled else None,
            "ai_transcript": ai_output,
            "aipp_eff": (aipp_end - aipp_start) / max(len(ai_output), 1) if ai_output and aipp_start and aipp_end else None,
            "sys_mem": psutil.virtual_memory().total,
            "sys_cpu": psutil.cpu_freq().max,
            "total_dur": (trans_end - trans_start) + (rec_end - rec_start)
        }
        write_perf_entry(perf_entry)

    print("[core_runner] Done.")
    return tscript
