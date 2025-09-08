import sys


def test_main_routes_cli(monkeypatch):
    import voxt.cli.cli_main as cli_mod
    called = {"cli": False}
    monkeypatch.setattr(cli_mod, "main", lambda: called.__setitem__("cli", True))
    monkeypatch.setattr(sys, "argv", ["voxt", "--cli"])  # ensure mode

    import importlib
    import voxt.__main__ as main_mod
    importlib.reload(main_mod)  # ensure fresh parse
    main_mod.main()
    assert called["cli"] is True


