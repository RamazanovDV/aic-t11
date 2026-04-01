from typing import Any

from app.mcp import MCPTool
from app.project_manager import project_manager
from app.git_repo_manager import git_repo_manager


TOOLS_PROJECT = [
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
]


async def builtin_get_current_project(args: dict[str, Any], session: Any = None) -> str:
    """Get current project info from session."""
    project_name = None
    
    if session and hasattr(session, 'status'):
        project_name = session.status.get("project")
    
    if not project_name:
        return "Error: No project selected in session. Set 'project' in session status."
    
    if not project_manager.project_exists(project_name):
        return f"Error: Project '{project_name}' not found"
    
    project_info = project_manager.get_project_info(project_name)
    repos = git_repo_manager.list_repos(project_name)
    
    parts = [f"# Project: {project_name}"]
    parts.append(f"\n**Path:** {project_info.get('path', 'N/A')}")
    parts.append(f"\n**Repositories:** {len(repos)}")
    
    if repos:
        parts.append("\n\n## Repositories:")
        for repo in repos:
            parts.append(f"\n- **{repo.name}**")
            parts.append(f"  - URL: {repo.url or 'N/A'}")
            parts.append(f"  - Local: {repo.local_path or 'N/A'}")
            parts.append(f"  - Branch: {repo.branch or 'N/A'}")
            parts.append(f"  - Status: {repo.status or 'N/A'}")
    
    indexes = project_info.get('embeddings_indexes', [])
    if indexes:
        parts.append(f"\n**Embeddings Indexes:** {len(indexes)}")
    
    return "".join(parts)


async def builtin_list_project_repos(args: dict[str, Any], session: Any = None) -> str:
    """List repositories in a project."""
    project_name = args.get("project_name")
    
    if not project_name and session and hasattr(session, 'status'):
        project_name = session.status.get("project")
    
    if not project_name:
        return "Error: project_name is required or project must be set in session"
    
    if not project_manager.project_exists(project_name):
        return f"Error: Project '{project_name}' not found"
    
    repos = git_repo_manager.list_repos(project_name)
    
    if not repos:
        return f"No repositories connected to project '{project_name}'"
    
    parts = [f"# Repositories in {project_name}:\n"]
    for repo in repos:
        parts.append(f"\n## {repo.name}")
        parts.append(f"\n- **URL:** {repo.url or 'N/A'}")
        parts.append(f"\n- **Local Path:** {repo.local_path or 'N/A'}")
        parts.append(f"\n- **Branch:** {repo.branch or 'N/A'}")
        parts.append(f"\n- **Status:** {repo.status or 'N/A'}")
        parts.append(f"\n- **Last Fetch:** {repo.last_fetch or 'N/A'}")
    
    return "".join(parts)


async def builtin_get_repo_info(args: dict[str, Any], session: Any = None) -> str:
    """Get detailed info about a specific repository."""
    repo_name = args.get("repo_name")
    project_name = args.get("project_name")
    
    if not project_name and session and hasattr(session, 'status'):
        project_name = session.status.get("project")
    
    if not repo_name:
        return "Error: repo_name is required"
    
    if not project_name:
        return "Error: project_name is required or project must be set in session"
    
    if not project_manager.project_exists(project_name):
        return f"Error: Project '{project_name}' not found"
    
    success, message, repo_info = git_repo_manager.get_repo_info(project_name, repo_name)
    
    if not success:
        return f"Error: {message}"
    
    parts = [f"# Repository: {repo_name}\n"]
    parts.append(f"\n**Project:** {project_name}")
    parts.append(f"\n- **URL:** {repo_info.get('url', 'N/A')}")
    parts.append(f"\n- **Local Path:** {repo_info.get('local_path', 'N/A')}")
    parts.append(f"\n- **Branch:** {repo_info.get('branch', 'N/A')}")
    parts.append(f"\n- **Type:** {repo_info.get('repo_type', 'N/A')}")
    parts.append(f"\n- **Status:** {repo_info.get('status', 'N/A')}")
    parts.append(f"\n- **Current Commit:** {repo_info.get('current_commit', 'N/A')}")
    parts.append(f"\n- **Last Fetch:** {repo_info.get('last_fetch', 'N/A')}")
    parts.append(f"\n- **Auto Index:** {repo_info.get('auto_index', 'N/A')}")
    if repo_info.get('required_agent'):
        parts.append(f"\n- **Required Agent:** {repo_info.get('required_agent')}")
    if repo_info.get('branches'):
        parts.append(f"\n- **Branches:** {', '.join(repo_info.get('branches', []))}")
    
    return "".join(parts)
