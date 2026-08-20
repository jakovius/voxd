import socket
import sys
from pathlib import Path

def _socket_path() -> Path:
    return Path.home() / ".config" / "voxd" / "voxd.sock"

def send_trigger() -> bool:
    """Connect to the running app and send 'trigger_record'.

    Returns True when the trigger was delivered, False otherwise. Failures
    go to stderr so a hotkey that silently does nothing can be diagnosed.
    """
    path = str(_socket_path())
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(path)
        sock.sendall(b"trigger_record")
        return True
    except FileNotFoundError:
        print(
            "[IPC] VOXD is not running - start it with 'voxd --tray'.",
            file=sys.stderr,
        )
    except ConnectionRefusedError:
        print(
            f"[IPC] Stale socket at {path} - VOXD is not running. "
            "Restart VOXD to recreate it.",
            file=sys.stderr,
        )
    except OSError as e:
        print(f"[IPC] Could not send trigger: {e}", file=sys.stderr)
    finally:
        sock.close()
    return False
