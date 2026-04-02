import json
from typing import Any

from app.mcp import MCPManager, tools_to_provider_format, MCPTool
from app.logger import debug, warning
from app.tools import (
    builtin_code_review,
    builtin_get_current_project,
    builtin_list_project_repos,
    builtin_get_repo_info,
    builtin_read_file,
    builtin_list_directory,
    builtin_grep_files,
    builtin_write_file,
    builtin_edit_file,
    builtin_create_directory,
    builtin_delete_file,
    builtin_delete_directory,
)
from app.tools.git_ops import (
    builtin_git_status,
    builtin_git_log,
    builtin_git_diff,
    builtin_git_branch_list,
    builtin_git_show,
    builtin_git_blame,
    builtin_git_commit,
    builtin_git_push,
    builtin_git_pull,
    builtin_git_checkout,
    builtin_git_reset,
    builtin_git_rebase,
    builtin_git_merge,
    builtin_git_stash,
    builtin_git_cherry_pick,
    builtin_git_fetch,
)


TOOL_CAPABILITIES: dict[str, list[str]] = {
    "read_file": ["file_read"],
    "list_directory": ["file_read"],
    "grep_files": ["file_search"],
    "write_file": ["file_write"],
    "edit_file": ["file_edit"],
    "create_directory": ["file_write"],
    "delete_file": ["file_write"],
    "delete_directory": ["file_write"],
    "manageembeddings": ["development"],
    "code_review": ["code_review"],
    "get_current_project": ["development", "devops", "architecture"],
    "list_project_repos": ["development", "devops", "architecture"],
    "get_repo_info": ["development", "devops", "architecture"],
    "git_status": ["git_read"],
    "git_log": ["git_read"],
    "git_diff": ["git_read"],
    "git_branch_list": ["git_read"],
    "git_show": ["git_read"],
    "git_blame": ["git_read"],
    "git_commit": ["git_write"],
    "git_push": ["git_write"],
    "git_pull": ["git_write"],
    "git_checkout": ["git_write"],
    "git_reset": ["git_write"],
    "git_rebase": ["git_write"],
    "git_merge": ["git_write"],
    "git_stash": ["git_write"],
    "git_cherry_pick": ["git_write"],
    "git_fetch": ["git_write"],
}


def _tool_has_required_capability(tool_name: str, capabilities: list[str]) -> bool:
    required = TOOL_CAPABILITIES.get(tool_name, [])
    if not required:
        return True
    return any(cap in capabilities for cap in required)


def _filter_tools_by_capabilities(
    tools: list[MCPTool], capabilities: list[str]
) -> list[MCPTool]:
    if not capabilities:
        return tools
    return [t for t in tools if _tool_has_required_capability(t.name, capabilities)]


def _filter_dict_tools_by_capabilities(
    tools: list[dict], capabilities: list[str]
) -> list[dict]:
    if not capabilities:
        return tools
    result = []
    for tool in tools:
        if "function" in tool:
            name = tool["function"].get("name", "")
        elif "name" in tool:
            name = tool.get("name", "")
        else:
            continue
        if _tool_has_required_capability(name, capabilities):
            result.append(tool)
    return result


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
    MCPTool(
        name="code_review",
        description="Perform code review on a repository. Analyzes git diff and returns findings with severity, title, message, and suggestions. Use this when user asks to review code, changes, or a pull request.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_name": {
                    "type": "string",
                    "description": "Name of the repository to review (must be in current project)"
                },
                "target": {
                    "type": "string",
                    "description": "Target branch/commit for comparison (default: HEAD)",
                    "default": "HEAD"
                },
                "base": {
                    "type": "string",
                    "description": "Base branch for diff comparison (optional, leave empty for uncommitted changes)"
                }
            },
            "required": ["repo_name"]
        }
    ),
    MCPTool(
        name="get_current_project",
        description="Get information about the current project in the session. Returns project name, path, repositories count, and embeddings indexes.",
        input_schema={
            "type": "object",
            "properties": {}
        }
    ),
    MCPTool(
        name="list_project_repos",
        description="List all git repositories connected to a project. Returns repository names, URLs, local paths, and status.",
        input_schema={
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Name of the project (optional if session has active project)"
                }
            }
        }
    ),
    MCPTool(
        name="get_repo_info",
        description="Get detailed information about a specific repository in a project.",
        input_schema={
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Name of the project"
                },
                "repo_name": {
                    "type": "string",
                    "description": "Name of the repository"
                }
            },
            "required": ["repo_name"]
        }
    ),
    MCPTool(
        name="read_file",
        description="Read contents of a file. Requires active project in session. Only works with files within project's repos directory.",
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file to read"
                },
                "offset": {
                    "type": "integer",
                    "description": "Line offset to start reading from (0-based, default: 0)",
                    "default": 0
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read (default: 500)",
                    "default": 500
                }
            },
            "required": ["file_path"]
        }
    ),
    MCPTool(
        name="list_directory",
        description="List files and directories. Requires active project in session. Only works within project's repos directory.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the directory to list"
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Recurse into subdirectories (default: false)",
                    "default": False
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum recursion depth when recursive=true (default: 3)",
                    "default": 3
                },
                "include_hidden": {
                    "type": "boolean",
                    "description": "Include hidden files (starting with .) (default: false)",
                    "default": False
                }
            },
            "required": ["path"]
        }
    ),
    MCPTool(
        name="grep_files",
        description="Search for text pattern in files. Requires active project in session. Only searches within project's repos directory.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to directory to search in"
                },
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for"
                },
                "file_glob": {
                    "type": "string",
                    "description": "File glob pattern to filter files (e.g., '*.py', '*.{js,ts}') (default: all files)",
                    "default": "*"
                },
                "case_sensitive": {
                    "type": "boolean",
                    "description": "Case sensitive search (default: false)",
                    "default": False
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of matching lines to return (default: 100)",
                    "default": 100
                }
            },
            "required": ["path", "pattern"]
        }
    ),
    MCPTool(
        name="write_file",
        description="Create or overwrite a file. Requires active project in session. Only works within project's repos directory.",
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file to write"
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file"
                }
            },
            "required": ["file_path", "content"]
        }
    ),
    MCPTool(
        name="edit_file",
        description="Edit a file section. Requires active project in session. Only works within project's repos directory.",
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file to edit"
                },
                "old_string": {
                    "type": "string",
                    "description": "The exact text to find and replace"
                },
                "new_string": {
                    "type": "string",
                    "description": "The replacement text"
                }
            },
            "required": ["file_path", "old_string", "new_string"]
        }
    ),
    MCPTool(
        name="create_directory",
        description="Create a directory. Requires active project in session. Only works within project's repos directory.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the directory to create"
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Create parent directories if they don't exist (default: true)",
                    "default": True
                }
            },
            "required": ["path"]
        }
    ),
    MCPTool(
        name="delete_file",
        description="Delete a file. Requires active project in session. Only works within project's repos directory.",
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file to delete"
                }
            },
            "required": ["file_path"]
        }
    ),
    MCPTool(
        name="delete_directory",
        description="Delete a directory recursively. Requires active project in session. Only works within project's repos directory.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the directory to delete"
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Must be true to delete non-empty directories (default: true)",
                    "default": True
                }
            },
            "required": ["path"]
        }
    ),
    MCPTool(
        name="git_status",
        description="Show working tree status. Requires active project. Use list_project_repos to get available repositories.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_name": {"type": "string", "description": "Name of git repository in project"},
                "short": {"type": "boolean", "default": True}
            }
        }
    ),
    MCPTool(
        name="git_log",
        description="Show commit logs. Requires active project. Use list_project_repos to get available repositories.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_name": {"type": "string", "description": "Name of git repository in project"},
                "max_count": {"type": "integer", "default": 20},
                "oneline": {"type": "boolean", "default": True}
            }
        }
    ),
    MCPTool(
        name="git_diff",
        description="Show changes between commits. Requires active project. Use list_project_repos to get available repositories.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_name": {"type": "string", "description": "Name of git repository in project"},
                "target": {"type": "string"},
                "file": {"type": "string"},
                "cached": {"type": "boolean"}
            }
        }
    ),
    MCPTool(
        name="git_branch_list",
        description="List all branches. Requires active project. Use list_project_repos to get available repositories.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_name": {"type": "string", "description": "Name of git repository in project"},
                "all": {"type": "boolean"},
                "verbose": {"type": "boolean"}
            }
        }
    ),
    MCPTool(
        name="git_show",
        description="Show various types of objects. Requires active project. Use list_project_repos to get available repositories.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_name": {"type": "string", "description": "Name of git repository in project"},
                "object": {"type": "string"}
            }
        }
    ),
    MCPTool(
        name="git_blame",
        description="Show what revision and author last modified each line. Requires active project. Use list_project_repos to get available repositories.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_name": {"type": "string", "description": "Name of git repository in project"},
                "file": {"type": "string"}
            },
            "required": ["file"]
        }
    ),
    MCPTool(
        name="git_commit",
        description="Create a new commit. Requires active project. Use list_project_repos to get available repositories.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_name": {"type": "string", "description": "Name of git repository in project"},
                "message": {"type": "string"},
                "amend": {"type": "boolean"}
            },
            "required": ["message"]
        }
    ),
    MCPTool(
        name="git_push",
        description="Push commits to remote. Requires active project. Use list_project_repos to get available repositories.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_name": {"type": "string", "description": "Name of git repository in project"},
                "remote": {"type": "string"},
                "force": {"type": "boolean"}
            }
        }
    ),
    MCPTool(
        name="git_pull",
        description="Fetch and integrate changes. Requires active project. Use list_project_repos to get available repositories.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_name": {"type": "string", "description": "Name of git repository in project"},
                "remote": {"type": "string"},
                "rebase": {"type": "boolean"}
            }
        }
    ),
    MCPTool(
        name="git_checkout",
        description="Switch branches. Requires active project. Use list_project_repos to get available repositories.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_name": {"type": "string", "description": "Name of git repository in project"},
                "branch": {"type": "string"},
                "new_branch": {"type": "string"},
                "force": {"type": "boolean"}
            },
            "required": ["branch"]
        }
    ),
    MCPTool(
        name="git_reset",
        description="Reset current HEAD. Requires active project. Use list_project_repos to get available repositories.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_name": {"type": "string", "description": "Name of git repository in project"},
                "target": {"type": "string"},
                "mode": {"type": "string", "enum": ["soft", "mixed", "hard"]}
            }
        }
    ),
    MCPTool(
        name="git_rebase",
        description="Reapply commits on top of another base. Requires active project. Use list_project_repos to get available repositories.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_name": {"type": "string", "description": "Name of git repository in project"},
                "base": {"type": "string"},
                "continue": {"type": "boolean"},
                "abort": {"type": "boolean"}
            }
        }
    ),
    MCPTool(
        name="git_merge",
        description="Join two or more development histories. Requires active project. Use list_project_repos to get available repositories.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_name": {"type": "string", "description": "Name of git repository in project"},
                "branch": {"type": "string"},
                "no_ff": {"type": "boolean"},
                "squash": {"type": "boolean"}
            },
            "required": ["branch"]
        }
    ),
    MCPTool(
        name="git_stash",
        description="Stash changes. Requires active project. Use list_project_repos to get available repositories.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_name": {"type": "string", "description": "Name of git repository in project"},
                "action": {"type": "string", "enum": ["push", "pop", "list", "drop", "apply"]},
                "message": {"type": "string"}
            }
        }
    ),
    MCPTool(
        name="git_cherry_pick",
        description="Apply changes from commits. Requires active project. Use list_project_repos to get available repositories.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_name": {"type": "string", "description": "Name of git repository in project"},
                "commits": {"type": "array", "items": {"type": "string"}},
                "continue": {"type": "boolean"},
                "abort": {"type": "boolean"}
            },
            "required": ["commits"]
        }
    ),
    MCPTool(
        name="git_fetch",
        description="Download objects and refs. Requires active project. Use list_project_repos to get available repositories.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_name": {"type": "string", "description": "Name of git repository in project"},
                "remote": {"type": "string"},
                "all": {"type": "boolean"},
                "prune": {"type": "boolean"}
            }
        }
    ),
]


async def get_mcp_tools(
    server_names: list[str],
    provider_name: str,
    required_capabilities: list[str] | None = None
) -> list[dict[str, Any]]:
    result = []

    filtered_builtin = _filter_tools_by_capabilities(BUILTIN_TOOLS, required_capabilities or [])
    result.extend(tools_to_provider_format(filtered_builtin, provider_name))

    if not server_names:
        return result

    try:
        tools = await MCPManager.get_tools(server_names)
        filtered_external = _filter_tools_by_capabilities(tools, required_capabilities or [])
        result.extend(tools_to_provider_format(filtered_external, provider_name))
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
    max_tool_calls: int = 10,
    required_capabilities: list[str] | None = None,
    session: Any = None
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

        if required_capabilities is not None:
            if not _tool_has_required_capability(tool_name, required_capabilities):
                required = TOOL_CAPABILITIES.get(tool_name, [])
                missing = [r for r in required if r not in required_capabilities]
                tool_result_content = f"Error: Tool '{tool_name}' requires capability: {', '.join(missing)}"
            else:
                builtin_names = {t.name for t in BUILTIN_TOOLS}
                if tool_name in builtin_names:
                    tool_result_content = await handle_builtin_tool(tool_name, tool_args, session)
                else:
                    try:
                        result = await MCPManager.call_tool(tool_name, tool_args)
                        tool_result_content = result.content
                    except Exception as e:
                        tool_result_content = f"Error: {str(e)}"
                        warning("MCP", f"Tool call error: {e}")
        else:
            builtin_names = {t.name for t in BUILTIN_TOOLS}
            if tool_name in builtin_names:
                tool_result_content = await handle_builtin_tool(tool_name, tool_args, session)
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


async def handle_builtin_tool(tool_name: str, args: dict[str, Any], session: Any = None) -> str:
    project_name = None
    if session and hasattr(session, 'status'):
        project_name = session.status.get("project")

    if tool_name == "manageembeddings":
        return await builtin_manage_embeddings(args)
    elif tool_name == "code_review":
        return await builtin_code_review(args)
    elif tool_name == "get_current_project":
        return await builtin_get_current_project(args, session)
    elif tool_name == "list_project_repos":
        return await builtin_list_project_repos(args, session)
    elif tool_name == "get_repo_info":
        return await builtin_get_repo_info(args, session)
    elif tool_name == "read_file":
        return await builtin_read_file(args, project_name)
    elif tool_name == "list_directory":
        return await builtin_list_directory(args, project_name)
    elif tool_name == "grep_files":
        return await builtin_grep_files(args, project_name)
    elif tool_name == "write_file":
        return await builtin_write_file(args, project_name)
    elif tool_name == "edit_file":
        return await builtin_edit_file(args, project_name)
    elif tool_name == "create_directory":
        return await builtin_create_directory(args, project_name)
    elif tool_name == "delete_file":
        return await builtin_delete_file(args, project_name)
    elif tool_name == "delete_directory":
        return await builtin_delete_directory(args, project_name)
    elif tool_name == "git_status":
        return await builtin_git_status(args, project_name)
    elif tool_name == "git_log":
        return await builtin_git_log(args, project_name)
    elif tool_name == "git_diff":
        return await builtin_git_diff(args, project_name)
    elif tool_name == "git_branch_list":
        return await builtin_git_branch_list(args, project_name)
    elif tool_name == "git_show":
        return await builtin_git_show(args, project_name)
    elif tool_name == "git_blame":
        return await builtin_git_blame(args, project_name)
    elif tool_name == "git_commit":
        return await builtin_git_commit(args, project_name)
    elif tool_name == "git_push":
        return await builtin_git_push(args, project_name)
    elif tool_name == "git_pull":
        return await builtin_git_pull(args, project_name)
    elif tool_name == "git_checkout":
        return await builtin_git_checkout(args, project_name)
    elif tool_name == "git_reset":
        return await builtin_git_reset(args, project_name)
    elif tool_name == "git_rebase":
        return await builtin_git_rebase(args, project_name)
    elif tool_name == "git_merge":
        return await builtin_git_merge(args, project_name)
    elif tool_name == "git_stash":
        return await builtin_git_stash(args, project_name)
    elif tool_name == "git_cherry_pick":
        return await builtin_git_cherry_pick(args, project_name)
    elif tool_name == "git_fetch":
        return await builtin_git_fetch(args, project_name)
    return f"Unknown built-in tool: {tool_name}"


async def call_mcp_tool(
    tool_name: str,
    tool_args: dict[str, Any],
    required_capabilities: list[str] | None = None,
    session: Any = None
) -> str:
    """Call an MCP tool, handling both builtin and external tools."""
    if required_capabilities is not None:
        if not _tool_has_required_capability(tool_name, required_capabilities):
            required = TOOL_CAPABILITIES.get(tool_name, [])
            missing = [r for r in required if r not in required_capabilities]
            return f"Error: Tool '{tool_name}' requires capability: {', '.join(missing)}"

    builtin_names = {t.name for t in BUILTIN_TOOLS}
    if tool_name in builtin_names:
        return await handle_builtin_tool(tool_name, tool_args, session)
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
