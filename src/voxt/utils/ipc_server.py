import socket
import threading
from pathlib import Path

def _socket_path():
    return Path.home() / ".config" / "voxt" / "voxt.sock"

def start_ipc_server(trigger_callback):
    """Starts a background thread that listens for 'trigger_record' and calls trigger_callback()."""
    sock_path = _socket_path()
    sock_path.parent.mkdir(parents=True, exist_ok=True)
    if sock_path.exists():
        sock_path.unlink()

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen()

    def _serve_loop():
        while True:
            conn, _ = server.accept()
            data = conn.recv(1024).strip()
            if data == b"trigger_record":
                trigger_callback()
            conn.close()

    t = threading.Thread(target=_serve_loop, daemon=True)
    t.start()