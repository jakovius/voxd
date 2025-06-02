# Whisp – Talk & Type on Linux 🗣️⌨️

A lightning‑fast voice‑to‑text helper for **any** Linux app.  Hit a global shortcut, speak, and watch your words appear wherever the cursor lives.

---

## ✨ Highlights

| Feature                          | Notes                                                                   |
| -------------------------------- | ----------------------------------------------------------------------- |
| **Whisper.cpp backend**          | Local, offline, MIT‑licensed large‑vocab ASR.                           |
| **One‑key recording**            | Works on Wayland (*ydotool*) **and** X11 (*xdotool*).                   |
| **Clipboard + Simulated typing** | Auto‑copies or types straight into the focused window.                  |
| Multiple UI surfaces             | CLI, minimal PyQt6 GUI, Background Tray (“WHISP”) & one‑shot HEAR mode. |
| Optional AI post‑process         | Summarise / rewrite via local **Ollama** or remote **OpenAI**.          |
| Logs & benchmarks                | Session log plus opt‑in performance CSV.                                |

---

## 🚀 Quick install (Ubuntu / Fedora / Arch / Pop!\_OS)

```bash
# 1. Grab the source
$ git clone https://github.com/jacob8472/whisp.git && cd whisp

# 2. Run one‑shot installer (≈ 2–5 min on first run)
$ ./setup.sh
```

`setup.sh` will:

1. Detect **apt / dnf / pacman** and install build tools, `ffmpeg`, clipboard helpers, etc.
2. Create a local **.venv** and `pip install -r requirements.txt`.
3. Clone & compile **whisper.cpp** under `whisper.cpp/build/`.
4. (Wayland only) Offer to build & enable **ydotool** for simulated typing.

> **Re‑run safe** – if everything’s already present the script exits in seconds.

---

## ⌨️ Setting the Global Hotkey ("Trigger Record")

Whisp listens for a small CLI flag: `--trigger-record`.  Your desktop shortcut should run this **exact command**, *with PYTHONPATH pointing at the repo root* so Python can resolve the package when invoked by the WM.

```bash
bash -c 'PYTHONPATH=/home/$USER/whisp python3 -m whisp --trigger-record'
```

### GNOME / Cinnamon / Budgie

1. **Settings → Keyboard → Custom Shortcuts → “+”**
2. *Name*: **Whisp – Toggle record**
3. *Command*: *(see box above)*
4. *Shortcut*: press <kbd>Ctrl</kbd><kbd>Alt</kbd><kbd>R</kbd> (or anything free)

### KDE Plasma

1. **System Settings → Shortcuts → Custom Shortcuts**
2. *Edit ➜ New ➜ Global ➜ Command/URL* → paste command
3. Assign the key sequence, Apply.

### XFCE / i3 / sway …

Any launcher that can run a shell one‑liner works – just remember the `PYTHONPATH=` prefix or call a wrapper script such as:

```bash
#!/usr/bin/env bash
export PYTHONPATH="$HOME/whisp"
python3 -m whisp --trigger-record
```

Place it in `~/bin/whisp_trigger` and bind the shortcut to that file.

---

## 🏃‍♀️ Usage modes

```bash
# One‑off dictation into clipboard
$ python -m whisp --mode hear

# Interactive shell (quick tests, benchmarks, hotkey loop)
$ python -m whisp --mode cli

# Minimal dark GUI window
$ python -m whisp --mode gui

# Background tray – ideal for day‑to‑day typing
$ python -m whisp --mode whisp
```

*CLI quick keys*

| Key   | Action                                        |
| ----- | --------------------------------------------- |
| `r`   | record (Enter to stop)                        |
| `rh`  | wait for hotkey, record, hotkey again to stop |
| `l`   | show / save session log                       |
| `cfg` | open `config.yaml` in editor                  |
| `x`   | quit                                          |

---

## ⚙️ Config (first‑run auto‑generated)

`~/.config/whisp/config.yaml`

```yaml
app_mode: whisp            # default launch mode
model_path: whisper.cpp/models/ggml-base.en.bin
hotkey_record: ctrl+alt+r  # for reference only – DE shortcut does the real work
simulate_typing: true
clipboard_backend: auto    # xclip / wl-copy / pyperclip fallback
aipp_enabled: false        # AI post‑processing off by default
verbosity: true            # extra console logs
```

Change values, restart Whisp.  Unknown keys are ignored.

---

## 🩺 Troubleshooting cheatsheet

| Symptom                            | Likely cause / fix                                                                             |
| ---------------------------------- | ---------------------------------------------------------------------------------------------- |
| *Press hotkey, nothing happens*    | Shortcut command missing `PYTHONPATH` or wrong path to repo.                                   |
| *Transcript printed but not typed* | Wayland: `ydotool` not installed or user not in `input` group → run `setup_ydotool.sh`, relog. |
| *“whisper-cli not found”*          | Build failed – rerun `./setup.sh` and check cmake output.                                      |
| *Mic not recording*                | Verify in `pavucontrol` the VM’s input device is active and not muted.                         |
| Clipboard empty                    | Disable/enable SPICE clipboard sync in VM; ensure `xclip` or `wl-copy` present.                |

---

## 📜 License & Credits

* Whisp – © 2025 Jakov Iv.
* **MIT** license (see `LICENSE`).
* Speech engine powered by [**ggml‑org/whisper.cpp**](https://github.com/ggml-org/whisper.cpp) (MIT) and OpenAI Whisper models (MIT).

---

## Removal

**If it was installed via `git clone` and running `setup.sh`:**

```bash
cd ~/where/you/cloned/whisp
rm -rf .venv # kill the virtual-env
rm -rf whisper.cpp # if whisper.cpp was built in the same folder
cd .. && rm -rf whisp # remove the repo folder
```

**If it was installed via `pipx install whisp`:**

```bash
pipx uninstall whisp # removes venv, script, deps
```
---

Enjoy seamless voice‑typing on Linux – and if you build something cool on top, open a PR or say hi! 🚀
