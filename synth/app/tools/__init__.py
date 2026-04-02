from app.tools.code_review import builtin_code_review, TOOL_CODE_REVIEW
from app.tools.project import (
    builtin_get_current_project,
    builtin_list_project_repos,
    builtin_get_repo_info,
    TOOLS_PROJECT,
)
from app.tools.filesystem import (
    builtin_read_file,
    builtin_list_directory,
    builtin_grep_files,
    TOOLS_FILESYSTEM,
)
from app.tools.file_ops import (
    builtin_write_file,
    builtin_edit_file,
    builtin_create_directory,
    builtin_delete_file,
    builtin_delete_directory,
    TOOLS_FILE_OPS,
)

ALL_BUILTIN_TOOLS = [
    TOOL_CODE_REVIEW,
    *TOOLS_PROJECT,
    *TOOLS_FILESYSTEM,
    *TOOLS_FILE_OPS,
]

__all__ = [
    "builtin_code_review",
    "TOOL_CODE_REVIEW",
    "builtin_get_current_project",
    "builtin_list_project_repos",
    "builtin_get_repo_info",
    "TOOLS_PROJECT",
    "builtin_read_file",
    "builtin_list_directory",
    "builtin_grep_files",
    "TOOLS_FILESYSTEM",
    "builtin_write_file",
    "builtin_edit_file",
    "builtin_create_directory",
    "builtin_delete_file",
    "builtin_delete_directory",
    "TOOLS_FILE_OPS",
    "ALL_BUILTIN_TOOLS",
]
