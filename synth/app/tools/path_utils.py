from pathlib import Path
from typing import Any

from app.config import config


class PathSecurityError(Exception):
    pass


def get_project_repos_path(project_name: str) -> Path:
    """Get the repos directory for a project."""
    return config.data_dir / "projects" / project_name / "repos"


def validate_path(
    requested_path: str | None,
    project_name: str,
    base_path: Path | None = None,
    require_file: bool = False,
    require_dir: bool = False
) -> Path:
    """
    Validate that requested_path is within the project's repos directory.
    
    Args:
        requested_path: The path to validate (relative or absolute within project)
        project_name: The current project name
        base_path: Base directory to validate against (defaults to project/repos)
        require_file: If True, path must be a file
        require_dir: If True, path must be a directory
        
    Returns:
        Validated Path object
        
    Raises:
        PathSecurityError: If validation fails
    """
    if not project_name:
        raise PathSecurityError("No active project in session")

    if base_path is None:
        base_path = get_project_repos_path(project_name)
    
    base_resolved = base_path.resolve()
    
    if not base_resolved.exists():
        raise PathSecurityError(f"Project directory does not exist: {base_resolved}")

    if requested_path:
        target = (base_path / requested_path).resolve()
        
        if not str(target).startswith(str(base_resolved)):
            raise PathSecurityError(
                f"Path '{requested_path}' is outside project directory"
            )
        
        if require_file and not target.is_file():
            raise PathSecurityError(f"Path '{requested_path}' is not a file")
        
        if require_dir and not target.is_dir():
            raise PathSecurityError(f"Path '{requested_path}' is not a directory")
        
        return target
    
    return base_resolved


def validate_file_path(file_path: str | None, project_name: str) -> Path:
    """Validate a file path within project repos directory."""
    return validate_path(file_path, project_name, require_file=True)


def validate_dir_path(dir_path: str | None, project_name: str) -> Path:
    """Validate a directory path within project repos directory."""
    return validate_path(dir_path, project_name, require_dir=True)


def validate_any_path(path: str | None, project_name: str) -> Path:
    """Validate any path within project repos directory."""
    return validate_path(path, project_name)


def build_result_header(path: Path, title: str | None = None) -> str:
    """Build a header string for tool results."""
    title_str = f" {title}" if title else ""
    return f"# {title_str}\n# Path: {path}\n\n"


def get_project_name_from_session(session: Any) -> str | None:
    """Extract project name from session status."""
    if session and hasattr(session, 'status'):
        return session.status.get("project")
    return None