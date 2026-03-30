import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent


class GitMCPConfig:
    def __init__(self, config_path: Path | None = None):
        self._config: dict[str, Any] = {}
        self._load_config(config_path)

    def _load_config(self, config_path: Path | None = None) -> None:
        if config_path is None:
            env_path = os.environ.get("SYNTH_MCP_GIT_CONFIG")
            if env_path:
                config_path = Path(env_path)
            else:
                server_dir = Path(__file__).parent
                config_path = server_dir / "config.yaml"
                if not config_path.exists():
                    synth_dir = server_dir.parent / "synth"
                    config_path = synth_dir / "config.yaml"

        if config_path and config_path.exists():
            with open(config_path, "r") as f:
                self._config = yaml.safe_load(f) or {}
        else:
            self._config = {}

    @property
    def allowed_dirs(self) -> list[str]:
        return self._config.get("mcp", {}).get("servers", {}).get("git", {}).get(
            "env", {}
        ).get("ALLOWED_DIRS", "/home").split(":")

    @property
    def default_repo_path(self) -> str | None:
        return os.environ.get("GIT_REPO_PATH")


git_config = GitMCPConfig()


def is_path_allowed(path: str) -> bool:
    """Check if path is within allowed directories."""
    try:
        abs_path = Path(path).resolve()
        for allowed_dir in git_config.allowed_dirs:
            allowed_resolved = Path(allowed_dir).resolve()
            if str(abs_path).startswith(str(allowed_resolved)):
                return True
        return False
    except Exception:
        return False


def run_git_command(args: list[str], repo_path: str | None = None) -> dict[str, Any]:
    """Run a git command and return the result."""
    if repo_path is None:
        repo_path = git_config.default_repo_path or os.getcwd()
    
    if not os.path.exists(repo_path):
        return {
            "success": False,
            "error": f"Repository path does not exist: {repo_path}"
        }
    
    if not is_path_allowed(repo_path):
        return {
            "success": False,
            "error": f"Path not allowed: {repo_path}"
        }
    
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Command timed out after 30 seconds"
        }
    except FileNotFoundError:
        return {
            "success": False,
            "error": "Git command not found. Is git installed?"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


app = Server("synth-mcp-git")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="git_branch",
            description="Get the current git branch name",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                        "description": "Path to the git repository (optional, defaults to GIT_REPO_PATH env or current directory)"
                    }
                }
            }
        ),
        Tool(
            name="git_files",
            description="List all files in the git repository (tracked and untracked)",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                        "description": "Path to the git repository (optional)"
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Filter files by pattern (e.g., '*.py', 'src/*')"
                    },
                    "include_untracked": {
                        "type": "boolean",
                        "default": True,
                        "description": "Include untracked files"
                    }
                }
            }
        ),
        Tool(
            name="git_diff",
            description="Get git diff of changes (staged, unstaged, or between commits)",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                        "description": "Path to the git repository (optional)"
                    },
                    "staged": {
                        "type": "boolean",
                        "default": False,
                        "description": "Show staged changes"
                    },
                    "file": {
                        "type": "string",
                        "description": "Show diff for specific file"
                    },
                    "stat": {
                        "type": "boolean",
                        "default": False,
                        "description": "Show diff statistics only"
                    },
                    "from_commit": {
                        "type": "string",
                        "description": "Start commit for range diff"
                    },
                    "to_commit": {
                        "type": "string",
                        "description": "End commit for range diff (defaults to HEAD)"
                    }
                }
            }
        ),
        Tool(
            name="git_status",
            description="Get git status of the repository",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                        "description": "Path to the git repository (optional)"
                    },
                    "short": {
                        "type": "boolean",
                        "default": False,
                        "description": "Use short format"
                    }
                }
            }
        ),
        Tool(
            name="git_log",
            description="Get git commit history",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                        "description": "Path to the git repository (optional)"
                    },
                    "max_count": {
                        "type": "integer",
                        "default": 10,
                        "description": "Maximum number of commits to show"
                    },
                    "format": {
                        "type": "string",
                        "default": "%h %s",
                        "description": "Log format string"
                    }
                }
            }
        ),
        Tool(
            name="git_show",
            description="Show detailed information about a file at a specific commit",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                        "description": "Path to the git repository (optional)"
                    },
                    "object": {
                        "type": "string",
                        "description": "Commit, branch, or file reference"
                    },
                    "file": {
                        "type": "string",
                        "description": "Show specific file at the given commit"
                    }
                },
                "required": ["object"]
            }
        ),
        Tool(
            name="git_list_branches",
            description="List all git branches",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                        "description": "Path to the git repository (optional)"
                    },
                    "all": {
                        "type": "boolean",
                        "default": False,
                        "description": "List both local and remote branches"
                    }
                }
            }
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        repo_path = arguments.get("repo_path")
        
        if name == "git_branch":
            result = run_git_command(["branch", "--show-current"], repo_path)
            if result["success"]:
                return [TextContent(type="text", text=result["stdout"])]
            return [TextContent(type="text", text=f"Error: {result.get('error', result.get('stderr', 'Unknown error'))}")]
        
        elif name == "git_files":
            pattern = arguments.get("pattern")
            include_untracked = arguments.get("include_untracked", True)
            
            files = []
            
            # Get tracked files
            tracked_result = run_git_command(["ls-files"], repo_path)
            if tracked_result["success"]:
                tracked_files = tracked_result["stdout"].split("\n")
                if pattern:
                    import fnmatch
                    tracked_files = [f for f in tracked_files if fnmatch.fnmatch(f, pattern)]
                files.extend([{"path": f, "status": "tracked"} for f in tracked_files if f])
            
            # Get untracked files
            if include_untracked:
                untracked_result = run_git_command(["ls-files", "--others", "--exclude-standard"], repo_path)
                if untracked_result["success"]:
                    untracked_files = untracked_result["stdout"].split("\n")
                    if pattern:
                        import fnmatch
                        untracked_files = [f for f in untracked_files if fnmatch.fnmatch(f, pattern)]
                    files.extend([{"path": f, "status": "untracked"} for f in untracked_files if f])
            
            return [TextContent(type="text", text=json.dumps(files, ensure_ascii=False, indent=2))]
        
        elif name == "git_diff":
            staged = arguments.get("staged", False)
            file = arguments.get("file")
            stat = arguments.get("stat", False)
            from_commit = arguments.get("from_commit")
            to_commit = arguments.get("to_commit", "HEAD")
            
            args = ["diff"]
            if staged:
                args.append("--cached")
            if stat:
                args.append("--stat")
            if from_commit:
                args.append(f"{from_commit}..{to_commit}")
            if file:
                args.append("--")
                args.append(file)
            
            result = run_git_command(args, repo_path)
            if result["success"]:
                output = result["stdout"]
                if not output:
                    output = "No changes"
                return [TextContent(type="text", text=output)]
            return [TextContent(type="text", text=f"Error: {result.get('error', result.get('stderr', 'Unknown error'))}")]
        
        elif name == "git_status":
            short = arguments.get("short", False)
            args = ["status"]
            if short:
                args.append("--short")
            
            result = run_git_command(args, repo_path)
            if result["success"]:
                return [TextContent(type="text", text=result["stdout"])]
            return [TextContent(type="text", text=f"Error: {result.get('error', result.get('stderr', 'Unknown error'))}")]
        
        elif name == "git_log":
            max_count = arguments.get("max_count", 10)
            log_format = arguments.get("format", "%h %s")
            
            result = run_git_command(
                ["log", f"--max-count={max_count}", f"--format={log_format}"],
                repo_path
            )
            if result["success"]:
                return [TextContent(type="text", text=result["stdout"])]
            return [TextContent(type="text", text=f"Error: {result.get('error', result.get('stderr', 'Unknown error'))}")]
        
        elif name == "git_show":
            obj = arguments.get("object")
            file = arguments.get("file")
            
            if not obj:
                return [TextContent(type="text", text="Error: object is required")]
            
            args = ["show"]
            if file:
                args.append(f"{obj}:{file}")
            else:
                args.append(obj)
            
            result = run_git_command(args, repo_path)
            if result["success"]:
                return [TextContent(type="text", text=result["stdout"])]
            return [TextContent(type="text", text=f"Error: {result.get('error', result.get('stderr', 'Unknown error'))}")]
        
        elif name == "git_list_branches":
            all_branches = arguments.get("all", False)
            
            args = ["branch"]
            if all_branches:
                args.append("-a")
            
            result = run_git_command(args, repo_path)
            if result["success"]:
                branches = result["stdout"].split("\n")
                return [TextContent(type="text", text=json.dumps(branches, ensure_ascii=False, indent=2))]
            return [TextContent(type="text", text=f"Error: {result.get('error', result.get('stderr', 'Unknown error'))}")]
        
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
    
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


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
