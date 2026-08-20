import atexit
import socket
import sys
import threading
from pathlib import Path

_server = None
_owned_path = None

def _socket_path():
    return Path.home() / ".config" / "voxd" / "voxd.sock"

def _is_live(sock_path) -> bool:
    """True when another VOXD instance is already listening on this path.

    A socket file left behind by a killed instance still exists on disk but
    refuses connections, so only ECONNREFUSED/ENOENT prove it is stale. Any
    other error is treated as live, so we never unlink a socket that might
    still belong to a running instance.
    """
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.connect(str(sock_path))
        return True
    except (ConnectionRefusedError, FileNotFoundError):
        return False
    except OSError:
        return True
    finally:
        probe.close()

def shutdown_ipc_server():
    """Close the listener and remove our socket file. Safe to call twice."""
    global _server, _owned_path
    if _server is not None:
        try:
            _server.close()
        except OSError:
            pass
        _server = None
    if _owned_path is not None:
        try:
            _owned_path.unlink()
        except FileNotFoundError:
            pass
        _owned_path = None

def start_ipc_server(trigger_callback) -> bool:
    """Listen for 'trigger_record' and call trigger_callback().

    Returns True when this instance owns the socket, False when another
    instance already does (in which case IPC is left to that instance).
    """
    global _server, _owned_path
    sock_path = _socket_path()
    sock_path.parent.mkdir(parents=True, exist_ok=True)

    if sock_path.exists():
        if _is_live(sock_path):
            print(
                "[IPC] VOXD is already running; the hotkey controls that "
                "instance. Continuing without IPC.",
                file=sys.stderr,
            )
            return False
        sock_path.unlink()

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen()
    _server = server
    _owned_path = sock_path

    def _serve_loop():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return  # listener closed during shutdown
            data = conn.recv(1024).strip()
            if data == b"trigger_record":
                trigger_callback()
            conn.close()

    t = threading.Thread(target=_serve_loop, daemon=True)
    t.start()
    atexit.register(shutdown_ipc_server)
    return True
