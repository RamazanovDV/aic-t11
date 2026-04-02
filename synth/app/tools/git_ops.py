import subprocess
from pathlib import Path
from typing import Any

from app.mcp import MCPTool


TOOLS_GIT = [
    MCPTool(
        name="git_status",
        description="Show the working tree status. Returns modified, staged, and untracked files.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the git repository (default: current directory)"
                },
                "short": {
                    "type": "boolean",
                    "description": "Use short format output (default: true)",
                    "default": True
                }
            }
        }
    ),
    MCPTool(
        name="git_log",
        description="Show commit logs. Returns recent commits with hash, author, date, and message.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the git repository"
                },
                "max_count": {
                    "type": "integer",
                    "description": "Limit number of commits to show (default: 20)",
                    "default": 20
                },
                "oneline": {
                    "type": "boolean",
                    "description": "Show each commit on one line (default: true)",
                    "default": True
                },
                "author": {
                    "type": "string",
                    "description": "Filter commits by author name/email"
                },
                "since": {
                    "type": "string",
                    "description": "Show commits newer than date (e.g., '2024-01-01')"
                },
                "until": {
                    "type": "string",
                    "description": "Show commits older than date"
                },
                "grep": {
                    "type": "string",
                    "description": "Filter commits by commit message containing text"
                }
            }
        }
    ),
    MCPTool(
        name="git_diff",
        description="Show changes between commits, commit and working tree, etc. Returns diff output.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the git repository"
                },
                "target": {
                    "type": "string",
                    "description": "Target commit/branch (default: HEAD)"
                },
                "base": {
                    "type": "string",
                    "description": "Base commit/branch for comparison"
                },
                "file": {
                    "type": "string",
                    "description": "Show diff for specific file only"
                },
                "cached": {
                    "type": "boolean",
                    "description": "Show staged changes (diff --cached)"
                },
                "stat": {
                    "type": "boolean",
                    "description": "Show diffstat summary only (default: false)",
                    "default": False
                }
            }
        }
    ),
    MCPTool(
        name="git_branch_list",
        description="List all branches. Shows local and optionally remote branches.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the git repository"
                },
                "all": {
                    "type": "boolean",
                    "description": "Include remote branches (default: false)",
                    "default": False
                },
                "verbose": {
                    "type": "boolean",
                    "description": "Show last commit and tracking info (default: false)",
                    "default": False
                }
            }
        }
    ),
    MCPTool(
        name="git_show",
        description="Show various types of objects (commits, tags, trees, blobs).",
        input_schema={
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the git repository"
                },
                "object": {
                    "type": "string",
                    "description": "Object name (commit hash, tag, branch) - defaults to HEAD"
                },
                "stat": {
                    "type": "boolean",
                    "description": "Show diffstat (default: true)",
                    "default": True
                }
            }
        }
    ),
    MCPTool(
        name="git_blame",
        description="Show what revision and author last modified each line of a file.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the git repository"
                },
                "file": {
                    "type": "string",
                    "description": "Path to file to blame (relative to repo root)"
                },
                "max_count": {
                    "type": "integer",
                    "description": "Limit number of lines to show"
                },
                "L": {
                    "type": "string",
                    "description": "Line range to blame (e.g., '1,10')"
                }
            }
        }
    ),
    MCPTool(
        name="git_commit",
        description="Create a new commit with all staged changes. Returns commit hash and message.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the git repository"
                },
                "message": {
                    "type": "string",
                    "description": "Commit message (required)"
                },
                "allow_empty": {
                    "type": "boolean",
                    "description": "Allow creating empty commit (default: false)",
                    "default": False
                },
                "amend": {
                    "type": "boolean",
                    "description": "Amend the previous commit instead of creating new (default: false)",
                    "default": False
                }
            },
            "required": ["message"]
        }
    ),
    MCPTool(
        name="git_push",
        description="Push commits to remote repository.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the git repository"
                },
                "remote": {
                    "type": "string",
                    "description": "Remote name (default: origin)"
                },
                "branch": {
                    "type": "string",
                    "description": "Branch to push (default: current branch)"
                },
                "force": {
                    "type": "boolean",
                    "description": "Force push (dangerous!) (default: false)",
                    "default": False
                },
                "tags": {
                    "type": "boolean",
                    "description": "Push all tags (default: false)",
                    "default": False
                }
            }
        }
    ),
    MCPTool(
        name="git_pull",
        description="Fetch and integrate changes from remote repository.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the git repository"
                },
                "remote": {
                    "type": "string",
                    "description": "Remote name (default: origin)"
                },
                "branch": {
                    "type": "string",
                    "description": "Branch to pull (default: current branch)"
                },
                "rebase": {
                    "type": "boolean",
                    "description": "Rebase instead of merge (default: false)",
                    "default": False
                }
            }
        }
    ),
    MCPTool(
        name="git_checkout",
        description="Switch branches or restore working tree files.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the git repository"
                },
                "branch": {
                    "type": "string",
                    "description": "Branch to checkout"
                },
                "new_branch": {
                    "type": "string",
                    "description": "Create and checkout new branch"
                },
                "force": {
                    "type": "boolean",
                    "description": "Force checkout, discard local changes (dangerous!) (default: false)",
                    "default": False
                }
            },
            "required": ["branch"]
        }
    ),
    MCPTool(
        name="git_reset",
        description="Reset current HEAD to specified state. Can unstage files or change commit history.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the git repository"
                },
                "target": {
                    "type": "string",
                    "description": "Commit to reset to (default: HEAD)"
                },
                "mode": {
                    "type": "string",
                    "description": "Reset mode: soft, mixed, hard (default: mixed)",
                    "enum": ["soft", "mixed", "hard"],
                    "default": "mixed"
                },
                "file": {
                    "type": "string",
                    "description": "If provided, only unstaged file (like git reset HEAD <file>)"
                }
            }
        }
    ),
    MCPTool(
        name="git_rebase",
        description="Reapply commits on top of another base tip.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the git repository"
                },
                "base": {
                    "type": "string",
                    "description": "Base branch to rebase onto"
                },
                "continue": {
                    "type": "boolean",
                    "description": "Continue rebase after resolving conflicts",
                    "default": False
                },
                "abort": {
                    "type": "boolean",
                    "description": "Abort current rebase",
                    "default": False
                },
                "skip": {
                    "type": "boolean",
                    "description": "Skip current conflicting commit",
                    "default": False
                },
                "interactive": {
                    "type": "boolean",
                    "description": "Start interactive rebase (opens editor)",
                    "default": False
                }
            }
        }
    ),
    MCPTool(
        name="git_merge",
        description="Join two or more development histories together.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the git repository"
                },
                "branch": {
                    "type": "string",
                    "description": "Branch to merge into current branch"
                },
                "no_ff": {
                    "type": "boolean",
                    "description": "Create merge commit even if fast-forward (default: false)",
                    "default": False
                },
                "squash": {
                    "type": "boolean",
                    "description": "Squash commits into one (default: false)",
                    "default": False
            },
                "message": {
                    "type": "string",
                    "description": "Merge commit message"
                }
            },
            "required": ["branch"]
        }
    ),
    MCPTool(
        name="git_stash",
        description="Stash changes in working directory for later use.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the git repository"
                },
                "action": {
                    "type": "string",
                    "description": "Stash action: push, pop, list, show, drop, apply",
                    "enum": ["push", "pop", "list", "show", "drop", "apply"],
                    "default": "push"
                },
                "message": {
                    "type": "string",
                    "description": "Stash message (for push)"
                },
                "stash_index": {
                    "type": "integer",
                    "description": "Stash index (for pop, drop, apply)"
                },
                "include_untracked": {
                    "type": "boolean",
                    "description": "Include untracked files in stash (default: false)",
                    "default": False
                }
            }
        }
    ),
    MCPTool(
        name="git_cherry_pick",
        description="Apply changes introduced by some existing commits.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the git repository"
                },
                "commits": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Commit hashes to cherry-pick"
                },
                "no_commit": {
                    "type": "boolean",
                    "description": "Apply without creating commits (default: false)",
                    "default": False
                },
                "continue": {
                    "type": "boolean",
                    "description": "Continue cherry-pick after resolving conflicts",
                    "default": False
                },
                "abort": {
                    "type": "boolean",
                    "description": "Abort cherry-pick",
                    "default": False
                }
            },
            "required": ["commits"]
        }
    ),
    MCPTool(
        name="git_fetch",
        description="Download objects and refs from another repository.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the git repository"
                },
                "remote": {
                    "type": "string",
                    "description": "Remote to fetch from (default: all remotes)"
                },
                "all": {
                    "type": "boolean",
                    "description": "Fetch all remotes (default: false)",
                    "default": False
                },
                "prune": {
                    "type": "boolean",
                    "description": "Remove deleted remote refs (default: false)",
                    "default": False
                },
                "tags": {
                    "type": "boolean",
                    "description": "Fetch all tags (default: false)",
                    "default": False
                }
            }
        }
    ),
]


def _run_git(repo_path: str | None, args: list[str]) -> tuple[int, str, str]:
    cmd = ["git"] + args
    try:
        result = subprocess.run(
            cmd,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=60
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "Command timed out"
    except Exception as e:
        return 1, "", str(e)


def _get_repo_path(repo_path: str | None) -> str | None:
    if repo_path:
        p = Path(repo_path)
        if not p.exists() or not (p / ".git").exists():
            return None
        return str(p)
    return None


async def builtin_git_status(args: dict[str, Any]) -> str:
    repo_path = _get_repo_path(args.get("repo_path"))
    if repo_path is None:
        return "Error: Not a git repository"

    short = args.get("short", True)
    cmd = ["status"]
    if short:
        cmd.append("--short")

    code, stdout, stderr = _run_git(repo_path, cmd)
    if code != 0:
        return f"Error: {stderr}"
    return stdout or "Nothing to commit, working tree clean"


async def builtin_git_log(args: dict[str, Any]) -> str:
    repo_path = _get_repo_path(args.get("repo_path"))
    if repo_path is None:
        return "Error: Not a git repository"

    max_count = args.get("max_count", 20)
    oneline = args.get("oneline", True)
    author = args.get("author")
    since = args.get("since")
    until = args.get("until")
    grep = args.get("grep")

    cmd = ["log", f"--max-count={max_count}"]
    if oneline:
        cmd.append("--oneline")
    else:
        cmd.append("--pretty=format:%H%n%an%n%ae%n%at%n%s%n%b---END---")

    if author:
        cmd.extend(["--author", author])
    if since:
        cmd.extend(["--since", since])
    if until:
        cmd.extend(["--until", until])
    if grep:
        cmd.extend(["--grep", grep])

    code, stdout, stderr = _run_git(repo_path, cmd)
    if code != 0:
        return f"Error: {stderr}"
    return stdout or "No commits found"


async def builtin_git_diff(args: dict[str, Any]) -> str:
    repo_path = _get_repo_path(args.get("repo_path"))
    if repo_path is None:
        return "Error: Not a git repository"

    target = args.get("target", "HEAD")
    base = args.get("base")
    file = args.get("file")
    cached = args.get("cached", False)
    stat = args.get("stat", False)

    cmd = ["diff"]
    if stat:
        cmd.append("--stat")
    if cached:
        cmd.append("--cached")
    elif base:
        cmd.append(f"{base}...{target}" if "..." in f"{base}...{target}" else f"{base}..{target}")
    elif target:
        cmd.append(target)
    if file:
        cmd.append("--")
        cmd.append(file)

    code, stdout, stderr = _run_git(repo_path, cmd)
    if code != 0:
        return f"Error: {stderr}"
    return stdout or "No differences"


async def builtin_git_branch_list(args: dict[str, Any]) -> str:
    repo_path = _get_repo_path(args.get("repo_path"))
    if repo_path is None:
        return "Error: Not a git repository"

    all_branches = args.get("all", False)
    verbose = args.get("verbose", False)

    cmd = ["branch"]
    if all_branches:
        cmd.append("--all")
    if verbose:
        cmd.append("-v") if not all_branches else cmd.append("-vv")
    else:
        cmd.append("--format=%(refname:short)")

    code, stdout, stderr = _run_git(repo_path, cmd)
    if code != 0:
        return f"Error: {stderr}"

    if not verbose and not all_branches:
        current = _get_current_branch(repo_path)
        lines = stdout.strip().split("\n") if stdout.strip() else []
        result = []
        for line in lines:
            if line == current:
                result.append(f"* {line}")
            else:
                result.append(f"  {line}")
        return "\n".join(result) if result else "No branches"

    return stdout or "No branches"


def _get_current_branch(repo_path: str) -> str:
    code, stdout, _ = _run_git(repo_path, ["branch", "--show-current"])
    return stdout.strip() if code == 0 else ""


async def builtin_git_show(args: dict[str, Any]) -> str:
    repo_path = _get_repo_path(args.get("repo_path"))
    if repo_path is None:
        return "Error: Not a git repository"

    obj = args.get("object", "HEAD")
    stat = args.get("stat", True)

    cmd = ["show"]
    if stat:
        cmd.append("--stat")
    cmd.append(obj)

    code, stdout, stderr = _run_git(repo_path, cmd)
    if code != 0:
        return f"Error: {stderr}"
    return stdout or "Object not found"


async def builtin_git_blame(args: dict[str, Any]) -> str:
    repo_path = _get_repo_path(args.get("repo_path"))
    if repo_path is None:
        return "Error: Not a git repository"

    file = args.get("file")
    if not file:
        return "Error: file is required"
    max_count = args.get("max_count")
    L = args.get("L")

    cmd = ["blame"]
    if max_count:
        cmd.extend(["--max-count", str(max_count)])
    if L:
        cmd.extend(["-L", L])
    cmd.append("--")
    cmd.append(file)

    code, stdout, stderr = _run_git(repo_path, cmd)
    if code != 0:
        return f"Error: {stderr}"
    return stdout or "No blame information"


async def builtin_git_commit(args: dict[str, Any]) -> str:
    repo_path = _get_repo_path(args.get("repo_path"))
    if repo_path is None:
        return "Error: Not a git repository"

    message = args.get("message")
    if not message:
        return "Error: commit message is required"
    allow_empty = args.get("allow_empty", False)
    amend = args.get("amend", False)

    cmd = ["commit"]
    if allow_empty:
        cmd.append("--allow-empty")
    if amend:
        cmd.append("--amend")
    cmd.extend(["-m", message])

    code, stdout, stderr = _run_git(repo_path, cmd)
    if code != 0:
        return f"Error: {stderr}"
    return stdout or "Commit created successfully"


async def builtin_git_push(args: dict[str, Any]) -> str:
    repo_path = _get_repo_path(args.get("repo_path"))
    if repo_path is None:
        return "Error: Not a git repository"

    remote = args.get("remote", "origin")
    branch = args.get("branch")
    force = args.get("force", False)
    tags = args.get("tags", False)

    cmd = ["push"]
    if force:
        cmd.append("--force")
    if tags:
        cmd.append("--tags")
    if branch:
        cmd.extend([remote, branch])
    else:
        cmd.append(remote)

    code, stdout, stderr = _run_git(repo_path, cmd)
    if code != 0:
        return f"Error: {stderr}"
    return stdout or "Push completed successfully"


async def builtin_git_pull(args: dict[str, Any]) -> str:
    repo_path = _get_repo_path(args.get("repo_path"))
    if repo_path is None:
        return "Error: Not a git repository"

    remote = args.get("remote", "origin")
    branch = args.get("branch")
    rebase = args.get("rebase", False)

    cmd = ["pull"]
    if rebase:
        cmd.append("--rebase")
    cmd.append(remote)
    if branch:
        cmd.append(branch)

    code, stdout, stderr = _run_git(repo_path, cmd)
    if code != 0:
        return f"Error: {stderr}"
    return stdout or "Pull completed successfully"


async def builtin_git_checkout(args: dict[str, Any]) -> str:
    repo_path = _get_repo_path(args.get("repo_path"))
    if repo_path is None:
        return "Error: Not a git repository"

    branch = args.get("branch")
    new_branch = args.get("new_branch")
    force = args.get("force", False)

    if not branch and not new_branch:
        return "Error: branch or new_branch is required"

    cmd = ["checkout"]
    if force:
        cmd.append("--force")
    if new_branch:
        cmd.extend(["-b", new_branch])
        if branch:
            cmd.append(branch)
    else:
        cmd.append(branch)

    code, stdout, stderr = _run_git(repo_path, cmd)
    if code != 0:
        return f"Error: {stderr}"
    return stdout or f"Switched to branch: {new_branch or branch}"


async def builtin_git_reset(args: dict[str, Any]) -> str:
    repo_path = _get_repo_path(args.get("repo_path"))
    if repo_path is None:
        return "Error: Not a git repository"

    target = args.get("target", "HEAD")
    mode = args.get("mode", "mixed")
    file = args.get("file")

    cmd = ["reset"]
    if mode:
        cmd.append(f"--{mode}")
    if file:
        cmd.append("--")
        cmd.append(file)
    elif target:
        cmd.append(target)

    code, stdout, stderr = _run_git(repo_path, cmd)
    if code != 0:
        return f"Error: {stderr}"
    return stdout or f"Reset to {target} ({mode} mode)"


async def builtin_git_rebase(args: dict[str, Any]) -> str:
    repo_path = _get_repo_path(args.get("repo_path"))
    if repo_path is None:
        return "Error: Not a git repository"

    base = args.get("base")
    continue_flag = args.get("continue", False)
    abort = args.get("abort", False)
    skip = args.get("skip", False)
    interactive = args.get("interactive", False)

    cmd = ["rebase"]
    if abort:
        cmd.append("--abort")
        code, stdout, stderr = _run_git(repo_path, cmd)
        return stdout or "Rebase aborted"
    if skip:
        cmd.append("--skip")
        code, stdout, stderr = _run_git(repo_path, cmd)
        return stdout or "Skipped current commit"
    if continue_flag:
        cmd.append("--continue")
        code, stdout, stderr = _run_git(repo_path, cmd)
        if code != 0:
            return f"Error: {stderr}\nResolve conflicts and run again with continue=true"
        return stdout or "Rebase continued"
    if interactive:
        if not base:
            return "Error: base is required for interactive rebase"
        cmd.extend(["-i", base])
        code, stdout, stderr = _run_git(repo_path, cmd)
        if code != 0:
            return f"Error: {stderr}"
        return stdout or "Interactive rebase started"
    if base:
        cmd.append(base)
        code, stdout, stderr = _run_git(repo_path, cmd)
        if code != 0:
            return f"Error: {stderr}"
        return stdout or f"Rebased onto {base}"
    return "Error: base, abort, continue, or skip is required"


async def builtin_git_merge(args: dict[str, Any]) -> str:
    repo_path = _get_repo_path(args.get("repo_path"))
    if repo_path is None:
        return "Error: Not a git repository"

    branch = args.get("branch")
    if not branch:
        return "Error: branch is required"
    no_ff = args.get("no_ff", False)
    squash = args.get("squash", False)
    message = args.get("message")

    cmd = ["merge"]
    if no_ff:
        cmd.append("--no-ff")
    if squash:
        cmd.append("--squash")
    if message:
        cmd.extend(["-m", message])
    cmd.append(branch)

    code, stdout, stderr = _run_git(repo_path, cmd)
    if code != 0:
        return f"Error: {stderr}"
    return stdout or f"Successfully merged {branch}"


async def builtin_git_stash(args: dict[str, Any]) -> str:
    repo_path = _get_repo_path(args.get("repo_path"))
    if repo_path is None:
        return "Error: Not a git repository"

    action = args.get("action", "push")
    message = args.get("message")
    stash_index = args.get("stash_index")
    include_untracked = args.get("include_untracked", False)

    cmd = ["stash"]
    if action == "list":
        cmd.append("list")
        code, stdout, stderr = _run_git(repo_path, cmd)
        return stdout or "No stash entries"
    elif action == "show":
        cmd.append("show")
        if stash_index is not None:
            cmd.append(f"stash@{{{stash_index}}}")
        code, stdout, stderr = _run_git(repo_path, cmd)
        return stdout or "No stash to show"
    elif action == "drop":
        if stash_index is None:
            return "Error: stash_index is required for drop"
        cmd.extend(["drop", f"stash@{{{stash_index}}}"])
        code, stdout, stderr = _run_git(repo_path, cmd)
        return stdout or f"Dropped stash@{{{stash_index}}}"
    elif action == "apply":
        cmd.append("apply")
        if stash_index is not None:
            cmd.append(f"stash@{{{stash_index}}}")
        code, stdout, stderr = _run_git(repo_path, cmd)
        if code != 0:
            return f"Error: {stderr}"
        return stdout or f"Applied stash@{{{stash_index}}}"
    elif action == "pop":
        cmd.append("pop")
        code, stdout, stderr = _run_git(repo_path, cmd)
        if code != 0:
            return f"Error: {stderr}"
        return stdout or "Popped stash and applied to working tree"
    else:
        if include_untracked:
            cmd.append("--include-untracked")
        if message:
            cmd.extend(["push", "-m", message])
        else:
            cmd.append("push")
        code, stdout, stderr = _run_git(repo_path, cmd)
        if code != 0:
            return f"Error: {stderr}"
        return stdout or "Changes stashed successfully"


async def builtin_git_cherry_pick(args: dict[str, Any]) -> str:
    repo_path = _get_repo_path(args.get("repo_path"))
    if repo_path is None:
        return "Error: Not a git repository"

    commits = args.get("commits", [])
    if not commits:
        return "Error: commits is required"
    no_commit = args.get("no_commit", False)
    continue_flag = args.get("continue", False)
    abort = args.get("abort", False)

    if abort:
        cmd = ["cherry-pick", "--abort"]
        code, stdout, stderr = _run_git(repo_path, cmd)
        return stdout or "Cherry-pick aborted"
    if continue_flag:
        cmd = ["cherry-pick", "--continue"]
        code, stdout, stderr = _run_git(repo_path, cmd)
        if code != 0:
            return f"Error: {stderr}\nResolve conflicts and run again with continue=true"
        return stdout or "Cherry-pick continued"

    cmd = ["cherry-pick"]
    if no_commit:
        cmd.append("--no-commit")
    cmd.extend(commits)

    code, stdout, stderr = _run_git(repo_path, cmd)
    if code != 0:
        return f"Error: {stderr}\nResolve conflicts manually"
    return stdout or f"Successfully cherry-picked {len(commits)} commit(s)"


async def builtin_git_fetch(args: dict[str, Any]) -> str:
    repo_path = _get_repo_path(args.get("repo_path"))
    if repo_path is None:
        return "Error: Not a git repository"

    remote = args.get("remote")
    all_remotes = args.get("all", False)
    prune = args.get("prune", False)
    tags = args.get("tags", False)

    cmd = ["fetch"]
    if all_remotes:
        cmd.append("--all")
    elif remote:
        cmd.append(remote)
    if prune:
        cmd.append("--prune")
    if tags:
        cmd.append("--tags")

    code, stdout, stderr = _run_git(repo_path, cmd)
    if code != 0:
        return f"Error: {stderr}"
    return stdout or "Fetch completed successfully"