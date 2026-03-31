import asyncio
from typing import Any

_mcp_event_loop: asyncio.AbstractEventLoop | None = None


def get_mcp_loop() -> asyncio.AbstractEventLoop:
    global _mcp_event_loop
    if _mcp_event_loop is None or _mcp_event_loop.is_closed():
        _mcp_event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_mcp_event_loop)
    return _mcp_event_loop


def run_mcp_async(coro: Any) -> Any:
    loop = get_mcp_loop()
    return loop.run_until_complete(coro)
