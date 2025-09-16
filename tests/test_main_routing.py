import sys


def test_main_routes_cli(monkeypatch):
    import voxd.cli.cli_main as cli_mod
    called = {"cli": False}
    monkeypatch.setattr(cli_mod, "main", lambda: called.__setitem__("cli", True))
    monkeypatch.setattr(sys, "argv", ["voxd", "--cli"])  # ensure mode

    import importlib
    import voxd.__main__ as main_mod
    importlib.reload(main_mod)  # ensure fresh parse
    main_mod.main()
    assert called["cli"] is True


