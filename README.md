# VOXT - Talk & Type on Linux 🗣️⌨️

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
After this you will have a global `voxt` command available in any shell.

```bash
git clone https://github.com/jacob8472/voxt.git
cd voxt && ./setup.sh    # builds deps *and* installs a global `voxt` command
```

The setup script now offers to install **pipx** automatically (default *Yes*)
and registers the `voxt` command on your `$PATH`.  Developers can still run

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
| **Name**     | VOXT • Record                     |
| **Command**  | `bash -c 'voxt --trigger-record'` |
| **Shortcut** | e.g. `Super + r`              |

3. Click **Add / Save**.
4. Launch VOXT in any mode (CLI, GUI, or tray). From now on:

| Press hotkey …   | VOXT does …                                                |
| ---------------- | ----------------------------------------------------------- |
| **First press**  | start recording                                             |
| **Second press** | stop ⇢ transcribe ⇢ copy to clipboard ⇢ (typing if enabled) |

### Quick-start examples

```bash
voxt --gui      # friendly pill-button window
voxt --tray    # sits in the tray; perfect for continuous dictation
voxt --cli      # terminal REPL; 'h' shows commands
```

**Add app-menu launchers later**
```bash
./launcher_setup.sh        # pick GUI, Tray, or both
./launcher_setup.sh --edit # fix existing launchers (if they freeze on "Typing...")
```

*(The very first run may download/build its own `whisper-cli` into the app's root — symlinks it to `~/.local/bin/` — subsequent starts are instant.)*


### 🎙️  Managing speech models

VOXT needs a Whisper GGML model file.  
Use the built-in model-manager to fetch the default (≈142 MB):

```bash
voxt-model install base.en     # or tiny.en / small / medium … see list below
```
That downloads into ~/.local/share/voxt/models/ and VOXT will
automatically pick it up.

Common commands:
```bash
voxt-model list	# show models already on disk
voxt-model install tiny.en  #	download another model ("fetch" can be also used as alias for "install")
voxt-model --no-check install base.en # download a model and skip SHA-1 verification (rarely needed)
voxt-model remove tiny.en	# delete a model
voxt-model use tiny.en	# make that model the default (edits config.yaml)
```

Some of the available keys (size MB):

tiny.en 75 · tiny 142 · base.en 142 · base 142 ·
small.en 466 · small 466 · medium.en 1500 · medium 1500 · large-v3 2900

---

## ⚙️ Config (first-run auto-generated)

Available to edit in GUI and TRAY modes, as well as for power-users here:
`~/.config/voxt/config.yaml`
Unknown keys are ignored.

---

## 🧠 AI Post-Processing (AIPP)
Your spoken words can be magically cleaned and rendered into e.g. neatly formated email, or straight away into a programing code!  

VOXT can optionally post-process your transcripts using LOCAL (on-machine, **Ollama**) or cloud LLMs (like **OpenAI, Anthropic, or xAI**).  
For the local processing, first **[install Ollama](https://ollama.ai)** and download a model that can be run on your machine, e.g. `ollama pull gemma3:latest`.   
You can enable, configure, and manage prompts directly from the GUI.

### Enable AIPP:
In CLI mode, use `--aipp` argument.  
In GUI or TRAY mode, all relevant settings are in: "*AI Post-Processing*".  
**Seleting provider & model** - models are tied to their respective providers!  
**Editing Prompts** - Select "*Manage prompts*" or "*Prompts*" to edit up to 4 of them.

## Supported providers:

- **Ollama** (local)  
- **llama.cpp** (local, direct & server modes)
- **OpenAI**  
- **Anthropic**  
- **xAI**  

---

## 🦙 llama.cpp Integration (Local AI)

VOXT includes **native llama.cpp support** for ultra-fast local AI processing without requiring Ollama. This gives you two llama.cpp modes:

- **`llamacpp_server`** - Uses llama.cpp's built-in HTTP server (recommended)
- **`llamacpp_direct`** - Direct Python bindings (fastest, but requires `llama-cpp-python`)

### 🚀 Quick Setup

llama.cpp integration is **optional** during `setup.sh`. If you want to add it later:

```bash
# Re-run setup with llama.cpp option
./setup.sh  # Will detect existing install and offer llama.cpp setup
```

The setup automatically:
- ✅ Clones and builds llama.cpp with optimal settings
- ✅ Downloads a default model (`gemma-3-270m-it-Q4_0.gguf`, ~150MB)  
- ✅ Installs Python bindings (`llama-cpp-python`) for direct mode
- ✅ Configures VOXT to use llama.cpp providers

### 📁 Model Management

#### **Model Storage**
```
~/.local/share/voxt/llamacpp_models/
```

#### **Adding New Models**

**Step 1:** Download a `.gguf` model from [Hugging Face](https://huggingface.co/models?search=gguf)
```bash
# Example: Download to model directory
cd ~/.local/share/voxt/llamacpp_models/
wget https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct-q4.gguf
```

**Step 2:** Register the model in your config
```bash
# Edit ~/.config/voxt/config.yaml
llamacpp_models:
  gemma-3-270m: "gemma-3-270m-it-Q4_0.gguf"
  phi-3-mini: "Phi-3-mini-4k-instruct-q4.gguf"  # ← Add this line
```

**Step 3:** Select in VOXT GUI  
*AI Post-Processing → Provider: `llamacpp_server` → Model: `phi-3-mini`*

#### **Recommended Models for AIPP**

| Model | Size | RAM | Quality | Best For |
|-------|------|-----|---------|----------|
| **gemma-3-270m** | 150MB | 1GB | Basic | Default, very fast |
| **llama-3.2-1b** | 600MB | 2GB | Good | Balanced speed/quality |
| **phi-3-mini** | 2.3GB | 4GB | Great | High quality text |
| **qwen2.5-coder-1.5b** | 900MB | 2GB | Good | Code-focused tasks |

💡 **Tip:** Always choose **instruct/chat** variants (not base models) for AIPP tasks.

#### **Model Format Requirements**
- ✅ **GGUF format only** (`.gguf` extension)
- ✅ **Quantized models preferred** (Q4_0, Q4_1, Q5_0, etc.)
- ❌ **Not supported:** PyTorch (`.pth`), Safetensors (`.safetensors`), ONNX

### 🔧 Advanced Configuration

Edit `~/.config/voxt/config.yaml`:

```yaml
# llama.cpp settings
llamacpp_server_path: "llama.cpp/build/bin/llama-server"
llamacpp_server_url: "http://localhost:8080"
llamacpp_server_timeout: 30

# Available models
llamacpp_models:
  gemma-3-270m: "gemma-3-270m-it-Q4_0.gguf"
  your-model: "your-model-file.gguf"

# Selected models per provider
aipp_selected_models:
  llamacpp_server: "gemma-3-270m"
  llamacpp_direct: "gemma-3-270m"
```

### 🚀 Performance Tips

- **Server mode** handles concurrent requests better
- **Direct mode** has lower latency for single requests
- **GPU acceleration** automatically detected during build (CUDA/Metal)
- **Smaller models** (270M-1B) are often sufficient for text cleanup tasks

---

### 🔑 Setting API Keys for the remote API providers

For security, VOXT does **not** store API keys in config files.  
To use cloud AIPP providers, set the required API key(s) in your shell environment before running VOXT:

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
| *Press hotkey, nothing happens*    | Troubleshoot with this command: `gnome-terminal -- bash -c "voxt --trigger-record; read -p 'Press Enter...'"` |
| *Transcript printed but not typed* | Wayland: `ydotool` not installed or user not in `input` group → run `setup_ydotool.sh`, relog.                 |
| *"whisper-cli not found"*          | Build failed - rerun `./setup.sh` and check any diagnostic output.                                                      |
| *Mic not recording*                | Verify in system settings: **input device available**? / **active**? / **not muted**?                                        |
| Clipboard empty                    | ensure `xclip` or `wl-copy`  present (re-run `setup.sh`).                                |

---

## 📜 License & Credits

* VOXT – © 2025 Jakov Ivkovic – **MIT** license (see [`LICENSE`](LICENSE)).
* Speech engine powered by [**ggml-org/whisper.cpp**](https://github.com/ggml-org/whisper.cpp) (MIT) and OpenAI Whisper models (MIT).
* Auto-typing/pasting powered by [**ReimuNotMoe/ydotool**](https://github.com/ReimuNotMoe/ydotool) (AGPLv3).

---

## 🗑️  Removal / Uninstall

### 1. Repo-clone install (`./setup.sh`)
If you cloned this repository and ran `./setup.sh` inside it:

```bash
# From inside the repo folder
# (1) leave the venv if it is currently active
deactivate 2>/dev/null || true

# (2) delete everything that the helper script created in-place
rm -rf .venv              # Python virtual-env
rm -rf whisper.cpp        # whisper.cpp sources + binaries
rm -rf llama.cpp          # llama.cpp sources + binaries (if installed)
rm -f  ~/.local/bin/whisper-cli   # symlink created by setup.sh
rm -f  ~/.local/bin/llama-server  # llama.cpp server symlink
rm -f  ~/.local/bin/llama-cli     # llama.cpp CLI symlink

# (3) finally remove the repo folder itself
cd .. && rm -rf voxt
```

### 2. pipx install
If voxt was installed through **pipx** (either directly or via the prompt at the end of `setup.sh`):

```bash
pipx uninstall voxt
```

### 3. Optional runtime clean-up
These steps remove user-level state that VOXT (or its Wayland helper) may have created. They are **safe to skip** – do them only if you want a fully pristine system.

```bash
# Stop any live processes
pkill -f voxt         || true
pkill -f ydotoold     || true
pkill -f llama-server || true  # Stop llama.cpp server if running

# Systemd user service (only if you previously ran setup_ydotool.sh)
systemctl --user stop    ydotoold.service   2>/dev/null || true
systemctl --user disable ydotoold.service   2>/dev/null || true
rm -f ~/.config/systemd/user/ydotoold.service

# XDG config & cache
rm -rf ~/.config/voxt      # settings file, absolute paths, etc.
rm -rf ~/.local/share/voxt # models, logs, and all user data
                               # (includes llamacpp_models/ directory)

# Desktop launcher
rm -f ~/.local/share/applications/voxt.desktop
rm -f ~/.local/share/applications/voxt-*.desktop

# Udev rule (Wayland only ‑ created for ydotool)
sudo rm -f /etc/udev/rules.d/99-uinput.rules 2>/dev/null || true

# Optionally remove yourself from the 'input' group again
# (Only necessary if you added it just for ydotool)
sudo gpasswd -d "$USER" input 2>/dev/null || true
```

### 4. System packages
`setup.sh` installs broadly useful distro packages (ffmpeg, gcc, cmake, portaudio, …). Most users keep them. If you **really** want to roll back, remove them with your package manager, e.g.

```bash
# Debian / Ubuntu example
sudo apt remove ffmpeg portaudio19-dev cmake
```

That's it – VOXT is now completely removed from your system.

---

Enjoy seamless voice-typing on Linux - and if you build something cool on top, open a PR or say hi!
