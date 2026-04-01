#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "synth"))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from app.config import config
from app.git_clone_service import git_clone_service
from app.git_repo_manager import git_repo_manager


ALLOWED_DIRS = os.environ.get("ALLOWED_DIRS", "/home:/workspace:/projects").split(":")
GIT_REPO_PATH = os.environ.get("GIT_REPO_PATH", "/home")


def _validate_path(path: str) -> bool:
    for allowed in ALLOWED_DIRS:
        if path.startswith(allowed):
            return True
    return False


def _sanitize_repo_path(project_name: str, repo_name: str) -> Path:
    base = config.data_dir / "projects" / project_name / "repos" / repo_name
    if not _validate_path(str(base)):
        raise ValueError(f"Path not allowed: {base}")
    return base


app = Server("synth-git")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="git_clone",
            description="Clone a git repository",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Repository URL (HTTPS or SSH)"},
                    "path": {"type": "string", "description": "Local path to clone to"},
                    "branch": {"type": "string", "description": "Branch to checkout", "default": "main"},
                    "agent": {"type": "string", "description": "Agent name for SSH key"},
                    "ssh_key_id": {"type": "string", "description": "Specific SSH key ID to use"},
                },
                "required": ["url", "path"]
            }
        ),
        Tool(
            name="git_fetch",
            description="Fetch updates from remote repository",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Path to local repository"},
                    "agent": {"type": "string", "description": "Agent name for SSH key"},
                    "ssh_key_id": {"type": "string", "description": "Specific SSH key ID"},
                    "remote": {"type": "string", "description": "Remote name", "default": "origin"},
                },
                "required": ["repo_path"]
            }
        ),
        Tool(
            name="git_branch",
            description="Get current branch name",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Path to local repository"},
                },
                "required": ["repo_path"]
            }
        ),
        Tool(
            name="git_list_branches",
            description="List all branches in repository",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Path to local repository"},
                    "remote": {"type": "boolean", "description": "Include remote branches", "default": False},
                },
                "required": ["repo_path"]
            }
        ),
        Tool(
            name="git_status",
            description="Get repository status",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Path to local repository"},
                },
                "required": ["repo_path"]
            }
        ),
        Tool(
            name="git_diff",
            description="Get diff between commits, branches, or against working tree",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Path to local repository"},
                    "target": {"type": "string", "description": "Target commit/branch (default: HEAD)"},
                    "base": {"type": "string", "description": "Base commit/branch for diff"},
                },
                "required": ["repo_path"]
            }
        ),
        Tool(
            name="git_log",
            description="Get commit history",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Path to local repository"},
                    "limit": {"type": "integer", "description": "Number of commits", "default": 50},
                    "branch": {"type": "string", "description": "Specific branch to log"},
                },
                "required": ["repo_path"]
            }
        ),
        Tool(
            name="git_show",
            description="Get commit details or file at specific commit",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Path to local repository"},
                    "commit": {"type": "string", "description": "Commit hash or ref"},
                    "file_path": {"type": "string", "description": "Get specific file at commit"},
                },
                "required": ["repo_path", "commit"]
            }
        ),
        Tool(
            name="git_checkout",
            description="Checkout a branch",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Path to local repository"},
                    "branch": {"type": "string", "description": "Branch to checkout"},
                },
                "required": ["repo_path", "branch"]
            }
        ),
        Tool(
            name="git_remote_url",
            description="Get remote URL for repository",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Path to local repository"},
                },
                "required": ["repo_path"]
            }
        ),
        Tool(
            name="git_current_commit",
            description="Get current commit hash",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Path to local repository"},
                },
                "required": ["repo_path"]
            }
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "git_clone":
            url = arguments.get("url", "")
            path_str = arguments.get("path", "")
            branch = arguments.get("branch", "main")
            agent = arguments.get("agent")
            ssh_key_id = arguments.get("ssh_key_id")

            if not url or not path_str:
                return [TextContent(type="text", text="Error: url and path are required")]

            path = Path(path_str)
            if not _validate_path(str(path.parent)):
                return [TextContent(type="text", text=f"Error: Path not allowed: {path}")]

            result = git_clone_service.clone(
                url=url,
                local_path=path,
                agent_name=agent,
                key_id=ssh_key_id,
                branch=branch
            )

            if result.success:
                return [TextContent(type="text", text=json.dumps({
                    "success": True,
                    "path": result.local_path,
                    "commit": result.commit,
                    "message": result.message
                }, ensure_ascii=False))]
            else:
                return [TextContent(type="text", text=json.dumps({
                    "success": False,
                    "error": result.message
                }, ensure_ascii=False))]

        elif name == "git_fetch":
            repo_path_str = arguments.get("repo_path", "")
            agent = arguments.get("agent")
            ssh_key_id = arguments.get("ssh_key_id")
            remote = arguments.get("remote", "origin")

            if not repo_path_str:
                return [TextContent(type="text", text="Error: repo_path is required")]

            repo_path = Path(repo_path_str)
            if not _validate_path(str(repo_path)):
                return [TextContent(type="text", text=f"Error: Path not allowed: {repo_path}")]

            success, message = git_clone_service.fetch(
                repo_path=repo_path,
                agent_name=agent,
                key_id=ssh_key_id,
                remote=remote
            )

            return [TextContent(type="text", text=json.dumps({
                "success": success,
                "message": message
            }, ensure_ascii=False))]

        elif name == "git_branch":
            repo_path_str = arguments.get("repo_path", "")
            if not repo_path_str:
                return [TextContent(type="text", text="Error: repo_path is required")]

            repo_path = Path(repo_path_str)
            if not _validate_path(str(repo_path)):
                return [TextContent(type="text", text=f"Error: Path not allowed: {repo_path}")]

            branch = git_clone_service.get_current_branch(repo_path)
            return [TextContent(type="text", text=json.dumps({
                "branch": branch
            }, ensure_ascii=False))]

        elif name == "git_list_branches":
            repo_path_str = arguments.get("repo_path", "")
            remote = arguments.get("remote", False)

            if not repo_path_str:
                return [TextContent(type="text", text="Error: repo_path is required")]

            repo_path = Path(repo_path_str)
            if not _validate_path(str(repo_path)):
                return [TextContent(type="text", text=f"Error: Path not allowed: {repo_path}")]

            branches = git_clone_service.list_branches(repo_path, remote=remote)
            return [TextContent(type="text", text=json.dumps({
                "branches": branches
            }, ensure_ascii=False))]

        elif name == "git_status":
            repo_path_str = arguments.get("repo_path", "")
            if not repo_path_str:
                return [TextContent(type="text", text="Error: repo_path is required")]

            repo_path = Path(repo_path_str)
            if not _validate_path(str(repo_path)):
                return [TextContent(type="text", text=f"Error: Path not allowed: {repo_path}")]

            status = git_clone_service.get_status(repo_path)
            return [TextContent(type="text", text=json.dumps({
                "status": status
            }, ensure_ascii=False))]

        elif name == "git_diff":
            repo_path_str = arguments.get("repo_path", "")
            target = arguments.get("target", "HEAD")
            base = arguments.get("base")

            if not repo_path_str:
                return [TextContent(type="text", text="Error: repo_path is required")]

            repo_path = Path(repo_path_str)
            if not _validate_path(str(repo_path)):
                return [TextContent(type="text", text=f"Error: Path not allowed: {repo_path}")]

            diff = git_clone_service.get_diff(repo_path, target, base)
            return [TextContent(type="text", text=diff)]

        elif name == "git_log":
            repo_path_str = arguments.get("repo_path", "")
            limit = arguments.get("limit", 50)
            branch = arguments.get("branch")

            if not repo_path_str:
                return [TextContent(type="text", text="Error: repo_path is required")]

            repo_path = Path(repo_path_str)
            if not _validate_path(str(repo_path)):
                return [TextContent(type="text", text=f"Error: Path not allowed: {repo_path}")]

            log = git_clone_service.get_log(repo_path, limit=limit, branch=branch)
            return [TextContent(type="text", text=json.dumps(log, ensure_ascii=False, indent=2))]

        elif name == "git_show":
            repo_path_str = arguments.get("repo_path", "")
            commit = arguments.get("commit", "")
            file_path = arguments.get("file_path")

            if not repo_path_str or not commit:
                return [TextContent(type="text", text="Error: repo_path and commit are required")]

            repo_path = Path(repo_path_str)
            if not _validate_path(str(repo_path)):
                return [TextContent(type="text", text=f"Error: Path not allowed: {repo_path}")]

            if file_path:
                content = git_clone_service.show_file_at_commit(repo_path, commit, file_path)
                return [TextContent(type="text", text=content)]
            else:
                info = git_clone_service.get_commit_info(repo_path, commit)
                diff = git_clone_service.get_commit_diff(repo_path, commit)
                return [TextContent(type="text", text=json.dumps({
                    "info": info,
                    "diff": diff
                }, ensure_ascii=False, indent=2))]

        elif name == "git_checkout":
            repo_path_str = arguments.get("repo_path", "")
            branch = arguments.get("branch", "")

            if not repo_path_str or not branch:
                return [TextContent(type="text", text="Error: repo_path and branch are required")]

            repo_path = Path(repo_path_str)
            if not _validate_path(str(repo_path)):
                return [TextContent(type="text", text=f"Error: Path not allowed: {repo_path}")]

            success, message = git_clone_service.checkout_branch(repo_path, branch)
            return [TextContent(type="text", text=json.dumps({
                "success": success,
                "message": message
            }, ensure_ascii=False))]

        elif name == "git_remote_url":
            repo_path_str = arguments.get("repo_path", "")
            if not repo_path_str:
                return [TextContent(type="text", text="Error: repo_path is required")]

            repo_path = Path(repo_path_str)
            if not _validate_path(str(repo_path)):
                return [TextContent(type="text", text=f"Error: Path not allowed: {repo_path}")]

            url = git_clone_service.get_remote_url(repo_path)
            return [TextContent(type="text", text=json.dumps({
                "url": url
            }, ensure_ascii=False))]

        elif name == "git_current_commit":
            repo_path_str = arguments.get("repo_path", "")
            if not repo_path_str:
                return [TextContent(type="text", text="Error: repo_path is required")]

            repo_path = Path(repo_path_str)
            if not _validate_path(str(repo_path)):
                return [TextContent(type="text", text=f"Error: Path not allowed: {repo_path}")]

            commit = git_clone_service.get_current_commit(repo_path)
            return [TextContent(type="text", text=json.dumps({
                "commit": commit
            }, ensure_ascii=False))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        import traceback
        return [TextContent(type="text", text=f"Error: {str(e)}\n{traceback.format_exc()}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
