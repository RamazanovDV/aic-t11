import re
from pathlib import Path
from typing import Any

from app.mcp import MCPTool


TOOLS_FILESYSTEM = [
    MCPTool(
        name="read_file",
        description="Read contents of a file. Returns file content with optional offset and limit for large files.",
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
        description="List files and directories at a given path. Can recurse into subdirectories with optional depth limit.",
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
        description="Search for text pattern in files. Supports regex patterns and optional file glob filter.",
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
]


async def builtin_read_file(args: dict[str, Any]) -> str:
    """Read file contents."""
    file_path = args.get("file_path")
    
    if not file_path:
        return "Error: file_path is required"
    
    path = Path(file_path)
    
    if not path.exists():
        return f"Error: File not found: {file_path}"
    
    if not path.is_file():
        return f"Error: Not a file: {file_path}"
    
    offset = args.get("offset", 0)
    limit = args.get("limit", 500)
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        total_lines = len(lines)
        
        if offset >= total_lines:
            return f"Error: Offset {offset} is beyond file length ({total_lines} lines)"
        
        selected_lines = lines[offset:offset + limit]
        content = ''.join(selected_lines)
        
        result = f"# File: {file_path}\n"
        result += f"# Lines: {total_lines} (showing {offset}-{min(offset + limit, total_lines)})\n\n"
        result += content
        
        if offset + limit < total_lines:
            result += f"\n... ({total_lines - offset - limit} more lines)"
        
        return result
    
    except UnicodeDecodeError:
        return f"Error: Cannot read binary file: {file_path}"
    except Exception as e:
        return f"Error reading file: {str(e)}"


async def builtin_list_directory(args: dict[str, Any]) -> str:
    """List directory contents."""
    path = args.get("path")
    
    if not path:
        return "Error: path is required"
    
    dir_path = Path(path)
    
    if not dir_path.exists():
        return f"Error: Directory not found: {path}"
    
    if not dir_path.is_dir():
        return f"Error: Not a directory: {path}"
    
    recursive = args.get("recursive", False)
    max_depth = args.get("max_depth", 3)
    include_hidden = args.get("include_hidden", False)
    
    def format_tree(dir_path: Path, prefix: str = "", depth: int = 0) -> list[str]:
        if depth > max_depth:
            return []
        
        try:
            entries = sorted(dir_path.iterdir(), key=lambda e: (not e.is_dir(), e.name))
        except PermissionError:
            return [f"{prefix}[Permission denied]"]
        
        lines = []
        dirs = []
        files = []
        
        for entry in entries:
            if not include_hidden and entry.name.startswith('.'):
                continue
            
            if entry.is_dir():
                dirs.append(entry)
            else:
                files.append(entry)
        
        all_entries = [(d, True) for d in dirs] + [(f, False) for f in files]
        
        for i, (entry, is_dir) in enumerate(all_entries):
            is_last = i == len(all_entries) - 1
            current_prefix = "└── " if is_last else "├── "
            next_prefix = "    " if is_last else "│   "
            
            if is_dir:
                lines.append(f"{prefix}{current_prefix}{entry.name}/")
                if recursive:
                    lines.extend(format_tree(entry, prefix + next_prefix, depth + 1))
            else:
                size = entry.stat().st_size if not entry.is_symlink() else 0
                size_str = f" ({size} bytes)" if size > 0 else ""
                lines.append(f"{prefix}{current_prefix}{entry.name}{size_str}")
        
        return lines
    
    result = f"# Directory: {path}\n\n"
    
    try:
        entries = list(dir_path.iterdir())
        if not include_hidden:
            entries = [e for e in entries if not e.name.startswith('.')]
        total = len(entries)
    except PermissionError:
        return result + "[Permission denied]"
    
    result += f"# Total: {total} entries\n\n"
    result += ".\n"
    result += "\n".join(format_tree(dir_path))
    
    return result


async def builtin_grep_files(args: dict[str, Any]) -> str:
    """Search for pattern in files."""
    path = args.get("path")
    pattern = args.get("pattern")
    
    if not path or not pattern:
        return "Error: both path and pattern are required"
    
    dir_path = Path(path)
    
    if not dir_path.exists():
        return f"Error: Directory not found: {path}"
    
    file_glob = args.get("file_glob", "*")
    case_sensitive = args.get("case_sensitive", False)
    max_results = args.get("max_results", 100)
    
    try:
        flags = 0 if case_sensitive else re.IGNORECASE
        regex = re.compile(pattern, flags)
    except re.error as e:
        return f"Error: Invalid regex pattern: {e}"
    
    matches = []
    
    def search_in_file(file_path: Path) -> list[str]:
        file_matches = []
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for i, line in enumerate(f, 1):
                    if regex.search(line):
                        escaped_line = line.rstrip().replace('`', '\\`')
                        file_matches.append(f"  {i}: {escaped_line}")
                        if len(file_matches) >= max_results:
                            return file_matches
        except Exception:
            pass
        return file_matches
    
    def walk_directory(current_path: Path, depth: int = 0) -> None:
        if depth > 10:
            return
        
        try:
            for entry in sorted(current_path.iterdir()):
                if entry.name.startswith('.'):
                    continue
                
                if entry.is_dir() and not entry.is_symlink():
                    walk_directory(entry, depth + 1)
                elif entry.is_file():
                    if file_glob == "*" or entry.match(file_glob):
                        file_matches = search_in_file(entry)
                        if file_matches:
                            matches.append((entry, file_matches))
                            if len(matches) >= max_results:
                                return
        except PermissionError:
            pass
    
    walk_directory(dir_path)
    
    if not matches:
        return f"# Search: {pattern}\n# In: {path}\n# Glob: {file_glob}\n\nNo matches found."
    
    result = f"# Search: {pattern}\n"
    result += f"# In: {path}\n"
    result += f"# Glob: {file_glob}\n"
    result += f"# Files with matches: {len(matches)}\n\n"
    
    for file_path, file_matches in matches:
        result += f"## {file_path}\n"
        result += "\n".join(file_matches)
        result += "\n\n"
    
    return result
