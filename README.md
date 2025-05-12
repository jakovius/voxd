# Whisp App

> Talk and type with your voice, in any of your apps!
> A minimal, fast, modular speech-to-text dictation tool using **whisper.cpp**, with **CLI**, **GUI**, tray/background mode (**"WHISP" mode**).

---

## ✨ Features

- 🎤 Fast microphone audio recording (using `sounddevice`)
- 🧠 Transcription with whisper.cpp
- 📋 Automatic clipboard copy of transcript
- ⌨️ Simulated typing into any focused app (even on GNOME/Wayland)
- 🧾 Session logging with timestamps
- 🧠 AI post-processing (optional via local Ollama or a remote LLM)
- 📊 Benchmarking, diagnostics, performance CSV export
- 🖥️ Multiple usage modes:
  - `HEAR`: one-off transcript (from CLI or integration)
  - `CLI`: interactive shell with hotkey and commands
  - `GUI`: minimal dark-mode UI with single button
  - `WHISP`: tray mode with global hotkey

---

## 📦 Installation

### Linux:

#### Clone & Run Setup
```bash
git clone https://github.com/jacob8472/whisp.git
cd whisp
chmod +x setup.sh
sudo ./setup.sh
```

## 🏃 Usage

### Setting Up a Global Hotkey for Whisp App

To enable global hotkey recording:

1. **Open your system’s keyboard shortcuts settings** (e.g., GNOME Settings → Keyboard → Custom Shortcuts).
2. **Add a new shortcut:**
    - **Name:** Whisp: Start Recording
    - **Command:** `bash -c 'PYTHONPATH=/path/to/parent/folder/of/the/project/ python3 -m whisp --trigger-record'`
    - **Shortcut:** (e.g., `ctrl+alt+r`)
3. **Save the shortcut.**
4. In your `config.yaml`, set `hotkey_record` to match your chosen shortcut for reference.

**Running**  
When you are in one of the Whisp running modes (see below), press the shortcut hotkey, the system will run the trigger command, which sends a message to the running Whisp app (CLI, GUI, or Tray) to start recording - then any speech will be recorded - to finish recording and proceed, one should press the hotkey again.

> The shortcut works as long as Whisp App is running in any mode except "hear".

### CLI Mode
```bash
python -m cli.cli_main
```
**Commands:**
- `r` → record audio, press ENTER to stop
- `rh` → wait for hotkey to trigger start recording, and stop with the hotkey trigger again
- `l` → show log
- `cfg` → open config
- `x` → quit
- `--save-audio` → preserve `.wav`
- `--test-file file.wav` → use existing audio

### GUI Mode
```bash
python -m gui.main
```
- Central button to start/stop recording
- works with hotkey as well
- Shows clipboard status and transcript preview
- Options: log, config, test, quit

### WHISP Mode (Tray)
```bash
python -m whisp_mode.tray
```
- Tray icon with menu
- listens for hotkey to start/stop recording
- Runs in background
- ideal for dictation in any app

---

## ⚙️ Configuration

Modify `config.yaml` or open it in the program to customize settings:
```yaml
# Whisp configuration file example
app_mode: CLI
hotkey_record: ctrl+alt+r
model_path: whisper.cpp/models/ggml-base.en.bin
simulate_typing: true
aipp_enabled: false
clipboard_backend: auto
```

---

## 🧪 Testing & Benchmarking

### Test one transcription run
```bash
python test.py test
```

### Benchmark multiple models
```bash
python test.py benchmark --audio recordings/example.wav --models whisper.cpp/models/*.bin
```

### Analyze previous results
```bash
python test.py analyze
```

### Run system diagnostics
```bash
python test.py diagnostics
```

---

## 🧱 Architecture Overview

- `core/` — building blocks: recorder, transcriber, logger, clipboard, typer
- `cli/` — CLI loop
- `gui/` — PyQt6 GUI
- `whisp_mode/` — background tray app
- `utils/` — orchestration, benchmarking, setup utils

---

## 📜 License

Whisp is licensed under the MIT License. See `LICENSE` for details.

---

## 💡 Credits
- whisper.cpp by @ggerganov
