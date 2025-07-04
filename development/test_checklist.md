## ✅ Whisp App Testing Checklist

### 🔹 Global Setup
- [ ] ✅ `config.yaml` loads with all default values
- [ ] ✅ `setup.sh` installs everything cleanly
- [ ] ✅ `requirements.txt` installs without errors
- [ ] ✅ `whisper.cpp` builds and runs with default model
- [ ] ✅ `whisper.cpp` model file exists and is correct

---

### 🔸 CLI Mode (`cli_main.py`)
- [ ] `python -m cli.cli_main` launches
- [ ] Typing `r` starts recording, pressing ENTER stops
- [ ] Transcript is printed and copied to clipboard
- [ ] typing `rh` enables hotkey mode - works when termnal in the background and enables voice typing in any app
- [ ] `l` shows session log; can be saved
- [ ] `cfg` opens the config file
- [ ] `x` exits the CLI
- [ ] `--save-audio` preserves `.wav` file in `recordings/`
- [ ] `--test-file path.wav` transcribes existing file

---

### 🔸 Hotkey Triggering
- [ ] Hotkey from config (e.g. `ctrl+alt+r`) starts recording in CLI, GUI and whisp (tray) modes
- [ ] Typing works in focused field if simulate_typing = true

---

### 🔸 GUI Mode (`gui/main.py`)
- [ ] Central button starts/stops recording, and trigers transcribing/typing
- [ ] Transcript is displayed under the button (preview)
- [ ] Hotkey starts and stops recording - typing to any active input window happens
- [ ] “Copied to clipboard” label updates
- [ ] Options > Show Log works and can save
- [ ] Options > Settings opens config
- [ ] Options > Test gives placeholder
- [ ] Options > Quit exits cleanly

---

### 🔸 WHISP Tray Mode (`tray.py`)
- [ ] Launches and shows tray icon with status “Whisp”
- [ ] Hotkey starts recording (icon changes)
- [ ] Repeated hotkey stops recording
- [ ] Transcribing and uptake to clipboard executes
- [ ] Typing into any active input window of any app is executed
- [ ] the process completes and tray returns to idle
- [ ] Tray > Session Log displays and allows saving
- [ ] Tray > Settings opens config
- [ ] Tray > Test placeholder works
- [ ] Tray > Quit exits and unregisters hotkey

---

### 🔸 Clipboard & Typing
- [ ] Clipboard works across Wayland/X11
- [ ] Typing outputs into a focused window correctly

---

### 🔸 Logging
- [ ] All transcripts logged with timestamps
- [ ] AIPP entries are logged (if enabled)
- [ ] Log saved to configured or default filename

---

### 🔸 Performance
- [ ] Recordings run under ~1s delay on short phrases
- [ ] App remains responsive under load (GUI + tray + CLI)

---



