# VOXD - Voice-Type on Linux 🗣️⌨️

Running in background, provides fast **voice-to-text typing** in any Linux app, using **LOCAL** voice processing, with optional **LOCAL** AI text post-processing.  
Hit a **global shortcut**, speak, and watch your words appear wherever the cursor lives.  
  
**Tested & Works on:**
- Ubuntu 24.04
- Ubuntu Sway Remix 25.04
- Fedora 42
- openSUSE, Leap 15.6
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

  


## Setup

Complete the 2 steps:
### 1. Install VOXD

#### Preferred: Install from Release (recommended)
Download the package for your distro and architecture from the latest release, then install with your package manager.

Latest builds: [GitHub Releases (Latest)](https://github.com/jakovius/voxd/releases/latest)

- **Ubuntu/Debian (.deb)**
```bash
# After downloading voxd_...amd64.deb (or arm64.deb)
sudo apt update
sudo apt install -y ./voxd_*_amd64.deb
```

- **Fedora (.rpm)**
```bash
sudo dnf install -y ./voxd-*-x86_64.rpm
```

- **openSUSE (.rpm)**
```bash
sudo zypper install --force-resolution ./voxd-*-x86_64.rpm
```

- **Arch (.pkg.tar.zst)**
```bash
sudo pacman -U ./voxd-*-x86_64.pkg.tar.zst
```

Alternatively, you can use the cross-distro helper after downloading a package file into the current directory:
```bash
curl -fsSL https://raw.githubusercontent.com/jakovius/voxd/main/packaging/install_voxd.sh -o install_voxd.sh
bash install_voxd.sh
```

#### Alternative: Clone the repo & run the setup (for hacking):  

Copy this code, paste into terminal (Ctrl+Shift+V), and execute:
```bash
git clone https://github.com/jakovius/voxd.git

cd voxd && ./setup.sh

# requires sudo for packages & REBOOT (ydotool setup on Wayland systems). Launchers (GUI, Tray, Flux) are installed automatically.
```

Setup is non-interactive with minimal console output; a detailed setup log is saved in the repo directory (e.g. `2025-09-18-setup-log.txt`).

**Reboot** the system!  
(required to complete **ydotool** setup).  

### 2. **Setup a global hotkey** shortcut  in your system, for recording/stop:  
a. Open your system keyboard-shortcuts panel:  
  - *GNOME:* Settings → Keyboard → "Custom Shortcuts"  
  - *KDE / XFCE / Cinnamon:* similar path.  
  - *Hyprland / Sway:* just add a keybinding in the respective config file.  

b. **The command** to assign to the shortcut hotkey (EXACTLY as given):  

`bash -c 'voxd --trigger-record'`  

c. Click **Add / Save**.  

### <span style="color: #FFD600;">READY! → Go type anywhere with your voice!</span>  
Well, first run the app (see below) with a global `voxd` command.  
*(If you have been hacking a little too much, and need fixing, re-run `setup.sh`)*


---

## Usage

### Launch VOXD via Terminal, in any mode:
```bash
voxd        # CLI (interactive); 'h' shows commands inside CLI
voxd --rh   # directly starts hotkey-controlled continuous recording in CLI
voxd -h     # show top-level help and quick-actions
voxd --gui  # friendly pill-button window
voxd --tray # sits in the tray; perfect for continuous dictation
voxd --flux # VAD (Voice Activity Detection), voice-triggered continuous dictation
```

Now leave it running in the background, then go to any app where you want to voice-type and:

If in --flux, **just speak**.  

Otherwise:

| Press hotkey …   | VOXD does …                                                |
| ---------------- | ----------------------------------------------------------- |
| **First press**  | start recording                                             |
| **Second press** | stop ⇢ [transcribe ⇢ copy to clipboard] ⇢ types the output into any focused app |



### ... or from your app launcher:
Desktop launchers are installed automatically. Open your application menu and launch:

- VOXD (gui)
- VOXD (tray)
- VOXD (flux)


### 🎙️  Managing speech models

VOXD needs a Whisper GGML model file.  
Use the built-in model-manager to fetch the default (≈142 MB):

```bash
voxd-model install base.en     # or tiny.en / small / medium … see list below
```
That downloads into ~/.local/share/voxd/models/ and VOXD will
automatically pick it up.

Common commands:
```bash
voxd-model list	# show models already on disk
voxd-model install tiny.en  #	download another model ("fetch" can be also used as alias for "install")
voxd-model --no-check install base.en # download a model and skip SHA-1 verification
voxd-model remove tiny.en	# delete a model
voxd-model use tiny.en	# make that model the default (edits config.yaml)
```

Some of the available keys (size MB):

tiny.en 75 · tiny 142 · base.en 142 · base 142 ·
small.en 466 · small 466 · medium.en 1500 · medium 1500 · large-v3 2900

---

## ⚙️ User Config

Available in GUI and TRAY modes ("Settings"), but directly here:
`~/.config/voxd/config.yaml`
Unknown keys are ignored.

---

## 🧠 AI Post-Processing (AIPP)
Your spoken words can be magically cleaned and rendered into e.g. neatly formated email, or straight away into a programing code!  

VOXD can optionally post-process your transcripts using LOCAL (on-machine, **llama.cpp**, **Ollama**) or cloud LLMs (like **OpenAI, Anthropic, or xAI**).  
For the local AIPP, **llama.cpp** will be available out-of-the-box. You can also **[install Ollama](https://ollama.ai)** and download a model that can be run on your machine, e.g. `ollama pull gemma3:latest`.   
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

| Symptom                            | Likely cause / fix                                                                                             |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| *Getting randomly [BLANK_AUDIO], no transcript, or very poor transcript*    | Most likely: too high mic volume (clipping & distortions) VOXD will try to set your microphone optimally (configurable), but anyway check if input volume is not > 45%.
| *Press hotkey, nothing happens*    | Troubleshoot with this command: `gnome-terminal -- bash -c "voxd --trigger-record; read -p 'Press Enter...'"` |
| *Transcript printed but not typed* | Wayland: `ydotool` not installed or user not in `input` group → run `setup_ydotool.sh`, relog.                 |
| *"whisper-cli not found"*          | Build failed - rerun `./setup.sh` and check any diagnostic output.                                                      |
| *Mic not recording*                | Verify in system settings: **input device available**? / **active**? / **not muted**?                                        |
| Clipboard empty                    | ensure `xclip` or `wl-copy`  present (re-run `setup.sh`).                                |

---

## 📜 License & Credits

* VOXD – © 2025 Jakov Ivkovic – **MIT** license (see [`LICENSE`](LICENSE)).
* Speech engine powered by [**ggml-org/whisper.cpp**](https://github.com/ggml-org/whisper.cpp) (MIT) and OpenAI Whisper models (MIT).
* Auto-typing/pasting powered by [**ReimuNotMoe/ydotool**](https://github.com/ReimuNotMoe/ydotool) (AGPLv3).
* Transcript post-processing powered by [**ggml-org/llama.cpp**](https://github.com/ggml-org/llama.cpp) (MIT)

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
cd .. && rm -rf voxd
```

### 2. Package install (deb/rpm/arch)
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

### 3. pipx install
If voxd was installed through **pipx** (either directly or via the prompt at the end of `setup.sh`):

```bash
pipx uninstall voxd
```

### 4. Optional runtime clean-up
These steps remove user-level state that VOXD (or its Wayland helper) may have created. They are **safe to skip** – do them only if you want a fully pristine system. Pick the subsection that matches how you installed VOXD.

#### Package install – user-scoped leftovers (after removing the package)
```bash
# Stop any live processes
pkill -f voxd         || true
pkill -f ydotoold     || true
pkill -f llama-server || true

# Disable the user service (packaged unit lives under /usr/lib/systemd/user)
systemctl --user disable --now ydotoold.service 2>/dev/null || true
rm -f ~/.config/systemd/user/default.target.wants/ydotoold.service 2>/dev/null || true
systemctl --user daemon-reload 2>/dev/null || true

# Remove VOXD-managed prebuilts and symlinks for ydotool/ydotoold
rm -f ~/.local/bin/ydotool ~/.local/bin/ydotoold
rm -rf ~/.local/share/voxd/bin
rm -f ~/.ydotool_socket

# Remove VOXD user config & data (models, logs, settings)
rm -rf ~/.config/voxd
rm -rf ~/.local/share/voxd

# Note: The package removal already deletes the udev rule at /etc/udev/rules.d/99-uinput.rules
# Optional: revert uinput autoload that the package enabled (only if you don't need ydotool elsewhere)
sudo rm -f /etc/modules-load.d/uinput.conf 2>/dev/null || true
sudo modprobe -r uinput 2>/dev/null || true

# Optionally remove yourself from the 'input' group (log out/in to take effect)
sudo gpasswd -d "$USER" input 2>/dev/null || true
```

#### Repo-clone install – user-scoped leftovers
```bash
# Stop any live processes
pkill -f voxd         || true
pkill -f ydotoold     || true
pkill -f llama-server || true  # Stop llama.cpp server if running

# Systemd user service (only if you previously ran setup_ydotool.sh)
systemctl --user stop    ydotoold.service   2>/dev/null || true
systemctl --user disable ydotoold.service   2>/dev/null || true
rm -f ~/.config/systemd/user/ydotoold.service

# XDG config & cache
rm -rf ~/.config/voxd      # settings file, absolute paths, etc.
rm -rf ~/.local/share/voxd # models, logs, and all user data
                               # (includes llamacpp_models/ directory)

# Desktop launcher
rm -f ~/.local/share/applications/voxd.desktop
rm -f ~/.local/share/applications/voxd-*.desktop

# Udev rule (Wayland only ‑ created for ydotool)
sudo rm -f /etc/udev/rules.d/99-uinput.rules 2>/dev/null || true

# Optionally remove yourself from the 'input' group again
# (Only necessary if you added it just for ydotool)
sudo gpasswd -d "$USER" input 2>/dev/null || true
```

### 5. System packages
`setup.sh` installs broadly useful distro packages (ffmpeg, gcc, cmake, portaudio, …). Most users keep them. If you **really** want to roll back, remove them with your package manager, e.g.

```bash
# Debian / Ubuntu example
sudo apt remove ffmpeg portaudio19-dev cmake
```

That's it – VOXD is now completely removed from your system.

---

Enjoy seamless voice-typing on Linux - and if you build something cool on top, open a PR or say hi!
