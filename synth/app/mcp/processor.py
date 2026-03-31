import json
from pathlib import Path
from typing import Any

from app.mcp import MCPManager, tools_to_provider_format, MCPTool
from app.logger import debug, warning


BUILTIN_TOOLS: list[MCPTool] = [
    MCPTool(
        name="manageembeddings",
        description="Manage project embeddings indexes: list, create, delete, enable, disable",
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "create", "delete", "enable", "disable"],
                    "description": "Action to perform"
                },
                "project_name": {
                    "type": "string",
                    "description": "Name of the Synth project"
                },
                "index_name": {
                    "type": "string",
                    "description": "Name of the embeddings index (for create, delete, enable, disable)"
                },
                "source_dir": {
                    "type": "string",
                    "description": "Absolute path to directory with files to index (for create)"
                },
                "description": {
                    "type": "string",
                    "description": "Description for the index (for create)"
                },
                "chunking_strategy": {
                    "type": "string",
                    "enum": ["fixed", "structure"],
                    "description": "Chunking strategy for create",
                    "default": "structure"
                },
                "chunk_size": {
                    "type": "integer",
                    "description": "Chunk size in tokens (for fixed strategy)",
                    "default": 50
                },
                "overlap": {
                    "type": "integer",
                    "description": "Overlap between chunks",
                    "default": 5
                }
            },
            "required": ["action", "project_name"]
        }
    ),
]


async def get_mcp_tools(server_names: list[str], provider_name: str) -> list[dict[str, Any]]:
    result = []
    
    result.extend(tools_to_provider_format(BUILTIN_TOOLS, provider_name))
    
    if not server_names:
        return result
    
    try:
        tools = await MCPManager.get_tools(server_names)
        result.extend(tools_to_provider_format(tools, provider_name))
        return result
    except Exception as e:
        warning("MCP", f"Failed to get tools: {e}")
        return result


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
        
        debug("MCP", f"Calling tool: {tool_name} with args: {tool_args}")
        
        builtin_names = {t.name for t in BUILTIN_TOOLS}
        if tool_name in builtin_names:
            tool_result_content = await handle_builtin_tool(tool_name, tool_args)
        else:
            try:
                result = await MCPManager.call_tool(tool_name, tool_args)
                tool_result_content = result.content
            except Exception as e:
                tool_result_content = f"Error: {str(e)}"
                warning("MCP", f"Tool call error: {e}")
        
        formatted_result = format_tool_result_for_provider(
            tool_result_content, tool_call_id, provider_name
        )
        
        if provider_name == "anthropic":
            results.append(formatted_result)
        else:
            results.append(formatted_result)
    
    return results


async def handle_builtin_tool(tool_name: str, args: dict[str, Any]) -> str:
    if tool_name == "manageembeddings":
        return await builtin_manage_embeddings(args)
    return f"Unknown built-in tool: {tool_name}"


async def call_mcp_tool(tool_name: str, tool_args: dict[str, Any]) -> str:
    """Call an MCP tool, handling both builtin and external tools."""
    builtin_names = {t.name for t in BUILTIN_TOOLS}
    if tool_name in builtin_names:
        return await handle_builtin_tool(tool_name, tool_args)
    else:
        try:
            result = await MCPManager.call_tool(tool_name, tool_args)
            return result.content
        except Exception as e:
            return f"Error: {str(e)}"


async def builtin_manage_embeddings(args: dict[str, Any]) -> str:
    from pathlib import Path
    from app.embeddings.config import embeddings_config
    from app.embeddings.embedder import create_embedder
    from app.embeddings.indexer import EmbeddingIndexer
    from app.embeddings.storage import embedding_storage
    from app.project_manager import project_manager
    
    action = args.get("action")
    project_name = args.get("project_name")
    index_name = args.get("index_name")
    
    if not action:
        return "Error: 'action' is required"
    if not project_name:
        return "Error: 'project_name' is required"
    
    if action == "list":
        return await _manage_list(project_name)
    elif action == "create":
        return await _manage_create(args, project_name)
    elif action == "delete":
        return await _manage_delete(project_name, index_name)
    elif action == "enable":
        return await _manage_enable_disable(project_name, index_name, True)
    elif action == "disable":
        return await _manage_enable_disable(project_name, index_name, False)
    else:
        return f"Error: Unknown action '{action}'. Use: list, create, delete, enable, disable"


async def _manage_list(project_name: str) -> str:
    from app.project_manager import project_manager
    from app.embeddings.storage import embedding_storage
    
    if not project_manager.project_exists(project_name):
        return f"Error: Project '{project_name}' does not exist"
    
    indexes = project_manager.get_embeddings_indexes(project_name)
    
    if not indexes:
        return f"No embeddings indexes configured for project '{project_name}'"
    
    result = [f"Embeddings indexes for project '{project_name}':\n"]
    
    for idx in indexes:
        name = idx.get("name", "unknown")
        desc = idx.get("description", "")
        enabled = idx.get("enabled", True)
        
        faiss_index = embedding_storage.get_index_by_name(name)
        if faiss_index:
            version = faiss_index.version
            chunk_count = faiss_index.chunk_count
            status_icon = "✓" if enabled else "✗"
            result.append(f"{status_icon} {name} (v{version}, {chunk_count} chunks)")
        else:
            status_icon = "✗" if enabled else "✗"
            result.append(f"{status_icon} {name} - FAISS file missing!")
        
        if desc:
            result.append(f"   Description: {desc}")
    
    enabled_count = sum(1 for i in indexes if i.get("enabled", True))
    result.append(f"\nTotal: {len(indexes)} ({enabled_count} active)")
    
    return "\n".join(result)


async def _manage_create(args: dict, project_name: str) -> str:
    from pathlib import Path
    from app.embeddings.config import embeddings_config
    from app.embeddings.embedder import create_embedder
    from app.embeddings.indexer import EmbeddingIndexer
    from app.embeddings.storage import embedding_storage
    from app.project_manager import project_manager
    
    index_name = args.get("index_name")
    source_dir = args.get("source_dir")
    description = args.get("description", "")
    chunking_strategy = args.get("chunking_strategy", "structure")
    
    if not index_name:
        return "Error: 'index_name' is required for create"
    if not source_dir:
        return "Error: 'source_dir' is required for create"
    
    if not project_manager.project_exists(project_name):
        return f"Error: Project '{project_name}' does not exist"
    
    source_path = Path(source_dir)
    if not source_path.exists():
        return f"Error: Directory does not exist: {source_dir}"
    if not source_path.is_dir():
        return f"Error: Not a directory: {source_dir}"
    
    if chunking_strategy == "fixed":
        chunking_params = {
            "chunk_size": args.get("chunk_size", 50),
            "overlap": args.get("overlap", 5)
        }
    else:
        chunking_params = {
            "min_chunk_size": 20,
            "max_chunk_size": 150
        }
    
    try:
        provider = embeddings_config.default_provider
        model = embeddings_config.default_model
        embedder_config = embeddings_config.get_embedder_config(provider)
        embedder = create_embedder(provider, {**embedder_config, "model": model})
        
        indexer = EmbeddingIndexer(embedder)
        index_meta, chunks, faiss_index = indexer.create_index(
            source_dir=source_path,
            chunking_strategy=chunking_strategy,
            chunking_params=chunking_params,
        )
        
        existing_index = embedding_storage.get_index_by_name(index_name)
        version = 1
        if existing_index:
            version = existing_index.version + 1
        
        index_meta.name = index_name
        index_meta.version = version
        index_meta.provider = provider
        index_meta.model = model
        index_meta.chunking_strategy = chunking_strategy
        index_meta.chunking_params = chunking_params
        index_meta.source_dir = str(source_path)
        
        embedding_storage.save_index(index_meta, chunks, faiss_index)
        
        indexes = project_manager.get_embeddings_indexes(project_name)
        indexes.append({
            "name": index_name,
            "description": description,
            "enabled": True
        })
        project_manager.save_embeddings_indexes(project_name, indexes)
        
        return (
            f"Successfully created embeddings index '{index_name}'\n"
            f"Version: {version}\n"
            f"Chunk count: {len(chunks)}\n"
            f"Provider: {provider}\n"
            f"Model: {model}\n"
            f"Added to project: {project_name}"
        )
    
    except Exception as e:
        return f"Error creating embeddings index: {str(e)}"


async def _manage_delete(project_name: str, index_name: str) -> str:
    from app.embeddings.storage import embedding_storage
    from app.project_manager import project_manager
    
    if not index_name:
        return "Error: 'index_name' is required for delete"
    
    if not project_manager.project_exists(project_name):
        return f"Error: Project '{project_name}' does not exist"
    
    indexes = project_manager.get_embeddings_indexes(project_name)
    index_exists = any(i.get("name") == index_name for i in indexes)
    
    if not index_exists:
        return f"Error: Index '{index_name}' not found in project '{project_name}'"
    
    embedding_storage.delete_index_by_name(index_name, delete_all_versions=True)
    
    indexes = [i for i in indexes if i.get("name") != index_name]
    project_manager.save_embeddings_indexes(project_name, indexes)
    
    return f"Successfully deleted embeddings index '{index_name}' (all versions)"


async def _manage_enable_disable(project_name: str, index_name: str, enable: bool) -> str:
    from app.project_manager import project_manager
    
    if not index_name:
        return "Error: 'index_name' is required for enable/disable"
    
    if not project_manager.project_exists(project_name):
        return f"Error: Project '{project_name}' does not exist"
    
    indexes = project_manager.get_embeddings_indexes(project_name)
    
    found = False
    for idx in indexes:
        if idx.get("name") == index_name:
            idx["enabled"] = enable
            found = True
    
    if not found:
        return f"Error: Index '{index_name}' not found in project '{project_name}'"
    
    project_manager.save_embeddings_indexes(project_name, indexes)
    
    action = "enabled" if enable else "disabled"
    return f"Index '{index_name}' {action} for project '{project_name}'"


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
