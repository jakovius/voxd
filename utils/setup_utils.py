import os
import shutil
import subprocess
import sys
from pathlib import Path
import yaml
from core.config import AppConfig
import tempfile
import platform

TOOL_PACKAGE_MAP = {
    "ffmpeg": "ffmpeg",
    "gcc": "gcc",
    "make": "make",
    "xdg-open": "xdg-open",
    "git": "git",
    "cmake": "cmake",
    "build-essential": "build-essential",
    "wl-clipboard": "wl-clipboard",
}

CONFIG_PATH = Path("config.yaml")
MODELS_DIR = Path("whisper.cpp/models")
DEFAULT_MODEL = "ggml-base.en.bin"

def check_virtualenv():
    if "VIRTUAL_ENV" not in os.environ:
        print("⚠️  You are not running inside the virtual environment (.venv).")
        print("    This may lead to missing modules or misconfigured setup.")
        print("    Run this first and try again:")
        print("        source .venv/bin/activate")
        print()
        if platform.system() == "Linux":
            response = input("❓ Continue anyway? [y/N]: ").lower()
            if response not in ("y", "yes"):
                sys.exit(1)

def print_section(title):
    print("\n" + "=" * 40)
    print(f"{title}")
    print("=" * 40)

def is_tool_installed(tool):
    return shutil.which(tool) is not None

def preemptive_sudo_check():
    # Only prompt if we might need to install system packages
    required = ["ffmpeg", "gcc", "make", "xdg-open", "git", "cmake", "build-essential", "wl-clipboard"]
    missing = [tool for tool in required if shutil.which(tool) is None]
    if missing:
        print("🔒 Some dependencies may require sudo to install system packages.")
        try:
            subprocess.run(["sudo", "-v"], check=True)
        except subprocess.CalledProcessError:
            print("❌ Sudo authentication failed. Exiting.")
            sys.exit(1)

def prompt_auto_install():
    try:
        reply = input("\n❓ Would you like to attempt auto-install of missing tools? [Y/n] ").strip().lower()
        return reply in ("", "y", "yes")
    except KeyboardInterrupt:
        return False

def apt_install_package(pkg, friendly_name=None):
    """
    Try to install a package via apt, handling apt update errors gracefully.
    Returns True if installed, False otherwise.
    """
    friendly_name = friendly_name or pkg
    try:
        subprocess.run(["sudo", "apt", "update"], check=True)
    except subprocess.CalledProcessError:
        print(f"⚠️  apt update failed. You may have a broken or unreachable repository in your sources.")
        print("   You can try to fix this by removing or disabling problematic PPAs.")
        proceed = input(f"❓ Attempt to install {friendly_name} anyway? [y/N] ").strip().lower()
        if proceed not in ("y", "yes"):
            print(f"❌ Aborting install of {friendly_name}.")
            return False
    try:
        subprocess.run(["sudo", "apt", "install", "-y", pkg], check=True)
        print(f"✅ {friendly_name} installed.")
        return True
    except subprocess.CalledProcessError:
        print(f"❌ Failed to install {friendly_name}. Please install it manually.")
        return False

def ensure_tool(tool, apt_pkg=None, friendly_name=None):
    """
    Ensure a tool is installed, prompt to install via apt if missing.
    Returns True if installed or user declined, False if aborted.
    """
    if is_tool_installed(tool):
        return True
    friendly_name = friendly_name or tool
    print(f"⚠️  {friendly_name} is required.")
    try:
        reply = input(f"❓ Install {friendly_name} via apt? [Y/n] ").strip().lower()
    except KeyboardInterrupt:
        print("❌ Aborted.")
        return False
    if reply in ("", "y", "yes"):
        return apt_install_package(apt_pkg or tool, friendly_name)
    else:
        print(f"❌ Cannot proceed without {friendly_name}. Aborting.")
        return False

def try_install(tool):
    pkg = TOOL_PACKAGE_MAP.get(tool, tool)
    try:
        print(f"==> Installing {pkg}...")
        subprocess.run(["sudo", "apt", "install", "-y", pkg], check=True)
        print(f"✅ Installed: {pkg}")
    except subprocess.CalledProcessError:
        print(f"❌ Failed to install {pkg}. Please try manually: sudo apt install {pkg}")

def ensure_model_downloaded():
    model_path = MODELS_DIR / DEFAULT_MODEL
    if model_path.exists():
        print(f"✅ Whisper model found: {model_path}")
        return True

    print("==> Ensuring default Whisper model is downloaded...")
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    url = f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{DEFAULT_MODEL}"
    try:
        subprocess.run(["curl", "-L", "-o", str(model_path), url], check=True)
        print(f"✅ Model downloaded: {model_path}")
        return True
    except subprocess.CalledProcessError:
        print("❌ Failed to download model automatically.")
        print(f"Please download manually from:\n  {url}\nand place it in {MODELS_DIR}")
        return False

def detect_whisper_binary():
    candidates = list(Path("whisper.cpp").rglob("whisper-cli"))
    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            print(f"✅ Found whisper binary: {path}")
            cfg = AppConfig()
            cfg.set("whisper_binary", str(path))
            cfg.save()
            return True
    print("❌ whisper binary not found. Expected to find an executable named 'main' under whisper.cpp/build/...")
    return False

def check_dependencies():
    print_section("Checking system dependencies...")
    required = ["ffmpeg", "gcc", "make", "xdg-open", "git", "cmake", "build-essential", "wl-clipboard"]
    missing = []
    for tool in required:
        if is_tool_installed(tool):
            print(f"✅ {tool}: {shutil.which(tool)}")
        else:
            print(f"❌ {tool} is missing.")
            missing.append(tool)

    if missing:
        if prompt_auto_install():
            for tool in missing:
                try_install(tool)
        else:
            print("\nPlease install the following tools manually:")
            for tool in missing:
                print(f"  sudo apt install {tool}")

def check_audio():
    print_section("Audio device check...")
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        input_devs = [d for d in devices if isinstance(d, dict) and d.get("max_input_channels", 0) > 0]
        
        if not input_devs:
            print("❌ No input devices found.")
            print("   Tips:")
            print("   • Make sure a mic is connected and unmuted")
            print("   • Ensure PulseAudio or PipeWire is running")
            print("   • Check that your user is in the 'audio' group")
        else:
            print(f"✅ {len(input_devs)} input device(s) found:")
            for dev in input_devs:
                print(f"   - {dev['name']} ({dev['max_input_channels']} channels)")
    except Exception as e:
        print("❌ Could not query sound devices:", e)
        print("   You may need to install: libportaudio2 alsa-utils")

def check_whisper_config():
    print_section("Verifying whisper binary + model setup...")
    detect_whisper_binary()
    ensure_model_downloaded()

def run_all():
    preemptive_sudo_check()
    check_virtualenv()
    check_dependencies()
    check_audio()
    check_whisper_config()
    print("\n✅ Setup check complete.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Run setup checks")
    args = parser.parse_args()

    if args.check:
        run_all()