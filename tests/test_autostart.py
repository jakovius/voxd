import importlib
import types


def test_parse_bool_true_false(monkeypatch, tmp_path):
    # Isolate config directory and HOME
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.setenv("HOME", str(tmp_path))

    # Import module fresh
    import voxd.__main__ as main_mod
    importlib.reload(main_mod)

    assert main_mod._parse_bool("true") is True
    assert main_mod._parse_bool("True") is True
    assert main_mod._parse_bool("1") is True
    assert main_mod._parse_bool("yes") is True
    assert main_mod._parse_bool("on") is True

    assert main_mod._parse_bool("false") is False
    assert main_mod._parse_bool("False") is False
    assert main_mod._parse_bool("0") is False
    assert main_mod._parse_bool("no") is False
    assert main_mod._parse_bool("off") is False


def test_autostart_xdg_fallback_enable_disable(monkeypatch, tmp_path):
    # Force systemd --user to appear unavailable
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.setenv("HOME", str(tmp_path))

    import voxd.__main__ as main_mod
    importlib.reload(main_mod)

    def fake_run(args, **kwargs):
        # Simulate missing systemd --user
        if args[:3] == ["systemctl", "--user", "--version"]:
            t = types.SimpleNamespace(returncode=1, stdout=b"", stderr=b"")
            return t
        return types.SimpleNamespace(returncode=1, stdout=b"", stderr=b"")

    monkeypatch.setattr(main_mod, "subprocess", types.SimpleNamespace(run=fake_run))

    rc_en = main_mod._handle_autostart("true")
    assert rc_en == 0
    xdg_path = (tmp_path / ".config" / "autostart" / "voxd-tray.desktop")
    assert xdg_path.exists()
    assert "Exec=voxd --tray" in xdg_path.read_text()

    rc_dis = main_mod._handle_autostart("false")
    assert rc_dis == 0
    assert not xdg_path.exists()


def test_autostart_systemd_enable_disable(monkeypatch, tmp_path):
    # Make a fake systemd that "enables" and tracks state
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.setenv("HOME", str(tmp_path))

    import voxd.__main__ as main_mod
    importlib.reload(main_mod)

    state = {"enabled": False, "active": False}

    def fake_run(args, **kwargs):
        cmd = args
        if cmd[:3] == ["systemctl", "--user", "--version"]:
            return types.SimpleNamespace(returncode=0, stdout=b"systemd", stderr=b"")
        if cmd[:3] == ["systemctl", "--user", "daemon-reload"]:
            return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        if cmd[:3] == ["systemctl", "--user", "enable"]:
            state["enabled"] = True
            state["active"] = True
            return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        if cmd[:3] == ["systemctl", "--user", "disable"]:
            state["enabled"] = False
            state["active"] = False
            return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        if cmd[:3] == ["systemctl", "--user", "is-enabled"]:
            return types.SimpleNamespace(returncode=0 if state["enabled"] else 1, stdout=b"", stderr=b"")
        if cmd[:3] == ["systemctl", "--user", "is-active"]:
            return types.SimpleNamespace(returncode=0 if state["active"] else 1, stdout=b"", stderr=b"")
        if cmd[:3] == ["systemctl", "--user", "start"]:
            state["active"] = True
            return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(main_mod, "subprocess", types.SimpleNamespace(run=fake_run))

    rc_en = main_mod._handle_autostart("true")
    assert rc_en == 0

    rc_dis = main_mod._handle_autostart("false")
    assert rc_dis == 0


