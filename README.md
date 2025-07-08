# Whisp - Talk & Type on Linux 🗣️⌨️

A fast voice-to-text helper for **any** Linux app, using **LOCAL** voice processing.  
Hit a **global shortcut**, speak, and watch your words appear wherever the cursor lives.  
Optionally, have your transcript **AI-rewritten** by **LOCAL** (Ollama) or remote AI model before output. 

---

## Highlights

| Feature                          | Notes                                                                   |
| -------------------------------- | ----------------------------------------------------------------------- |
| **Whisper.cpp** backend          | Local, offline  ASR.   |
| **Simulated typing**             | types straight into any currently focused input window. Even on Wayland! (*ydotool*).                   |
| **Clipboard**                    | Auto-copies into clipboard - ready for pasting        |
| **Multiple UI** surfaces             | CLI, GUI (minimal PyQt6), TRAY (system tray) |
| **Logging** & **performance**             | Session log plus opt-in local performance data (CSV).                          |
| AI Post-Processing (**AIPP**)	     | Process transcripts via local or cloud LLMs. GUI prompt editor.         |

---


## 📦 Installation

**Works on modern Linux** – Ubuntu 24.04, Fedora 40, Pop!\_OS 22, etc.  
After this you will have a global `whisp` command available in any shell.

```bash
git clone https://github.com/jacob8472/whisp.git
cd whisp && ./setup.sh    # builds deps *and* installs a global `whisp` command
```

The setup script now offers to install **pipx** automatically (default *Yes*)
and registers the `whisp` command on your `$PATH`.  Developers can still run

```bash
pipx install --editable .
```

after cloning if they prefer an editable install.

---

## 🏃 Usage — Setting up a **global Record/Stop shortcut**

1. **Open your system keyboard-shortcuts panel**
   *GNOME:* Settings → Keyboard → "Custom Shortcuts"
   *KDE / XFCE / Cinnamon:* similar path.

2. **Add a new shortcut:**

| Field        | Value *(copy the command exactly)*               |
| ------------ | ---------------------------------- |
| **Name**     | Whisp • Record                     |
| **Command**  | `bash -c 'whisp --trigger-record'` |
| **Shortcut** | e.g. `Super + r`              |

3. Click **Add / Save**.
4. Launch Whisp in any mode (CLI, GUI, or tray). From now on:

| Press hotkey …   | Whisp does …                                                |
| ---------------- | ----------------------------------------------------------- |
| **First press**  | start recording                                             |
| **Second press** | stop ⇢ transcribe ⇢ copy to clipboard ⇢ (typing if enabled) |

### Quick-start examples

```bash
whisp --gui      # friendly pill-button window
whisp --tray    # sits in the tray; perfect for continuous dictation
whisp --cli      # terminal REPL; 'h' shows commands
```

*(The very first run may download/build its own `whisper-cli` into the app's root — symlinks it to `~/.local/bin/` — subsequent starts are instant.)*


### 🎙️  Managing speech models

Whisp needs a Whisper GGML model file.  
Use the built-in model-manager to fetch the default (≈142 MB):

```bash
whisp-model install base.en     # or tiny.en / small / medium … see list below
```
That downloads into ~/.local/share/whisp/models/ and Whisp will
automatically pick it up.

Common commands:
```bash
whisp-model list	# show models already on disk
whisp-model install tiny.en  #	download another model ("fetch" can be also used as alias for "install")
whisp-model --no-check install base.en # download a model and skip SHA-1 verification (rarely needed)
whisp-model remove tiny.en	# delete a model
whisp-model use tiny.en	# make that model the default (edits config.yaml)
```

Some of the available keys (size MB):

tiny.en 75 · tiny 142 · base.en 142 · base 142 ·
small.en 466 · small 466 · medium.en 1500 · medium 1500 · large-v3 2900

---

## ⚙️ Config (first-run auto-generated)

Available to edit in GUI and TRAY modes, as well as for power-users here:
`~/.config/whisp/config.yaml`
Unknown keys are ignored.

---

## 🧠 AI Post-Processing (AIPP)
Your spoken words can be magically cleaned and rendered into e.g. neatly formated email, or straight away into a programing code!  

Whisp can optionally post-process your transcripts using LOCAL (on-machine, **Ollama**) or cloud LLMs (like **OpenAI, Anthropic, or xAI**).  
For the local processing, first **[install Ollama](https://ollama.ai)** and download a model that can be run on your machine, e.g. `ollama pull gemma3:latest`.   
You can enable, configure, and manage prompts directly from the GUI.

### Enable AIPP:
In CLI mode, use `--aipp` argument.  
In GUI or TRAY mode, all relevant settings are in: "*AI Post-Processing*".  
**Seleting provider & model** - models are tied to their respective providers!  
**Editing Prompts** - Select "*Manage prompts*" or "*Prompts*" to edit up to 4 of them.

## Supported providers:

- Ollama (local)  
- OpenAI  
- Anthropic  
- xAI  

---

### 🔑 Setting API Keys for the remote API providers

For security, Whisp does **not** store API keys in config files.  
To use cloud AIPP providers, set the required API key(s) in your shell environment before running Whisp:

```sh
# For OpenAI
export OPENAI_API_KEY="sk-..."

# For Anthropic
export ANTHROPIC_API_KEY="..."

# For xAI
export XAI_API_KEY="..."
```

You can add these lines to your `.bashrc`, `.zshrc`, or equivalent shell profile for convenience.

**Note:**  
If an API key is missing, cloud-based AIPP providers will not work and you will see an error.

---

## 🩺 Troubleshooting cheatsheet

| Symptom                            | Likely cause / fix                                                                                             |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| *Press hotkey, nothing happens*    | Troubleshoot with this command: `gnome-terminal -- bash -c "whisp --trigger-record; read -p 'Press Enter...'"` |
| *Transcript printed but not typed* | Wayland: `ydotool` not installed or user not in `input` group → run `setup_ydotool.sh`, relog.                 |
| *"whisper-cli not found"*          | Build failed - rerun `./setup.sh` and check any diagnostic output.                                                      |
| *Mic not recording*                | Verify in system settings: **input device available**? / **active**? / **not muted**?                                        |
| Clipboard empty                    | ensure `xclip` or `wl-copy`  present (re-run `setup.sh`).                                |

---

## 📜 License & Credits

* Whisp – © 2025 Jakov Ivkovic – **MIT** license (see [`LICENSE`](LICENSE)).
* Speech engine powered by [**ggml-org/whisper.cpp**](https://github.com/ggml-org/whisper.cpp) (MIT) and OpenAI Whisper models (MIT).
* Auto-typing/pasting powered by [**ReimuNotMoe/ydotool**](https://github.com/ReimuNotMoe/ydotool) (AGPLv3).

---

## Removal

**If the app was installed via `git clone` and running `setup.sh`:**

```bash
cd ~/where/you/cloned/whisp
rm -rf .venv # kill the virtual-env
rm -rf whisper.cpp # if whisper.cpp was built in the same folder
cd .. && rm -rf whisp # remove the repo folder
```

**If the app was installed via `pipx install .`:**

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

# 3. wipe Whisp's XDG dirs
rm -rf ~/.config/whisp        # settings file
rm -rf ~/.cache/whisp         # auto-built whisper.cpp, downloaded models, logs

# 4. any stray desktop launchers or symlinks
rm -f ~/.local/share/applications/whisp.desktop
sudo rm -f /usr/local/bin/whisp  # only if you manually linked it
```

Enjoy seamless voice-typing on Linux - and if you build something cool on top, open a PR or say hi!
