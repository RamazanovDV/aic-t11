import asyncio
import os
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

try:
    ExceptionGroup
except NameError:
    from exceptiongroup import ExceptionGroup  # type: ignore

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False

import httpx
from httpx_sse import EventSource
from mcp.types import JSONRPCMessage, JSONRPCRequest, JSONRPCResponse

from app.mcp.config import mcp_config
from app.logger import debug, info, warning, error


@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class MCPToolResult:
    content: str
    is_error: bool = False


class MCPConnectionError(Exception):
    pass


class MCPClient:
    def __init__(self, server_name: str):
        if not MCP_AVAILABLE:
            raise ImportError("MCP package not installed. Run: pip install mcp")
        
        self.server_name = server_name
        server_config = mcp_config.get_server_config(server_name)
        
        if not server_config:
            raise ValueError(f"MCP server '{server_name}' not configured")
        
        self.server_type = server_config.get("type", "stdio")
        self.command = server_config.get("command")
        self.args = server_config.get("args", [])
        self.env = server_config.get("env", {})
        self.url = server_config.get("url")
        
        self._session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._client: httpx.AsyncClient | None = None
        self._session_id: str | None = None
        self._tools: list[MCPTool] = []

    async def connect(self) -> None:
        if self._client is not None:
            return
        
        try:
            if self.server_type == "stdio":
                await self._connect_stdio()
            elif self.server_type == "sse":
                await self._connect_sse()
            else:
                raise ValueError(f"Unknown MCP server type: {self.server_type}")
            
            await self._load_tools()
        except Exception as e:
            await self.cleanup()
            raise MCPConnectionError(f"Failed to connect to MCP server '{self.server_name}': {e}")

    async def _connect_stdio(self) -> None:
        if not self.command:
            raise ValueError(f"MCP server '{self.server_name}': 'command' required for stdio type")
        
        server_params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env={**os.environ, **self.env} if self.env else None
        )
        
        self._exit_stack = AsyncExitStack()
        stdio_transport = await self._exit_stack.enter_async_context(stdio_client(server_params))
        self._stdio, self._write = stdio_transport
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(self._stdio, self._write)
        )
        await self._session.initialize()

    async def _connect_sse(self) -> None:
        if not self.url:
            raise ValueError(f"MCP server '{self.server_name}': 'url' required for sse type")
        
        try:
            debug("MCP", f"Creating SSE connection to {self.url}")
            
            self._session_id = None
            self._client = httpx.AsyncClient(timeout=30.0)
            self._exit_stack = AsyncExitStack()
            await self._exit_stack.enter_async_context(self._client)
            
            debug("MCP", "Sending initialize via direct httpx...")
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
            
            response = await self._client.post(
                self.url,
                json={
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "mcp", "version": "1.0"}
                    },
                    "id": 1
                },
                headers=headers
            )
            
            response.raise_for_status()
            self._session_id = response.headers.get("mcp-session-id")
            debug("MCP", f"Got session ID: {self._session_id}")
            
            content_type = response.headers.get("content-type", "").lower()
            if content_type.startswith("text/event-stream"):
                event_source = EventSource(response)
                async for sse in event_source.aiter_sse():
                    if sse.data:
                        debug("MCP", f"SSE initialize response: {sse.data[:100]}...")
                        break
            
            debug("MCP", "Session initialized via direct httpx")
            
            self._session = None  # We'll call tools directly
            
        except Exception as e:
            error("MCP", f"Connection error: {e}")
            raise MCPConnectionError(f"Failed to connect to MCP server '{self.server_name}': {e}")

    async def _load_tools(self) -> None:
        if not self._client or not self._session_id:
            raise MCPConnectionError("Not connected")
        
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "mcp-session-id": self._session_id,
        }
        
        response = await self._client.post(
            self.url,
            json={
                "jsonrpc": "2.0",
                "method": "tools/list",
                "params": {},
                "id": 2
            },
            headers=headers
        )
        response.raise_for_status()
        
        content_type = response.headers.get("content-type", "").lower()
        if content_type.startswith("text/event-stream"):
            event_source = EventSource(response)
            async for sse in event_source.aiter_sse():
                if sse.data:
                    msg = JSONRPCMessage.model_validate_json(sse.data)
                    if isinstance(msg.root, JSONRPCResponse) and msg.root.result:
                        tools_data = msg.root.result.get("tools", [])
                        self._tools = [
                            MCPTool(
                                name=tool.get("name", ""),
                                description=tool.get("description", ""),
                                input_schema=tool.get("inputSchema", {})
                            )
                            for tool in tools_data
                        ]
                    break
        elif content_type.startswith("application/json"):
            content = response.read()
            msg = JSONRPCMessage.model_validate_json(content)
            if isinstance(msg.root, JSONRPCResponse) and msg.root.result:
                tools_data = msg.root.result.get("tools", [])
                self._tools = [
                    MCPTool(
                        name=tool.get("name", ""),
                        description=tool.get("description", ""),
                        input_schema=tool.get("inputSchema", {})
                    )
                    for tool in tools_data
                ]

    async def list_tools(self) -> list[MCPTool]:
        if not self._session:
            await self.connect()
        return self._tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPToolResult:
        if not self._client or not self._session_id:
            await self.connect()
        
        if not self._client or not self._session_id:
            raise MCPConnectionError("Not connected")
        
        try:
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "mcp-session-id": self._session_id,
            }
            
            response = await self._client.post(
                self.url,
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": name,
                        "arguments": arguments
                    },
                    "id": 3
                },
                headers=headers
            )
            response.raise_for_status()
            
            content_type = response.headers.get("content-type", "").lower()
            if content_type.startswith("text/event-stream"):
                event_source = EventSource(response)
                async for sse in event_source.aiter_sse():
                    if sse.data:
                        msg = JSONRPCMessage.model_validate_json(sse.data)
                        if isinstance(msg.root, JSONRPCResponse) and msg.root.result:
                            result_content = msg.root.result.get("content", [])
                            content_parts = []
                            for item in result_content:
                                if isinstance(item, dict) and item.get("type") == "text":
                                    content_parts.append(item.get("text", ""))
                                else:
                                    content_parts.append(str(item))
                            return MCPToolResult(content="\n".join(content_parts))
                        elif isinstance(msg.root, JSONRPCError):
                            return MCPToolResult(content=f"Error: {msg.root.error.get('message', 'Unknown error')}", is_error=True)
                        break
            return MCPToolResult(content="No response from tool", is_error=True)
            
        except asyncio.TimeoutError:
            return MCPToolResult(content=f"Error: Tool call timed out after 30 seconds", is_error=True)
        except Exception as e:
            return MCPToolResult(content=f"Error: {str(e)}", is_error=True)

    async def cleanup(self) -> None:
        if hasattr(self, '_client') and self._client:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None
        
        if self._exit_stack:
            try:
                await self._exit_stack.aclose()
            except asyncio.CancelledError:
                pass
            except GeneratorExit:
                pass
            except StopAsyncIteration:
                pass
            except ExceptionGroup as e:
                suppressed = (GeneratorExit, StopAsyncIteration, asyncio.CancelledError)
                if not all(isinstance(exc, suppressed) for exc in e.exceptions):
                    warning("MCP", f"Cleanup warning (mixed): {e}")
            except RuntimeError as e:
                if "cancel scope" not in str(e).lower():
                    warning("MCP", f"Cleanup warning: {e}")
            except StopIteration:
                pass
            except Exception as e:
                warning("MCP", f"Cleanup warning: {e}")
        
        self._exit_stack = None
        self._session = None
        self._tools = []


class MCPManager:
    _clients: dict[tuple[str, int], MCPClient] = {}
    _locks: dict[tuple[str, int], asyncio.Lock] = {}

    @classmethod
    def _get_client_key(cls, server_name: str) -> tuple[str, int]:
        return (server_name, 1)  # Use fixed loop_id = 1 for persistent loop

    @classmethod
    async def get_client(cls, server_name: str) -> MCPClient:
        key = cls._get_client_key(server_name)
        
        # Всегда создаём новое соединение
        if key in cls._clients:
            try:
                await cls._clients[key].cleanup()
            except Exception:
                pass
            del cls._clients[key]
        
        client = MCPClient(server_name)
        await client.connect()
        cls._clients[key] = client
        return cls._clients[key]

    @classmethod
    async def get_tools(cls, server_names: list[str]) -> list[MCPTool]:
        all_tools = []
        for server_name in server_names:
            try:
                info("MCP", f"Connecting to {server_name}...")
                client = await asyncio.wait_for(cls.get_client(server_name), timeout=15.0)
                debug("MCP", f"Loading tools from {server_name}...")
                tools = await asyncio.wait_for(client.list_tools(), timeout=15.0)
                debug("MCP", f"Got {len(tools)} tools from {server_name}")
                for tool in tools:
                    tool.name = f"{server_name}_{tool.name}"
                all_tools.extend(tools)
            except asyncio.TimeoutError:
                warning("MCP", f"Timeout connecting to '{server_name}'")
            except Exception as e:
                warning("MCP", f"Failed to get tools from '{server_name}': {e}")
        return all_tools

    @classmethod
    async def call_tool(cls, full_name: str, arguments: dict[str, Any]) -> MCPToolResult:
        if "_" not in full_name:
            raise ValueError(f"Invalid tool name format: {full_name}. Expected: server_toolname")
        
        server_name, tool_name = full_name.split("_", 1)
        client = await cls.get_client(server_name)
        return await client.call_tool(tool_name, arguments)

    @classmethod
    async def cleanup_all(cls) -> None:
        for client in cls._clients.values():
            await client.cleanup()
        cls._clients.clear()

    @classmethod
    def _get_lock(cls, key: tuple[str, int]) -> asyncio.Lock:
        if key not in cls._locks:
            cls._locks[key] = asyncio.Lock()
        return cls._locks[key]

    @classmethod
    async def cleanup_all(cls) -> None:
        # Используем фиксированный loop_id = 1 для персистентного loop
        key_prefix = 1
        
        keys_to_remove = [k for k in cls._clients if k[1] == key_prefix]
        for key in keys_to_remove:
            try:
                await cls._clients[key].cleanup()
            except Exception:
                pass
            del cls._clients[key]
        
        locks_to_remove = [k for k in cls._locks if k[1] == key_prefix]
        for key in locks_to_remove:
            del cls._locks[key]


def mcp_available() -> bool:
    return MCP_AVAILABLE
