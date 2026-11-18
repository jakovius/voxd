"""Proxy for the cloud AIPP providers (config key aipp_proxy)."""
import pytest


def test_normalize_proxy():
    from voxd.core.aipp import normalize_proxy as n
    assert n("") == "" and n(None) == ""
    assert n("10.0.0.1:3128") == "http://10.0.0.1:3128"
    assert n("socks5://127.0.0.1:1080") == "socks5h://127.0.0.1:1080"      # DNS through the proxy
    assert n("socks5h://u:p@host:1080/") == "socks5h://u:p@host:1080"
    assert n("socks4://host:1080") == "socks4a://host:1080"
    for bad in ("ftp://host:21", "socks5://host", "http://", "socks5://host:abc"):
        with pytest.raises(ValueError):
            n(bad)


class _Resp:
    ok = True

    def json(self):
        return {"choices": [{"message": {"content": " done "}}]}


def _run(monkeypatch, provider, proxy, **extra):
    import voxd.core.aipp as A
    from voxd.core.config import get_config
    calls = []
    monkeypatch.setattr(A.requests, "post", lambda url, **kw: calls.append((url, kw)) or _Resp())
    monkeypatch.setattr(A, "socks_supported", lambda: True)
    cfg = get_config()
    cfg.data.update(aipp_provider=provider, aipp_proxy=proxy, **extra)
    cfg.data["aipp_selected_models"][provider] = "m"
    return A.run_aipp("text", cfg), calls


def test_cloud_request_goes_through_proxy(monkeypatch):
    out, calls = _run(monkeypatch, "openrouter", "socks5://127.0.0.1:1080")
    assert out == "done"
    assert calls[0][1]["proxies"] == {"http": "socks5h://127.0.0.1:1080", "https": "socks5h://127.0.0.1:1080"}


def test_no_proxy_configured_means_no_proxies_argument(monkeypatch):
    _, calls = _run(monkeypatch, "openai", "")
    assert "proxies" not in calls[0][1]


def test_local_endpoints_bypass_the_proxy(monkeypatch):
    _, calls = _run(monkeypatch, "openai_compatible", "http://proxy:3128",
                    aipp_openai_compatible_base_url="http://127.0.0.1:8000/v1",
                    aipp_openai_compatible_api_key="k")
    assert "proxies" not in calls[0][1]
    _, calls = _run(monkeypatch, "openai_compatible", "http://proxy:3128",
                    aipp_openai_compatible_base_url="https://llm.example.com/v1",
                    aipp_openai_compatible_api_key="k")
    assert calls[0][1]["proxies"]["https"] == "http://proxy:3128"


def test_bad_proxy_is_ignored_not_fatal(monkeypatch):
    out, calls = _run(monkeypatch, "openai", "ftp://nope:1")
    assert out == "done" and "proxies" not in calls[0][1]


def test_socks_without_pysocks_leaves_transcript_untouched(monkeypatch):
    import voxd.core.aipp as A
    from voxd.core.config import get_config
    monkeypatch.setattr(A, "socks_supported", lambda: False)
    monkeypatch.setattr(A.requests, "post", lambda *a, **k: pytest.fail("must not connect directly"))
    cfg = get_config()
    cfg.data.update(aipp_enabled=True, aipp_provider="openai", aipp_proxy="socks5://h:1080")
    assert A.get_final_text("text", cfg) == "text"


def test_check_connection_reports_route(monkeypatch):
    import voxd.core.aipp as A
    from voxd.core.config import get_config
    seen = {}
    monkeypatch.setattr(A, "socks_supported", lambda: True)
    monkeypatch.setattr(A.requests, "get", lambda url, **kw: seen.update(url=url, **kw))
    cfg = get_config()
    cfg.data.update(aipp_provider="openrouter", aipp_proxy="socks5://127.0.0.1:1080")
    ok, msg = A.check_connection(cfg)
    assert ok and "openrouter.ai" in msg and "socks5h proxy 127.0.0.1" in msg
    assert seen["proxies"]["https"] == "socks5h://127.0.0.1:1080"

    def boom(url, **kw):
        raise A.requests.ConnectionError("refused")
    monkeypatch.setattr(A.requests, "get", boom)
    ok, msg = A.check_connection(cfg)
    assert not ok and "refused" in msg
    assert A.check_connection(cfg, "ollama")[0] is False
