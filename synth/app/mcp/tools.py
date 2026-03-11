from typing import Any

from app.mcp.client import MCPTool


def tool_to_openai_format(tool: MCPTool) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema
        }
    }


def tool_to_anthropic_format(tool: MCPTool) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema
    }


def tools_to_provider_format(tools: list[MCPTool], provider: str) -> list[dict[str, Any]]:
    if provider in ("openai", "generic"):
        return [tool_to_openai_format(t) for t in tools]
    elif provider == "anthropic":
        return [tool_to_anthropic_format(t) for t in tools]
    else:
        return [tool_to_openai_format(t) for t in tools]
