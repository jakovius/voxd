# VOXT - Voice-Type on Linux 🗣️⌨️

Running in background, provides fast **voice-to-text typing** in any Linux app, using **LOCAL** voice processing, with optional **LOCAL** AI text post-processing.  
Hit a **global shortcut**, speak, and watch your words appear wherever the cursor lives.  
  
**Tested & Works on:**
- Ubuntu 24.04
- Ubuntu Sway Remix 25.04
- Fedora 42
- Pop!_OS 22
- Mint 22
- Arch 2025 / Hyprland.  



## Highlights

| Feature                          | Notes                                                                   |
| -------------------------------- | ----------------------------------------------------------------------- |
| **Whisper.cpp** backend          | Local, offline  ASR.   |
| **Simulated typing**             | instantly types straight into any currently focused input window. Even on Wayland! (*ydotool*).                   |
| **Clipboard**                    | Auto-copies into clipboard - ready for pasting        |
| **Multiple UI** surfaces             | CLI, GUI (minimal PyQt6), TRAY (system tray), FLUX (triggered by voice activity detection) |
| **Logging** & **performance**             | Session log plus opt-in local performance data (CSV).                          |
| AI Post-Processing (**AIPP**)	     | Process transcripts via local or cloud LLMs. GUI prompt editor.         |

  


## Installation

Complete this list:
1. **Clone** the repo & **run the setup** (you will make some input):
```bash
git clone https://github.com/jacob8472/voxt.git

cd voxt && ./setup.sh

# builds voxt + deps and installs a global `voxt` command (via pipx)
```
2. **Setup a global hotkey** shortcut for recording/stop in your system:  
a. Open your system keyboard-shortcuts panel  
   *GNOME:* Settings → Keyboard → "Custom Shortcuts"  
   *KDE / XFCE / Cinnamon:* similar path.  
   *Hyprland / Sway:* open the respective config file with keybindings, and add a key binding for this purpose.  

   b. **The command to assign to the shortcut hotkey (EXACTLY as given):**  
 `bash -c 'voxt --trigger-record'`  
 c. Click **Add / Save**.  

3. make sure your **mic is ON**, and the gain/**volume is at ca. 40%** of the max  
*(Whisper and voice transcription is problematic at default sound input levels)*

**<span style="color: #FFD600;">You are set! → Go type anywhere with your voice!</span>**  
Well, first run the app (see below) with a global `voxt` command available in any shell.  
*(You are always welcome to re-run `setup.sh` if you need any part of the setup and optional stuff revisited)*


---

## Usage

### Launch VOXT via Terminal, in any mode:
```bash
voxt --gui  # friendly pill-button window
voxt --tray # sits in the tray; perfect for continuous dictation
voxt --cli  # terminal; 'h' shows commands
voxt --rh   # Go directly to --cli 'rh' and leave in the background
voxt --flux # VAD (Voice Activity Detection), voice-triggered recording, experimental
voxt        # displays detailed list of options & flags
```

Now leave it running in the background, then go to any app where you want to voice-type and:

| Press hotkey …   | VOXT does …                                                |
| ---------------- | ----------------------------------------------------------- |
| **First press**  | start recording                                             |
| **Second press** | stop ⇢ [transcribe ⇢ copy to clipboard] ⇢ types the output |



### ... or from your app launcher:  
Run this launcher setup first, and then find & run Voxt:  

```bash
./launcher_setup.sh        # pick GUI, Tray, or both
./launcher_setup.sh --edit # fix existing launchers
```


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

## ⚙️ User Config

Available in GUI and TRAY modes ("Settings"), but directly here:
`~/.config/voxt/config.yaml`
Unknown keys are ignored.

---

## 🧠 AI Post-Processing (AIPP)
Your spoken words can be magically cleaned and rendered into e.g. neatly formated email, or straight away into a programing code!  

VOXT can optionally post-process your transcripts using LOCAL (on-machine, **llama.cpp**, **Ollama**) or cloud LLMs (like **OpenAI, Anthropic, or xAI**).  
For the local AIPP, just accept llama.cpp during the setup or/and **[install Ollama](https://ollama.ai)** and download a model that can be run on your machine, e.g. `ollama pull gemma3:latest`.   
You can enable, configure, and manage prompts directly from the GUI.

### Enable AIPP:
In CLI mode, use `--aipp` argument.  
In GUI or TRAY mode, all relevant settings are in: "*AI Post-Processing*".  
**Seleting provider & model** - models are tied to their respective providers!  
**Editing Prompts** - Select "*Manage prompts*" or "*Prompts*" to edit up to 4 of them.

## Supported providers:

- **llama.cpp** (local, direct & server modes)
- **Ollama** (local)  
- **OpenAI**  
- **Anthropic**  
- **xAI**  

---

## 🦙 llama.cpp Integration (Local AI)

VOXT includes **native llama.cpp support** for ultra-fast local AI processing without requiring Ollama. This gives you two llama.cpp modes:

- **`llamacpp_server`** - Uses llama.cpp's built-in HTTP server (recommended)
- **`llamacpp_direct`** - Direct Python bindings (fastest, but requires `llama-cpp-python`)

### Quick Setup

llama.cpp integration is **optional** during `setup.sh`. If you want to add it later:

```bash
# Re-run setup with llama.cpp option
./setup.sh  # Will detect existing install and offer llama.cpp setup
```

- Clones and builds llama.cpp with optimal settings
- Downloads a default model (`qwen2.5-3b-instruct-q4_k_m.gguf`, ~1.9GB)  
- Installs Python bindings (`llama-cpp-python`) for direct mode
- Configures VOXT to use llama.cpp providers

### AIPP Model Management

#### **Model Storage**
```
~/.local/share/voxt/llamacpp_models/
```

#### **Adding Models | Requirements**


- **GGUF** format **only** (`.gguf` extension)
- **Quantized models recommended** (Q4_0, Q4_1, Q5_0, etc.)
- ❌ **Not supported:** PyTorch (`.pth`), Safetensors (`.safetensors`), ONNX

**Step 1:** Download a `.gguf` model from [Hugging Face](https://huggingface.co/models?search=gguf)
```bash
# Example: Download to model directory
cd ~/.local/share/voxt/llamacpp_models/
wget https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf?download=true
```

**Step 2:** Restart VOXT  
VOXT automatically discovers all `.gguf` files in the models directory on startup and makes them available for selection.

**Step 3:** Select in VOXT GUI  
*AI Post-Processing → Provider: `llamacpp_server` → Model: `qwen2.5-3b-instruct`*

#### **Recommended Models for AIPP**

| Model | Size | RAM | Quality | Best For |
|-------|------|-----|---------|----------|
| **qwen2.5-3b-instruct** | 1.9GB | 3GB | Great | Default, high quality |
| **qwen2.5-coder-1.5b** | 900MB | 2GB | Good | Code-focused tasks |


### 🔧 Advanced Configuration

Edit `~/.config/voxt/config.yaml`:

```yaml
# llama.cpp settings
llamacpp_server_path: "llama.cpp/build/bin/llama-server"
llamacpp_server_url: "http://localhost:8080"
llamacpp_server_timeout: 30

# Selected models per provider (automatically updated by VOXT)
aipp_selected_models:
  llamacpp_server: "qwen2.5-3b-instruct-q4_k_m"
  llamacpp_direct: "qwen2.5-3b-instruct-q4_k_m"
```

---

### 🔑 Setting API Keys for the remote API providers

For security reasons, be mindful where you store your API keys.  
To use cloud AI providers, set the required API key(s) in your shell environment before running VOXT.  
For example, add these lines to your `.bashrc`, `.zshrc`, or equivalent shell profile for convenience (change to your exact key accordingly):

```sh
# For OpenAI
export OPENAI_API_KEY="sk-..."

# For Anthropic
export ANTHROPIC_API_KEY="..."

# For xAI
export XAI_API_KEY="..."
```

**Note:**  
If an API key is missing, cloud-based AIPP providers will not work and you will see an error.

---

## 🩺 Troubleshooting cheatsheet

| Symptom                            | Likely cause / fix                                                                                             |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| *Getting randomly [BLANK_AUDIO], no transcript, or very poor transcript*    | Most likely your input features clipping & distortions at default volume levels - need to reduce your microphone input volume to ca. 40% level. |
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
