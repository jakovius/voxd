# VOXD - Voice-Type / dictation app for Linux 🗣️⌨️

Running in background, provides fast **voice-to-text typing** in any Linux app.  
Using **LOCAL** voice processing, with optional **LOCAL** AI text post-processing.  
Runs fine even on older CPUs. No GPU required.

Hit your **hotkey shortcut** -> speak -> hotkey again -> watch your words appear wherever the cursor currently is, even AI-rewritten as a poem or a C++ code.  
  
**Tested & Works on:**
- Ubuntu 24.04 / GNOME
- Ubuntu 25.04 / Sway
- Fedora 42 / KDE
- Arch / Hyprland
- Pop!_OS 22
- Mint 22 / Cinnamon
- openSUSE, Leap 15.6


## Highlights

| Feature                          | Notes                                                                   |
| -------------------------------- | ----------------------------------------------------------------------- |
| **Whisper.cpp** backend          | Local, offline, fast  ASR.   |
| **Simulated typing**             | instantly types straight into any currently focused input window. Even on Wayland! (*ydotool*).  |
| **Clipboard**                    | Auto-copies into clipboard - ready for pasting, if desired        |
| **AIPP**, AI Post-Processing	   | AI-rewriting via local or cloud LLMs. GUI prompt editor.         |  
| **Multiple UI** surfaces         | CLI, GUI (minimal PyQt6), TRAY (system tray), FLUX (triggered by voice activity detection, beta) |
| **Logging** & **performance**    | Session log plus your own optional local performance data (CSV).                          |
 

## Setup

Complete the 2 steps: **Install VOXD** & **setup a hotkey**.  

### 1. Install VOXD

#### Preferred: Install from Release (recommended)
Download the package for your distro and architecture from the latest release, then install with your package manager.

Latest builds: [GitHub Releases (Latest)](https://github.com/jakovius/voxd/releases/latest)  

#### **Ubuntu / Debian (.deb)**

```bash
# Update package lists and install the downloaded .deb package:
sudo apt update
sudo apt install -y ./voxd_*_amd64.deb    # or ./voxd_*_arm64.deb on ARM systems
```

---

#### **Fedora (.rpm)**

```bash
# Update repositories and install the downloaded .rpm package:
sudo dnf update -y
sudo dnf install -y ./voxd-*-x86_64.rpm  # or the arm64 counterpart if on an ARM device
```

---

#### **Arch Linux (.pkg.tar.zst)**

```bash
# Synchronize package databases and install the downloaded .pkg.tar.zst package:
sudo pacman -Sy
sudo pacman -U ./voxd-*-x86_64.pkg.tar.zst    # or the arm64 counterpart if on an ARM device
```

---

#### **openSUSE (.rpm)**

```bash
# Refresh repositories and install the downloaded .rpm package with dependency resolution:
sudo zypper refresh
sudo zypper install --force-resolution ./voxd-*-x86_64.rpm   # or the arm64 counterpart if on an ARM device
```

#### Alternatively: Download the source or clone the repo, and run the setup (for hacking):  

```bash
git clone https://github.com/jakovius/voxd.git

cd voxd && ./setup.sh

# requires sudo for packages & REBOOT (ydotool setup on Wayland systems). Launchers (GUI, Tray, Flux) are installed automatically.
```

Setup is non-interactive with minimal console output; a detailed setup log is saved in the repo directory (e.g. `2025-09-18-setup-log.txt`).

**Reboot** the system!  
(unless on an X11 system; on most modern systems there is Wayland, so **ydotool** is required for typing and needs rebooting for user setup).  

### 2. **Setup a global hotkey** shortcut  in your system, for recording/stop:  
a. Open your system keyboard-shortcuts panel:  
  - *GNOME:* Settings → Keyboard → "Custom Shortcuts"  
  - *KDE / XFCE / Cinnamon:* similar path.  
  - *Hyprland / Sway:* just add a keybinding in the respective config file.  

b. **The command** to assign to the shortcut hotkey (EXACTLY as given):  

`bash -c 'voxd --trigger-record'`  

c. Click **Add / Save**.  

First, run the app in terminal (see below) with a global `voxd` command.  
The first run will do some initial setup (voice model, LLM model for AIPP, ydotool user setup).  

### <span style="color: #FFD600;">READY! → Go type anywhere with your voice!</span>  


---

## Usage

### Use the installed VOXD launchers (your app launcher) or launch via Terminal, in any mode:
```bash
voxd        # CLI (interactive); 'h' shows commands inside CLI. FIRST RUN: a necessary initial setup.
voxd --rh   # directly starts hotkey-controlled continuous recording in Terminal
voxd -h     # show top-level help and quick-actions
voxd --gui  # friendly GUI window--just leave it in the background to voice-type via your hotkey
voxd --tray # sits in the tray; perfect for unobstructed dictation (hotkey-driven also)
voxd --flux # VAD (Voice Activity Detection), voice-triggered continuous dictation (in beta)
```

Leave VOXD running in the background -> go to any app where you want to voice-type and:  

| Press hotkey …   | VOXD does …                                                |
| ---------------- | ----------------------------------------------------------- |
| **First press**  | start recording                                             |
| **Second press** | stop ⇢ [transcribe ⇢ copy to clipboard] ⇢ types the output into any focused app |  

Otherwise, if in --flux, **just speak**.

### 🎙️  Managing speech models

VOXD needs a Whisper GGML model file. There is one default model readily setup in the app (base.en).  
Use the built-in model-manager in GUI mode or via CLI mode in Terminal to fetch any other model.  
The voice models are downloaded into ~/.local/share/voxd/models/ and VOXD app will
automatically have them visible.

CLI model management examples:
```bash
voxd-model list	# show models already on disk
voxd-model install tiny.en  #	download another model
voxd-model --no-check install base.en # download a model and skip SHA-1 verification
voxd-model remove tiny.en	# delete a model
voxd-model use tiny.en	# make that model the default (edits config.yaml)
```

Some of the models for download (size MB):

tiny.en 75 · tiny 142 · base.en 142 · base 142 ·
small.en 466 · small 466 · medium.en 1500 · medium 1500 · large-v3 2900

---

## ⚙️ User Config

Available in GUI and TRAY modes ("Settings"), but directly here:
`~/.config/voxd/config.yaml`

---

## 🧠 AI Post-Processing (AIPP)
Your spoken words can be magically cleaned and rendered into e.g. neatly formated email, a poem, or straight away into a programing code!  

VOXD can optionally post-process your transcripts using LOCAL (on-machine, **llama.cpp**, **Ollama**) or cloud LLMs (like **OpenAI, Anthropic, or xAI**).  
For the local AIPP, **llama.cpp** is available out-of-the-box, with a default model.  
You can also **[install Ollama](https://ollama.ai)** and download a model that can be run on your machine, e.g. `ollama pull gemma3:latest`.   
You can enable, configure, and manage prompts directly from the GUI.

### Enable AIPP:
In CLI mode, use `--aipp` argument.  
In GUI or TRAY mode, all relevant settings are in: "*AI Post-Processing*".  
**Seleting provider & model** - models are tied to their respective providers!  
**Editing Prompts** - Select "*Manage prompts*" or "*Prompts*" to edit up to 4 of them.

## Supported providers:

- **llama.cpp** (local)
- **Ollama** (local)  
- **OpenAI**  
- **Anthropic**  
- **xAI**  

---

### AIPP Model Management

#### **Model Storage**
```
~/.local/share/voxd/llamacpp_models/
```

#### **Adding Models | Requirements**


- **GGUF** format **only** (`.gguf` extension)
- **Quantized models recommended** (Q4_0, Q4_1, Q5_0, etc.)
- ❌ **Not supported:** PyTorch (`.pth`), Safetensors (`.safetensors`), ONNX

**Step 1:** Download a `.gguf` model from [Hugging Face](https://huggingface.co/models?search=gguf)
```bash
# Example: Download to model directory
cd ~/.local/share/voxd/llamacpp_models/
wget https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf?download=true
```

**Step 2:** Restart VOXD  
VOXD automatically discovers all `.gguf` files in the models directory on startup and makes them available for selection.

**Step 3:** Select in VOXD GUI  
*AI Post-Processing → Provider: `llamacpp_server` → Model: `qwen2.5-3b-instruct`*

#### **Recommended Models for AIPP**

| Model | Size | RAM | Quality | Best For |
|-------|------|-----|---------|----------|
| **qwen2.5-3b-instruct** | 1.9GB | 3GB | Great | Default, high quality |
| **qwen2.5-coder-1.5b** | 900MB | 2GB | Good | Code-focused tasks |


### 🔧 Advanced Configuration

Edit `~/.config/voxd/config.yaml`:

```yaml
# llama.cpp settings
llamacpp_server_path: "llama.cpp/build/bin/llama-server"
llamacpp_server_url: "http://localhost:8080"
llamacpp_server_timeout: 30

# Selected models per provider (automatically updated by VOXD)
aipp_selected_models:
  llamacpp_server: "qwen2.5-3b-instruct-q4_k_m"
```

---

### 🔑 Setting API Keys for the remote API providers

For security reasons, be mindful where you store your API keys.  
To use cloud AI providers, set the required API key(s) in your shell environment before running VOXD.  
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
If an API key is missing, the respective cloud-based AIPP provider will (surprise, surprise) not work.

---

## 🩺 Troubleshooting cheatsheet

Note: As one may expect, the app is not completely immune to very noisy environments :) especially if you are not the best speaker out there.  

| Symptom                            | Likely cause / fix                                                                                             |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| *Getting randomly [BLANK_AUDIO], no transcript, or very poor transcript*    | Most likely: too high mic volume (clipping & distortions) VOXD will try to set your microphone optimally (configurable), but anyway check if input volume is not > 45%.
| *Press hotkey, nothing happens*    | Troubleshoot with this command: `gnome-terminal -- bash -c "voxd --trigger-record; read -p 'Press Enter...'"` |
| *Transcript printed but not typed* | Wayland: `ydotool` not installed or user not in `input` group → run `setup_ydotool.sh`, relog.                 |
| *"whisper-cli not found"*          | Build failed - rerun `./setup.sh` and check any diagnostic output.                                                      |
| *Mic not recording*                | Verify in system settings: **input device available**? / **active**? / **not muted**?                                        |
| Clipboard empty                    | ensure `xclip` or `wl-copy`  present (re-run `setup.sh`).                                |

### Audio troubleshooting

- List devices: `python -m sounddevice` (check that a device named "pulse" exists on modern systems).
- Prefer PulseAudio/PipeWire: set in `~/.config/voxd/config.yaml`:

```yaml
audio_prefer_pulse: true
audio_input_device: "pulse"   # or a specific device name or index
```

- If no `pulse` device:
  - Debian/Ubuntu: `sudo apt install alsa-plugins pavucontrol` (ensure `pulseaudio` or `pipewire-pulse` is active)
  - Fedora/openSUSE: `sudo dnf install alsa-plugins-pulseaudio pavucontrol` (ensure `pipewire-pulseaudio` is active)
  - Arch: `sudo pacman -S alsa-plugins pipewire-pulse pavucontrol`

- If 16 kHz fails on ALSA: VOXD will retry with the device default rate and with `pulse` when available.

---

## 📜 License & Credits

* VOXD – © 2025 Jakov Ivkovic – **MIT** license (see [`LICENSE`](LICENSE)).
* Speech engine powered by [**ggml-org/whisper.cpp**](https://github.com/ggml-org/whisper.cpp) (MIT) and OpenAI Whisper models (MIT).
* Auto-typing/pasting powered by [**ReimuNotMoe/ydotool**](https://github.com/ReimuNotMoe/ydotool) (AGPLv3).
* Transcript post-processing powered by [**ggml-org/llama.cpp**](https://github.com/ggml-org/llama.cpp) (MIT)

---

## 🗑️  Removal / Uninstall


### 1. Package install (deb/rpm/arch)
If VOXD was installed via a native package:

- **Ubuntu/Debian**
```bash
sudo apt remove voxd
```

- **Fedora**
```bash
sudo dnf remove -y voxd
```

- **openSUSE**
```bash
sudo zypper --non-interactive remove voxd
```

- **Arch**
```bash
sudo pacman -R voxd
```

Note: This removes system files (e.g., under `/opt/voxd` and `/usr/bin/voxd`). User-level data (models, config, logs) remain. See "Optional runtime clean-up" below to remove those.



### 2. Repo-clone install (`./setup.sh`)
If you cloned this repository and ran `./setup.sh` inside it, just run the uninstall.sh script in the repo folder:

```bash
# From inside the repo folder
./uninstall.sh
```


### 3. pipx install
If voxd was installed through **pipx** (either directly or via the prompt at the end of `setup.sh`):

```bash
pipx uninstall voxd
```

---

Enjoy seamless voice-typing on Linux - and if you build something cool on top, open a PR or say hi!
