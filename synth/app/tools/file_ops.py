import shutil
from pathlib import Path
from typing import Any

from app.mcp import MCPTool


TOOLS_FILE_OPS = [
    MCPTool(
        name="write_file",
        description="Create or overwrite a file with content. Use for creating new files or completely replacing existing file content.",
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
        description="Edit a specific section of a file by replacing old text with new text. Use when you need to change part of a file without replacing everything.",
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file to edit"
                },
                "old_string": {
                    "type": "string",
                    "description": "The exact text to find and replace. Must be a unique substring in the file."
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
        description="Create a new directory. Can also create parent directories if they don't exist (recursive).",
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
        description="Delete a file. Cannot delete directories - use delete_directory for that.",
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
        description="Delete a directory and all its contents recursively.",
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
]


async def builtin_write_file(args: dict[str, Any]) -> str:
    """Create or overwrite a file with content."""
    file_path = args.get("file_path")
    content = args.get("content", "")

    if not file_path:
        return "Error: file_path is required"

    path = Path(file_path)

    if path.exists() and path.is_dir():
        return f"Error: Path is a directory: {file_path}"

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)

        line_count = len(content.splitlines())
        return f"Successfully wrote to {file_path}\nLines: {line_count}\nSize: {len(content)} bytes"
    except PermissionError:
        return f"Error: Permission denied: {file_path}"
    except Exception as e:
        return f"Error writing file: {str(e)}"


async def builtin_edit_file(args: dict[str, Any]) -> str:
    """Edit a file by replacing old_string with new_string."""
    file_path = args.get("file_path")
    old_string = args.get("old_string")
    new_string = args.get("new_string", "")

    if not file_path:
        return "Error: file_path is required"
    if old_string is None:
        return "Error: old_string is required"

    path = Path(file_path)

    if not path.exists():
        return f"Error: File not found: {file_path}"

    if not path.is_file():
        return f"Error: Not a file: {file_path}"

    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        return f"Error: Cannot read binary file: {file_path}"
    except Exception as e:
        return f"Error reading file: {str(e)}"

    if old_string not in content:
        return "Error: old_string not found in file. Make sure the exact text exists in the file."

    new_content = content.replace(old_string, new_string, 1)

    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        old_lines = len(content.splitlines())
        new_lines = len(new_content.splitlines())
        return f"Successfully edited {file_path}\nReplaced 1 occurrence\nOld lines: {old_lines}, New lines: {new_lines}"
    except PermissionError:
        return f"Error: Permission denied: {file_path}"
    except Exception as e:
        return f"Error writing file: {str(e)}"


async def builtin_create_directory(args: dict[str, Any]) -> str:
    """Create a directory."""
    path = args.get("path")

    if not path:
        return "Error: path is required"

    dir_path = Path(path)

    if dir_path.exists():
        if dir_path.is_dir():
            return f"Directory already exists: {path}"
        else:
            return f"Error: Path exists but is not a directory: {path}"

    recursive = args.get("recursive", True)

    try:
        if recursive:
            dir_path.mkdir(parents=True, exist_ok=True)
        else:
            dir_path.mkdir(parents=False, exist_ok=False)
        return f"Successfully created directory: {path}"
    except PermissionError:
        return f"Error: Permission denied: {path}"
    except FileExistsError:
        return f"Error: Directory already exists: {path}"
    except Exception as e:
        return f"Error creating directory: {str(e)}"


async def builtin_delete_file(args: dict[str, Any]) -> str:
    """Delete a file."""
    file_path = args.get("file_path")

    if not file_path:
        return "Error: file_path is required"

    path = Path(file_path)

    if not path.exists():
        return f"Error: File not found: {file_path}"

    if not path.is_file():
        return f"Error: Not a file (use delete_directory for directories): {file_path}"

    try:
        path.unlink()
        return f"Successfully deleted file: {file_path}"
    except PermissionError:
        return f"Error: Permission denied: {file_path}"
    except Exception as e:
        return f"Error deleting file: {str(e)}"


async def builtin_delete_directory(args: dict[str, Any]) -> str:
    """Delete a directory and its contents."""
    path = args.get("path")

    if not path:
        return "Error: path is required"

    dir_path = Path(path)

    if not dir_path.exists():
        return f"Error: Directory not found: {path}"

    if not dir_path.is_dir():
        return f"Error: Not a directory: {path}"

    recursive = args.get("recursive", True)

    if not recursive:
        try:
            dir_path.rmdir()
            return f"Successfully deleted empty directory: {path}"
        except OSError:
            return "Error: Directory not empty. Use recursive=true to delete recursively."

    try:
        shutil.rmtree(dir_path)
        return f"Successfully deleted directory and contents: {path}"
    except PermissionError:
        return f"Error: Permission denied: {path}"
    except Exception as e:
        return f"Error deleting directory: {str(e)}"