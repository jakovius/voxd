Thinking through **architecture**, **bootstrapping**, **workflow order**, and **dev practices**.
Here’s a detailed guide on how to **approach and scaffold the full Whisp App** implementation.

---

## ✅ Phase 1: **Project Bootstrapping**

### 📁 1. Create the Project Structure (match the planned layout)

Use the structure from the requirements:

```bash
mkdir -p whisp/{core,gui,cli,whisp_mode,utils}
touch whisp/{__main__.py,setup.sh,setup.py,test.py,requirements.txt,config.yaml}
```

Then inside each folder:

```bash
touch whisp/core/{config.py,logger.py,recorder.py,transcriber.py,clipboard.py,typer.py}
touch whisp/gui/main.py
touch whisp/cli/cli_main.py
touch whisp/whisp_mode/tray.py
touch whisp/utils/{setup_utils.py,benchmark_utils.py}
```

### 🔧 2. Initialize Git

```bash
git init
```

---

## ✅ Phase 2: **Core Utilities and Configuration**

> 🔁 These should be done first as all other parts depend on them.

### 📌 1. `config.py`
- Read & validate config file
- Default fallback creation if not present
- Supports YAML or JSON

### 📌 2. `setup.sh`
- `setup.sh`:
  - Check/install system deps
  - Clone/build whisper.cpp
  - Set up Python & venv

---

## ✅ Phase 3: **Core Modules**

Once config is loadable and deps are in place:

### 🎤 1. `recorder.py`
- Uses `sounddevice`
- Outputs `.wav` for whisper.cpp

### 📄 2. `transcriber.py`
- Runs whisper.cpp binary
- Parses timestamped output (`orig_tscript`)
- Trims timestamps to produce `tscript`

### 🖱️ 3. `clipboard.py`
- Uses `pyperclip`, `xclip`, or `wl-clipboard`

### ⌨️ 4. `typer.py`
- Handles X11/Wayland typing via `ydotool`
- Optional: implement delay & speed settings

### 📓 5. `logger.py`
- Handles session logging string
- Writes to file on exit
- Appends `[ai output]` if present

---

## ✅ Phase 4: **Application Modes**

After core logic is working:

### 🖥️ 1. `cli_main.py` (CLI Mode)
- Run loop with commands (`r`, `rh`, `l`, `cfg`, `x`, etc.)
- Calls core process
- Handles logging, performance mode, config edit

### 🎛️ 2. `tray.py` (WHISP Mode)
- System tray icon with status updates
- Handles hotkey triggers
- Menu options (start/stop recording, log, config, test, quit)

### 🪄 3. `main.py` (GUI Mode)
- Use `PyQt6` for minimal GUI
- Pill-shaped central button
- Show latest `tscript`, options menu

---

## ✅ Phase 5: **Extra Features**

### 🧠 1. AIPP (AI Post Processing)
- `core/aipp.py`
- Sends `tscript` to local Ollama or remote API
- Reads config: model, prompt, API key
- Returns `ai_output`

### 📊 2. Performance Metrics
- Collects timestamps, durations, memory & CPU data
- Writes to `performance_data.csv`
- Optional: use `psutil` for hardware stats

### 🧪 3. `test.py`
- CLI for:
  - Single test
  - Benchmarks (same audio, multiple models)
  - Analyze CSV
  - Diagnostics
  - Dry run (dummy inputs)

---

## ✅ Phase 6: **Final Touches**

### 📦 Packaging
- Add `pyproject.toml` or `setup.cfg` for packaging
- Use `AppImage` tools (like `linuxdeploy`) to bundle everything
- Optional: PyInstaller spec file for `.bin` builds

### 🧪 Testing
- Unit tests: core modules
- Integration tests: CLI/GUI behavior

### 📚 Documentation
- `README.md`: features, install, usage

### Project Structure
```
whisp/
├── __main__.py
├── core/
│   ├── config.py
│   ├── logger.py
│   ├── recorder.py
│   ├── transcriber.py
│   ├── clipboard.py
│   ├── aipp.py
│   ├── whisp_core.py
│   └── typer.py
├── gui/
│   └── main.py
├── cli/
│   └── cli_main.py
├── whisp_mode/
│   └── tray.py
├── utils/
│   ├── setup_utils.py
│   ├── benchmark_utils.py
|   ├── ipc_client.py
│   ├── ipc_server.py
│   ├── test.py
│   └── core_runner.py   ← orchestrates full core process
├── setup.sh
├── test.py
├── requirements.txt
├── README.md
├── LICENSE
├── config.yaml
├── .gitignore
|   --- dependencies (virtual env, whisper.cpp) and git ---
├── .venv/
├── .git/
└── whisper.cpp/
```

---

## 🧭 Suggested Implementation Order

| Priority | Module/File | Purpose |
|---------|--------------|--------|
| 🥇 1 | `config.py`, `setup.sh` | Foundational |
| 🥈 2 | `recorder.py`, `transcriber.py`, `clipboard.py` | Core pipeline |
| 🥉 3 | `cli_main.py` | First mode to validate everything |
| 4 | `logger.py`, `typer.py` | Session logging, simulated typing |
| 5 | `tray.py`, `main.py` | GUI and WHISP modes |
| 6 | `ai_processor.py`, `benchmark_utils.py`, `test.py` | AIPP, diagnostics, benchmarking |

---

🛠️ setup.sh — System Setup Script
Handles:
- Installing system packages
- Building whisper.cpp
- Creating virtualenv

🔧 Notes:
Assumes requirements.txt exists in root (we’ll create this next).

whisper.cpp uses default ggml-base.en.bin model.

Compatibility with X11 or Wayland.

---


**`requirements.txt`**, matching all required and optional components for Whisp App based on the suggested architecture.

config.py
does the following:
- Load and validate this config.
- Provide a global access object.
- Auto-fill defaults if keys are missing.

---

recorder.py.

This module will:

Use sounddevice (or optionally pyaudio) to record from the microphone.

Save the recording as a .wav file (e.g., recorded.wav).

Be reusable by CLI/GUI modes and test/benchmarking.

🧠 Notes:
Uses sounddevice, configured for 16 kHz mono.

Records into memory and saves as .wav upon stop.

Automatically generates timestamped file names if none given.

Rescales float32 input to 16-bit PCM (int16), as required by most STT engines.

---

📄 whisp/core/transcriber.py
This module:

Calls the whisper.cpp binary with proper arguments.

Extracts the full transcript with timestamps (orig_tscript) from the .txt output.

Strips timestamps to create the clean tscript.

🧪 Example usage:
```python
if __name__ == "__main__":
    transcriber = WhisperTranscriber(
        model_path="whisper.cpp/models/ggml-base.en.bin",
        binary_path="./whisper.cpp/main"
    )
    tscript, orig = transcriber.transcribe("recording_20240403_120400.wav")
    print("\n=== Cleaned Transcript ===\n", tscript)
```

🧠 Notes:
Outputs are saved in whisp_output/ and .txt files are reused if already generated.

---

📄 whisp/core/clipboard.py

🧪 Usage Example:
```python
from core.clipboard import ClipboardManager

cb = ClipboardManager(backend="auto")  # or explicitly: "xclip", "wl-copy", "pyperclip"
cb.copy("Hello from Whisp!")
```

🧠 Features & Notes
Uses pyperclip as a fallback if xclip/wl-copy are not found.

Allows override via config: clipboard_backend: "xclip" etc.

Designed for synchronous use — no clipboard polling.

---
📄 whisp/utils/core_runner.py

🧠 Features:
Modular: every component is pluggable and swappable.

Parameters:

preserve_audio: store file for reuse/benchmarking.

simulate_typing: should it type the result?

apply_aipp: (future) use AI post-processing.

✅ Example usage from cli_main.py:
python
Copy
Edit
from core.config import AppConfig
from utils.core_runner import run_core_process

cfg = AppConfig()
tscript = run_core_process(cfg, preserve_audio=False, simulate_typing=True)
print("\nFinal transcript:\n", tscript)
---
 whisp/core/typer.py

 ✅ Goals
Simulate typing each character of tscript with a configurable delay.

Use:

ydotool

Example
```python
if __name__ == "__main__":
    typer = SimulatedTyper(delay=0.02)
    typer.type("Hello from Whisp App!")
```

🧠 Notes
Works best when focus is already on a text field.
Delay is per character. Could be improved with buffered chunks if needed.
You may want to warn the user if no compatible backend is installed and offer a --simulate-install CLI flag.

---

📄 whisp/core/logger.py

logger.py module, responsible for:

Storing session logs (each tscript, optionally ai_output)
Writing them to a file at the end of the session (or on demand)
Appending with timestamps
Supporting default-named file if none specified

🧪 Example
```python
if __name__ == "__main__":
    logger = SessionLogger(True)
    logger.log_entry("Hello world.")
    logger.log_entry("[ai output] Summary of your message.")
    logger.show()
    logger.save()
```

🧠 Notes
log_entry() stores to memory (no immediate write).
save() appends to file (can be triggered once per session).
Integrates cleanly into core_runner.py after clipboard or AIPP.
---

📄 whisp/cli/cli_main.py

✅ Goals for CLI Mode
Loop: wait for commands (r, rh, l, cfg, x, h)

On r (or "rh" for hotkey trigger), run the full core process
On l, show and optionally save the current log
On cfg, open the config file in default editor
Clean exit on x

---

📄 whisp/gui/main.py

✅ Key Features in PyQt6 GUI:
Pill-style central button with status (Whisp, Recording, etc.)

Transcript preview
Clipboard notice
Options menu:
Show log
Open config
Run test (stubbed)
Quit

Non-blocking threading for core process
Integrated with AppConfig, core_runner, SessionLogger

✅ Summary of Integration
Uses AppConfig, SessionLogger, and run_core_process() from existing modules
Non-blocking via QThread to keep GUI responsive
All features match your spec, including clipboard integration and future AIPP/test stubs
Option buttons open real config and show/save logs

🧪 Example Usage

```bash
source .venv/bin/activate
python -m gui.main
```
---

📄 whisp_mode/tray.py

✅ Goals (as per the spec):
Start in background with system tray icon showing status:

Whisp, Recording, Transcribing, Typing
React to a global hotkey (e.g. ctrl+alt+r) to trigger the core process

Tray menu:
Start/Stop recording
Show/Save session log
Open settings (xdg-open config.yaml)
Run test (placeholder)
Quit

Use PyQt6 here too, since it supports system tray and integrates with the GUI stack.

✅ Notes:
Integrates with AppConfig, SessionLogger, and core_runner
Global hotkey runs the core process without UI focus
Requires an icon PNG file at whisp/assets/icon.png

🧪 To Run:
```bash
python -m whisp_mode.tray
```

✅ The entire architecture now has:

CLI with hotkey and flags
PyQt6 GUI mode
WHISP tray mode
Modular and reusable core logic

---

## 🔜 Next: `test.py` — Test / Benchmark / Diagnostics Utility

As per requirements, this utility will support:

### Modes:
- ✅ **Test** — run one core process and collect performance metrics
- ✅ **Benchmark** — run multiple models on same audio input
- ✅ **Analyze** — summarize `performance_data.csv`
- ✅ **Diagnostics** — check system dependencies, config, model files
- ✅ **Dry-run** — for CI/testing

---

## 📄 `test.py`
including all four modes: **test**, **benchmark**, **analyze**, and **diagnostics**, each with placeholder or basic functionality wired to your architecture.


## ✅ To Run:

```bash
# Single test run (with metrics)
python test.py test

# Benchmark mode (transcribe same audio with multiple models)
python test.py benchmark --audio recordings/sample.wav --models whisper.cpp/models/ggml-base.en.bin whisper.cpp/models/ggml-tiny.en.bin

# Analyze performance data
python test.py analyze

# Check system/config sanity
python test.py diagnostics

# Load modules without doing anything
python test.py dry
```

---

## 📄 `whisp/__main__.py`

---

✅ Purpose of __main__.py
This file acts as the main entry point when the module is run directly (like a script). It's especially useful when distributing your project as a package or making it more user-friendly.

---

✅ Loads the `app_mode` from `config.yaml` (as default)  
✅ Allows you to override the mode from the command line via `--mode`  
✅ Supports all four modes: `cli`, `gui`, `whisp`, `hear`  
✅ Falls back cleanly on unknown modes

---
## ✅ Example Usage (from outside the project folder):

```bash
# Use mode from config.yaml
python -m whisp

# Override to GUI
python -m whisp --mode gui

# One-off dictation (HEAR mode)
python -m whisp --mode hear
```

This ensures `whisp` behaves like a polished, production-ready entry point with both configuration and CLI flexibility.

---

✅ Plan to Implement AIPP
We’ll build a new module:

📄 core/aipp.py

With:

run_aipp(text: str, cfg: AppConfig) -> str

if provider == "local" → call Ollama via HTTP

if provider == "remote" → call OpenAI or other API

And plug that into core_runner.py.


✅ core/aipp.py is now implemented with:

run_aipp() dispatcher (based on cfg.aipp_provider)

run_ollama_aipp() — sends prompt to a local Ollama instance

run_openai_aipp() — sends prompt to OpenAI Chat Completions API

---

✅ core_runner.py is to be fully integrated with aipp.py:

Runs AIPP if apply_aipp and cfg.aipp_enabled are true

Logs [ai output] ... to the session log

Measures and logs AIPP duration, model, provider, and efficiency

---

## ✅ **How to get `ydotool` working on Wayland**

### 🧠 Context:
Wayland doesn’t allow traditional X11 tools like `xdotool` to simulate keyboard input, due to stricter security. `ydotool` is a low-level input simulation tool that *can* work on Wayland, but it needs special setup — including `uinput` device access and a background daemon.

---

### 🔧 What was done:

#### 1. **Cloned and built `ydotool` from source:**
We installed the necessary build dependencies and compiled `ydotool` from [ReimuNotMoe's GitHub repo](https://github.com/ReimuNotMoe/ydotool).

```bash
git clone https://github.com/ReimuNotMoe/ydotool.git
cd ydotool
cmake -B build
make -j$(nproc)
sudo make install
```

#### 2. **Granted access to `/dev/uinput`:**
This device is needed to simulate input events. We:
- Added a udev rule to allow users in the `input` group access:
  ```bash
  echo 'KERNEL=="uinput", MODE="0660", GROUP="input"' | sudo tee /etc/udev/rules.d/99-uinput.rules
  ```
- Reloaded udev rules:
  ```bash
  sudo udevadm control --reload-rules && sudo udevadm trigger
  ```

#### 3. **Added the current user to the `input` group:**
```bash
sudo usermod -aG input $USER
```
> ⚠️ **A full system reboot** (not just logout/login) was required for the new group membership to take effect.

#### 4. **Set up a persistent user daemon with `systemd`:**
We created a `~/.config/systemd/user/ydotoold.service` file to run the `ydotoold` daemon automatically at login, using a user-specific UNIX socket:
```ini
[Unit]
Description=ydotool user daemon
After=default.target

[Service]
ExecStart=/usr/local/bin/ydotoold --socket-path=%h/.ydotool_socket --socket-own=%U:%G
Restart=on-failure

[Install]
WantedBy=default.target
```

Then enabled and started the service:
```bash
systemctl --user daemon-reexec
systemctl --user enable --now ydotoold.service
```

#### 5. **Added the socket path to the environment:**
We exported this path and added it to the user's `.bashrc`:
```bash
export YDOTOOL_SOCKET="$HOME/.ydotool_socket"
```

---

### 🧪 Final Verification:

After reboot:
- Confirmed group membership: `groups` → should show `input`
- Verified daemon is running: `systemctl --user status ydotoold`
- Ran a typing test:
  ```bash
  ydotool type "🚀 We have liftoff!"
  ```

If text appeared as simulated input — success! 🎉

---

### ❗Key Gotchas:
- **Must reboot** after adding to `input` group — logout won’t cut it.
- **Systemd user session** must be active — won’t work in sessions started via `startx` unless systemd is enabled for the user session.
- No need to use `wtype` if `ydotool` is installed — they're redundant.

---

### IPC Hotkey Implementation

1. **IPC Server Setup** (in CLI mode):
```python
# In cli_main.py
hotkey_event = threading.Event()

def on_ipc_trigger():
    print("\n[IPC] Hotkey trigger received.")
    hotkey_event.set()

# Start IPC server for hotkey triggers
start_ipc_server(on_ipc_trigger)
```

2. **Hotkey Recording Mode** (`rh` command):
- Uses `threading.Event()` to synchronize between IPC trigger and recording
- First trigger starts recording
- Second trigger stops recording
- Continues in loop until Ctrl+C

### System Shortcut Setup

**Correct Command for GNOME/Wayland:**
```bash
bash -c 'PYTHONPATH=/home/jacobi/.project/ python3 -m whisp --trigger-record'
```

This works because:
- `bash -c` ensures command runs in a proper shell environment
- `PYTHONPATH` is set correctly to find the package
- Command runs regardless of working directory

### Setup Instructions

1. **Open Settings** → **Keyboard** → **Keyboard Shortcuts**
2. **Add Custom Shortcut:**
   - Name: `Whisp Record`
   - Command: `bash -c 'PYTHONPATH=/home/jacobi/.project/ python3 -m whisp --trigger-record'`
   - Shortcut: Your chosen key combination (e.g., `Ctrl+Alt+R`)

### Usage Flow

1. Run Whisp in CLI mode
2. Enter `rh` to start hotkey recording mode
3. Press system shortcut to start recording
4. Press system shortcut again to stop recording
5. Transcription happens automatically
6. Repeat or Ctrl+C to exit hotkey mode

---

2025-05-20

a big refactor:

Below is a pragmatic “internal code-review” of **Whisp** with the two targets called out:

1. **“Works-anywhere” installation** (pip/pipx, Poetry, virtualenvs, system deps).
2. **Running the app from *inside* the project directory (or after `pip install`) instead of *one directory up*.**

---

## 1  Current root-layout & import situation

```
whisp/                   ← project root *and* the Python package name
  core/
  cli/
  gui/
  utils/
  whisp_mode/
  __main__.py
  setup.sh …
```

* • There is **no `__init__.py`** anywhere, so each sub-dir is an *implicit* namespace package.
* • Every file imports with an **absolute, “double-whisp” path**:

  ```py
  from whisp.core.config import AppConfig
  from whisp.cli.cli_main import cli_main
  ```

When you sit **one level above** the folder and run

```bash
python -m whisp           # or python -m whisp.cli.cli_main
```

Python happily finds a *top-level* package called `whisp` (the directory
it sees on `sys.path`).
But the moment you `cd whisp` and try to run `python -m cli.cli_main`,
the interpreter now thinks *that directory itself* is the *root of the
import tree* and promptly fails to find a sibling “whisp” top-level
package → `ModuleNotFoundError: whisp.core …`.

---

## 2  Fixing the layout

| 🔥 Today                                                                   | ✅ Proposed                                                                                           | Why it helps                                                                     |
| -------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| The repository directory **is** the importable package.                    | Make the repo root “just a repo”, and put all code under **`src/whisp/`** (PEP 420 “src-layout”).    | • No more path confusion. <br>• Editable installs (`pip install -e .`) work.     |
| No `__init__.py` files → implicit namespace pkgs.                          | Add **`src/whisp/__init__.py`** (can be empty) *plus* `__init__.py` in each first-level sub-package. | Explicit is better than implicit; tools (mypy, IDEs, zipapps) behave.            |
| Imports are *hard-wired absolute* (`from whisp.core…`).                    | **Keep** absolute imports (they’re fine) *but* the dir hierarchy now matches them.                   | No code changes needed except moving files.                                      |
| Scripts run via `python -m whisp …` only if parent dir is on `PYTHONPATH`. | Ship **console-scripts entry-points** in `pyproject.toml`:<br>`whisp = "whisp.__main__:main"`        | `pipx install .` gives the user a global `whisp` command; no more path juggling. |

> **Minimal folder diff**

```
repo_root/
  pyproject.toml
  README.md
  src/
    whisp/
      __init__.py
      __main__.py
      core/
      cli/
      gui/
      utils/
      whisp_mode/
  tests/
  assets/
```

*(You can literally `git mv` the five code directories into `src/whisp/`
and add the missing `__init__.py` files.)*

---

## 3  Packaging for painless installation

### 3-line `pyproject.toml` (PEP 621 + Hatchling example)

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "whisp"
version = "0.1.0"
dependencies = [  # copy requirements.txt here
  "pyqt6", "sounddevice", ...                       # ← keep it short; pin *ranges* not exact versions
]
[project.scripts]
whisp = "whisp.__main__:main"
```

* `pip install .` (or `pipx install .`) now:

  * adds *whisp* to `site-packages`, so absolute imports resolve anywhere;
  * drops a **`whisp` CLI** in `$PATH`;
  * means users never touch `PYTHONPATH`.
* Keep the **C++ whisper.cpp build** separate:

  * treat it as an **optional extra** (`pip install whisp[cpp]`) that runs
    a build hook, or
  * just detect the binary at runtime (your current `setup_utils`
    already does that).

### What to do with `setup.sh`

* Split the “pure Python” install (handled by pip) from the **system
  extras** (ffmpeg, xdotool/ydotool, CMake, whisper.cpp compile).
* Convert `setup.sh` into a **helper** that prints the apt lines *but
  doesn’t insist on being run inside the repo*.

---

## 4  Runtime paths that break after installation

| Code                                            | Problem after `pip install`                           | Quick fix                                                                                   |
| ----------------------------------------------- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `CONFIG_PATH = Path("config.yaml")`             | Looks in the *current working dir*.                   | Use **`platformdirs`** (`user_config_dir("whisp")`) and copy a default config on first run. |
| Assets (`assets/icon.png`)                      | Relative paths fail when launched from anywhere else. | Bundle with **`importlib.resources`** (`files("whisp.assets").joinpath("icon.png")`).       |
| Whisper model default `"whisper.cpp/models/…"`. | Same issue.                                           | Let the user set `WHISP_MODEL_PATH` env var or config; fall back to an XDG cache directory. |
| `open("whisp_output/…")`                        | Creates dirs all over CWDs.                           | Move to XDG `user_cache_dir("whisp")`.                                                      |

---

## 5  Step-by-step migration plan

1. **Move code into `src/whisp/`, add `__init__.py`.**
   All imports keep working because the package name stays **whisp**.

2. **Add `pyproject.toml` + 1-line `hatch build` smoke test.**

3. **Replace ad-hoc `python -m whisp …` docs** with:

   ```bash
   # dev install
   pip install -e .
   whisp --mode cli
   ```

4. **Refactor path-sensitive code**

   * minimise `os.chdir` (in `__main__.py`) – it masks path bugs;
   * switch to `platformdirs` + `importlib.resources`.

5. **CI sanity-check:**

   * `python -m pip install .`
   * `whisp --diagnose` (make sure no ModuleNotFoundError, assets OK).

6. **Mark shell helpers optional:**

   * rename `setup.sh` → `extras/linux_setup.sh`;
   * print “run me if you want clipboard typing on Wayland”.

---

## 6  Tiny but high-impact code tweaks

| File            | Change                                                                                                                                     |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `__main__.py`   | Delete `os.chdir`, rely on resource paths.                                                                                                 |
| `utils/libw.py` | Replace `from whisp.core.config import AppConfig` with lazy import inside `verbo` to avoid importing full config during package discovery. |
| Every directory | Add `__all__ = [...]` in `__init__.py` for IDE auto-complete.                                                                              |
| Tests           | Move interactive scripts in `utils/test.py` under `tests/` and turn them into pytest functions – they’ll run in CI after `pip install`.    |

---

## 7  What this buys you

* **`pipx install whisp`** → users get a self-contained CLI/GUI in one command.
* You can publish **wheels** to PyPI; no manual git clone & `setup.sh`.
* Contributors can `pytest` or run the GUI from anywhere without import gymnastics.
* Linux-distro packagers get a textbook src-layout; no “cd one folder up” hacks.

---

### Final thought

The codebase is already nicely modular; the *only* major blocker to
smooth adoption is the **package/distribution story**.
Reshaping the folder tree and shipping a minimalist `pyproject.toml`
turns Whisp from “it works on my box if I set PYTHONPATH” into a
standard Python application that can live in virtualenvs, containers,
or global brew/pip installs with zero surprises.
