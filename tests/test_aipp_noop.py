import asyncio
from whisp.aipp.engine import get_aipp_client

async def _run():
    cfg = {"aipp_enabled": False}
    cli = get_aipp_client(cfg)
    out = await cli.process("hello", "ignored")
    assert out == "hello"

def test_noop_driver():
    asyncio.run(_run())
