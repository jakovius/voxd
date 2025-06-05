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

Below is a drop-in replacement for the **“📦 Installation”** and **“🏃 Usage → Global Hotkey”** parts of `README.md`.
Everything else in the README can stay as is — just splice this in so that new users see the simplest path first.

---


## 📦 Installation

**Works on any modern Linux** – Ubuntu 24.04, Fedora 40, Pop!\_OS 22, etc.  
After this you will have a global `whisp` command available in any shell.

```bash
git clone https://github.com/jacob8472/whisp.git
cd whisp
./setup.sh               # builds whisper.cpp + checks OS dependencies
pipx install .   # ⏱️ <15 s → drops ~/.local/bin/whisp
# if you are developing/hacking, consider instead: `pipx install --editable .`
```

If you don’t have pipx yet:

```bash
sudo apt install -y pipx          # Debian/Ubuntu – use dnf / pacman on other distros
pipx ensurepath                    # makes sure ~/.local/bin is on your $PATH
logout && login                    # or: source ~/.bashrc
```
*Why pipx?*
`pipx` builds its **own** isolated venv under `~/.local/pipx/venvs/whisp/` and writes a tiny shim script to `~/.local/bin/whisp`.
You never have to remember “`source .venv/bin/activate`” again — just run `whisp` like any normal program.

---

## 🏃 Usage — Setting up a **global Record/Stop shortcut**

1. **Open your system keyboard-shortcuts panel**
   *GNOME:* Settings → Keyboard → “Custom Shortcuts”
   *KDE / XFCE / Cinnamon:* similar path.

2. **Add a new shortcut:**

| Field        | Value (copy exactly)               |
| ------------ | ---------------------------------- |
| **Name**     | Whisp • Record                     |
| **Command**  | `bash -c 'whisp --trigger-record'` |
| **Shortcut** | e.g. `Ctrl + Alt + R`              |

3. Click **Add / Save**.
4. Launch Whisp in any mode (CLI, GUI, or tray). From now on:

| Press hotkey …   | Whisp does …                                                |
| ---------------- | ----------------------------------------------------------- |
| **First press**  | start recording                                             |
| **Second press** | stop ⇢ transcribe ⇢ copy to clipboard ⇢ (typing if enabled) |

### Quick-start examples

```bash
whisp --mode gui      # friendly pill-button window
whisp --mode whisp    # sits in the tray; perfect for continuous dictation
whisp --mode cli      # terminal REPL; 'h' shows commands
```

*(The very first run may download/build its own `whisper-cli` into `~/.cache/whisp/` — subsequent starts are instant.)*


### 🎙️  Managing speech models

Whisp needs a Whisper GGML model file.  
Use the built-in model-manager to fetch the default (≈142 MB):

```bash
whisp-model install base.en     # or tiny.en / small / medium … see list below
```
That downloads into ~/.cache/whisp/models/ and Whisp will
automatically pick it up.

Common commands:
```bash
whisp-model list	# show models already on disk
whisp-model install tiny.en  #	download another model ("fetch" can be also used as alias for "install")
whisp-model --no-check install base.en # download a model and skip SHA-1 verification (rarely needed)
whisp-model remove tiny.en	# delete a model
whisp-model use tiny.en	# make that model the default (edits config.yaml)
```

A complete catalogue of available keys (size MB):

tiny.en 75 · tiny 142 · base.en 142 · base 142 ·
small.en 466 · small 466 · medium.en 1500 · medium 1500 · large-v3 2900

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

**If it was installed via `pipx install .`:**

```bash
pipx uninstall whisp # removes venv, script, deps
```
---

**Optional housekeeping:**

```bash
# 1. kill anything still running
pkill -f whisp || true
pkill -f ydotoold || true

# 2. user-level systemd bits (only if you ran setup_ydotool.sh)
systemctl --user stop  ydotoold.service 2>/dev/null
systemctl --user disable ydotoold.service 2>/dev/null
rm -f ~/.config/systemd/user/ydotoold.service

# 3. wipe Whisp’s XDG dirs
rm -rf ~/.config/whisp        # settings file
rm -rf ~/.cache/whisp         # auto-built whisper.cpp, downloaded models, logs

# 4. any stray desktop launchers or symlinks
rm -f ~/.local/share/applications/whisp.desktop
sudo rm -f /usr/local/bin/whisp  # only if you manually linked it
```

Enjoy seamless voice‑typing on Linux – and if you build something cool on top, open a PR or say hi! 🚀
