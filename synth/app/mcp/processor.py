import asyncio
import json
from typing import Any

from app.llm.base import Message
from app.mcp import MCPManager, tools_to_provider_format


async def get_mcp_tools(server_names: list[str], provider_name: str) -> list[dict[str, Any]]:
    if not server_names:
        return []
    
    try:
        tools = await MCPManager.get_tools(server_names)
        return tools_to_provider_format(tools, provider_name)
    except Exception as e:
        print(f"[MCP] Failed to get tools: {e}")
        return []


def extract_tool_calls_from_response(response, provider_name: str) -> list[dict[str, Any]]:
    tool_calls = []
    
    if provider_name in ("openai", "anthropic", "generic", "minimax"):
        if hasattr(response, "content"):
            content_items = response.content
            if isinstance(content_items, list):
                for item in content_items:
                    if hasattr(item, "type"):
                        if item.type == "tool_use":
                            tool_calls.append({
                                "id": getattr(item, "id", None),
                                "name": getattr(item, "name", None),
                                "input": getattr(item, "input", {})
                            })
                        elif item.type == "function_call":
                            tool_calls.append({
                                "id": getattr(item, "id", None),
                                "name": getattr(item, "name", None),
                                "arguments": getattr(item, "arguments", {})
                            })
                    elif isinstance(item, dict):
                        if item.get("type") == "tool_use":
                            tool_calls.append({
                                "id": item.get("id"),
                                "name": item.get("name"),
                                "input": item.get("input", {})
                            })
                        elif "function_call" in item:
                            fc = item["function_call"]
                            tool_calls.append({
                                "id": fc.get("id"),
                                "name": fc.get("name"),
                                "arguments": fc.get("arguments", {})
                            })
    
    return tool_calls


def format_tool_result_for_provider(tool_result: str, tool_call_id: str, provider_name: str) -> dict[str, Any]:
    if provider_name == "anthropic":
        return {
            "type": "tool_result",
            "tool_use_id": tool_call_id,
            "content": tool_result
        }
    else:
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": tool_result
        }


async def process_tool_calls(
    tool_calls: list[dict[str, Any]],
    formatted_messages: list[dict[str, Any]],
    provider_name: str,
    max_tool_calls: int = 10
) -> list[dict[str, Any]]:
    results = []
    
    for i, tool_call in enumerate(tool_calls[:max_tool_calls]):
        tool_name = tool_call.get("name")
        tool_args = tool_call.get("input") or tool_call.get("arguments", {})
        tool_call_id = tool_call.get("id")
        
        if isinstance(tool_args, str):
            try:
                tool_args = json.loads(tool_args)
            except json.JSONDecodeError:
                tool_args = {}
        
        print(f"[MCP] Calling tool: {tool_name} with args: {tool_args}")
        
        try:
            result = await MCPManager.call_tool(tool_name, tool_args)
            tool_result_content = result.content
        except Exception as e:
            tool_result_content = f"Error: {str(e)}"
            print(f"[MCP] Tool call error: {e}")
        
        formatted_result = format_tool_result_for_provider(
            tool_result_content, tool_call_id, provider_name
        )
        
        if provider_name == "anthropic":
            results.append(formatted_result)
        else:
            results.append(formatted_result)
    
    return results


def has_tool_calls(response, provider_name: str) -> bool:
    if not hasattr(response, "content"):
        return False
    
    content = response.content
    if isinstance(content, list):
        for item in content:
            if hasattr(item, "type"):
                if item.type in ("tool_use", "function_call"):
                    return True
            elif isinstance(item, dict):
                if item.get("type") in ("tool_use", "function_call") or "function_call" in item:
                    return True
    
    return False
