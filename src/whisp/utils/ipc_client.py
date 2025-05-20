import socket
from pathlib import Path

def _socket_path() -> Path:
    return Path.home() / ".config" / "whisp" / "whisp.sock"

def send_trigger():
    """Connect to the running app and send 'trigger_record'."""
    path = str(_socket_path())
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(path)
        sock.sendall(b"trigger_record")
    except Exception as e:
        print(f"[IPC] Could not send trigger: {e}")
    finally:
        sock.close()