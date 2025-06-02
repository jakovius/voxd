
Whisp is a **Python front-end wrapper** around `whisper.cpp` that lets you:

1. Record audio from the mic (`sounddevice`).
2. Run it through a local Whisper binary.
3. Copy (and optionally **type**) the transcript into the focused window.
4. Keep session / performance logs and, if asked, pipe the text through an LLM for post-processing (AIPP).

It ships three UI surfaces (CLI, minimal PyQt6 GUI, and a tray “WHISP” mode) that all call the same **`run_core_process`** pipeline.

---

## 2 ⃣ File-system anatomy (the condensed version)

```
src/whisp/               ← the Python package
│
├─ __main__.py           entry-point / mode switcher
├─ paths.py              all paths & binary discovery helpers
│
├─ core/                 low-level building blocks
│   ├─ recorder.py       → mic capture (.wav)
│   ├─ transcriber.py    → whisper.cpp CLI wrapper
│   ├─ clipboard.py      → xclip / wl-copy / pyperclip
│   ├─ typer.py          → xdotool / ydotool
│   ├─ aipp.py           → optional LLM call (Ollama/OpenAI)
│   ├─ logger.py         → in-memory + file log
│   └─ whisp_core.py     → QThread helper for GUI / tray
│
├─ cli/cli_main.py       REPL loop; hotkey via IPC
├─ gui/main.py           pill-button PyQt window
├─ whisp_mode/tray.py    background tray app
│
├─ utils/                orchestration & tooling
│   ├─ core_runner.py    ← **the orchestrator**; glues core pieces
│   ├─ setup_utils.py    env / dependency checker
│   ├─ ipc_{server,client}.py   Unix-socket hotkey trigger
│   └─ benchmark_utils.py etc.
│
└─ defaults/config.yaml  factory settings (copied to XDG config dir)
```

Outside `src/` you have:

* `setup.sh` + `setup_ydotool.sh` – convenience installers for Linux.
* `whisper.cpp/` clone – the heavyweight C++ backend.
* `development/` – design notes, exporter script, dev log.

---

## 3 ⃣ How a single dictation round trips

1. **Trigger**
   *CLI*: command `r` / hotkey. *GUI / Tray*: button / hotkey.
   → `ipc_server` wakes `AudioRecorder`.

2. **Record**
   `AudioRecorder` streams mic frames into RAM, dumps `last_recording.wav` (temp or preserved).

3. **Transcribe**
   `WhisperTranscriber` chooses a whisper-cli binary (bundled, PATH, or auto-build) and runs

   ```bash
   whisper-cli -m <model> -f recording.wav -otxt -of <output_prefix>
   ```

   Parses the `.txt` file, drops timestamps ➜ clean `tscript`.

4. **AIPP (optional)**
   If `aipp_enabled`, `aipp.py` calls Ollama or OpenAI and returns `ai_output`.

5. **Automation**

   * Clipboard: `ClipboardManager.copy(tscript)`
   * Typing (if enabled): `SimulatedTyper.type(tscript)` via `xdotool` or `ydotool`.

6. **Logging + Metrics**
   `SessionLogger` stores `[timestamp] transcript` (+ `[ai output] …`).
   If `collect_metrics`, `benchmark_utils.write_perf_entry()` appends timings / hw stats to a CSV.

---

## 4 ⃣ What already feels solid

* **Clear modular split** – recorder, transcriber, typer, clipboard all decouple nicely.
* **Wayland/X11 abstraction** – detects backend and nudges user to install ydotool or xdotool.
* **Lazy resource discovery** – falls back to bundled whisper binary or builds on the fly.
* **IPC hotkey trick** – single global shortcut talks to whichever mode is running.

---

## 5 ⃣ Quirks & opportunities (a short hit-list)

| Area                     | Observation                                                                         | “First-fix” ideas                                                                                    |
| ------------------------ | ----------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| **Packaging**            | Hard-coded paths (`whisper.cpp/models/…`) assume you’re in the repo root.           | Adopt the `platformdirs` cache pattern everywhere (you already do this in a few places).             |
| **Implicit namespace**   | `src/whisp/__init__.py` is empty ➜ good, but some subdirs still lack `__init__.py`. | Add them or switch to PEP 420 src-layout conventions consistently.                                   |
| **GUI / Tray threading** | `CoreProcessThread` holds a bunch of heavy objects each run.                        | Consider re-using the transcriber / typer objects across recordings to shave startup cost.           |
| **AIPP**                 | Blocking HTTP call in GUI thread if someone wires it wrong.                         | Wrap in the same worker thread or an async future.                                                   |
| **setup.sh**             | Does *a lot* (venv, whisper.cpp build, global deps) and calls `sudo` liberally.     | Split “build whisper.cpp” into a Shopify-style “optional extras” script, keep wheel install minimal. |
| **Metrics CSV**          | Many columns from requirements doc aren’t yet captured (GPU %, etc.).               | Hook `psutil` + maybe `pynvml` (if NVIDIA) to gather RAM/GPU stats.                                  |


