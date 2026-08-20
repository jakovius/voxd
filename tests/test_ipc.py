import socket
import time
from pathlib import Path

import pytest


def _wait_for(predicate, timeout=2.0):
    """Poll until predicate is true, so tests don't rely on fixed sleeps."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _sock_path(home: Path) -> Path:
    return home / ".config" / "voxd" / "voxd.sock"


def _make_stale_socket(path: Path):
    """Leave a socket file behind with nothing listening on it.

    This is what a Ctrl-C'd instance leaves on disk: connecting to it
    raises ConnectionRefusedError rather than FileNotFoundError.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    dead = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    dead.bind(str(path))
    dead.listen()
    dead.close()


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch, tmp_path):
    # ipc_server resolves the socket via Path.home(), not XDG_CONFIG_HOME.
    monkeypatch.setenv("HOME", str(tmp_path))
    yield tmp_path
    from voxd.utils.ipc_server import shutdown_ipc_server
    shutdown_ipc_server()


def test_second_instance_does_not_steal_live_socket(isolated_home):
    from voxd.utils.ipc_client import send_trigger
    from voxd.utils.ipc_server import start_ipc_server

    first = []
    second = []

    assert start_ipc_server(lambda: first.append(1)) is True
    # A second instance must not unlink the socket the first one owns.
    assert start_ipc_server(lambda: second.append(1)) is False

    assert send_trigger() is True
    assert _wait_for(lambda: first), "live owner stopped receiving triggers"
    assert second == []


def test_stale_socket_is_reclaimed(isolated_home):
    from voxd.utils.ipc_client import send_trigger
    from voxd.utils.ipc_server import start_ipc_server

    _make_stale_socket(_sock_path(isolated_home))
    received = []

    assert start_ipc_server(lambda: received.append(1)) is True

    assert send_trigger() is True
    assert _wait_for(lambda: received), "reclaimed socket did not deliver trigger"


def test_socket_file_removed_on_shutdown(isolated_home):
    from voxd.utils.ipc_server import shutdown_ipc_server, start_ipc_server

    assert start_ipc_server(lambda: None) is True
    assert _sock_path(isolated_home).exists()

    shutdown_ipc_server()

    assert not _sock_path(isolated_home).exists()


def test_send_trigger_reports_failure_when_not_running(isolated_home):
    from voxd.utils.ipc_client import send_trigger

    assert send_trigger() is False


def test_send_trigger_reports_failure_on_stale_socket(isolated_home):
    from voxd.utils.ipc_client import send_trigger

    _make_stale_socket(_sock_path(isolated_home))

    assert send_trigger() is False
