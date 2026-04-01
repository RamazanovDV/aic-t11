import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import config
from app.ssh_key_manager import ssh_key_manager


@dataclass
class GitCloneResult:
    success: bool
    local_path: str | None
    message: str
    commit: str | None = None


@dataclass
class GitRepoInfo:
    name: str
    url: str
    repo_type: str
    branch: str
    local_path: str
    last_fetch: str | None
    auto_index: bool
    required_agent: str | None
    current_commit: str | None = None
    branches: list[str] = None
    status: str | None = None
    
    def __post_init__(self):
        if self.branches is None:
            self.branches = []


class GitCloneService:
    def __init__(self):
        self._projects_dir = config.data_dir / "projects"
    
    def _get_repos_dir(self, project_name: str) -> Path:
        repos_dir = self._projects_dir / project_name / "repos"
        repos_dir.mkdir(parents=True, exist_ok=True)
        return repos_dir
    
    def _is_ssh_url(self, url: str) -> bool:
        return url.startswith("git@") or url.startswith("ssh://")
    
    def _build_git_env(self, agent_name: str | None, key_id: str | None) -> dict[str, str]:
        env = os.environ.copy()
        
        if agent_name:
            private_key, passphrase = ssh_key_manager.get_private_key_for_clone(agent_name, key_id)
            if private_key:
                with tempfile.NamedTemporaryFile(mode='w', suffix='_ssh_key', delete=False) as f:
                    f.write(private_key)
                    key_path = f.name
                
                env["GIT_SSH_COMMAND"] = f"ssh -i {key_path}"
                if passphrase:
                    env["SSH_PASSPHRASE"] = passphrase
                    
                return env
        return env
    
    def _run_git_command(self, args: list[str], cwd: Path | None = None, env: dict | None = None) -> tuple[int, str, str]:
        full_env = env or os.environ.copy()
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=cwd,
                env=full_env,
                capture_output=True,
                text=True,
                timeout=300
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "Command timed out"
        except FileNotFoundError:
            return -1, "", "Git not found"
    
    def clone(
        self,
        url: str,
        local_path: Path,
        agent_name: str | None = None,
        key_id: str | None = None,
        branch: str = "main"
    ) -> GitCloneResult:
        if local_path.exists() and (local_path / ".git").exists():
            return GitCloneResult(
                success=False,
                local_path=str(local_path),
                message="Repository already exists at path"
            )
        
        local_path.parent.mkdir(parents=True, exist_ok=True)
        
        env = self._build_git_env(agent_name, key_id)
        
        if self._is_ssh_url(url) and not agent_name:
            return GitCloneResult(
                success=False,
                local_path=None,
                message="SSH URL requires agent_name with SSH key"
            )
        
        args = ["clone"]
        if branch:
            args.extend(["--branch", branch, "--"])
        args.extend([url, str(local_path)])
        
        returncode, stdout, stderr = self._run_git_command(args, env=env)
        
        if returncode == 0:
            commit = self.get_current_commit(local_path)
            return GitCloneResult(
                success=True,
                local_path=str(local_path),
                message="Repository cloned successfully",
                commit=commit
            )
        else:
            return GitCloneResult(
                success=False,
                local_path=None,
                message=f"Clone failed: {stderr}"
            )
    
    def fetch(
        self,
        repo_path: Path,
        agent_name: str | None = None,
        key_id: str | None = None,
        remote: str = "origin"
    ) -> tuple[bool, str]:
        env = self._build_git_env(agent_name, key_id)
        
        returncode, stdout, stderr = self._run_git_command(
            ["fetch", "--all", "--tags"],
            cwd=repo_path,
            env=env
        )
        
        if returncode == 0:
            return True, "Fetch successful"
        else:
            return False, f"Fetch failed: {stderr}"
    
    def get_current_commit(self, repo_path: Path) -> str | None:
        returncode, stdout, stderr = self._run_git_command(
            ["rev-parse", "HEAD"],
            cwd=repo_path
        )
        if returncode == 0:
            return stdout.strip()
        return None
    
    def get_current_branch(self, repo_path: Path) -> str | None:
        returncode, stdout, stderr = self._run_git_command(
            ["branch", "--show-current"],
            cwd=repo_path
        )
        if returncode == 0:
            return stdout.strip()
        return None
    
    def list_branches(self, repo_path: Path, remote: bool = False) -> list[str]:
        args = ["branch", "-a"] if remote else ["branch"]
        returncode, stdout, stderr = self._run_git_command(args, cwd=repo_path)
        if returncode == 0:
            branches = []
            for line in stdout.strip().split("\n"):
                branch = line.strip()
                if branch.startswith("*"):
                    branch = branch[1:].strip()
                if branch and branch != "(detached)":
                    branches.append(branch.replace("remotes/", "").strip())
            return branches
        return []
    
    def get_status(self, repo_path: Path) -> str:
        returncode, stdout, stderr = self._run_git_command(
            ["status", "--porcelain"],
            cwd=repo_path
        )
        if returncode == 0:
            if stdout.strip():
                return "dirty"
            return "clean"
        return "unknown"
    
    def get_log(
        self,
        repo_path: Path,
        limit: int = 50,
        branch: str | None = None
    ) -> list[dict[str, Any]]:
        args = ["log", f"--pretty=format:%H|%s|%an|%ad", "--date=iso"]
        if branch:
            args.append(branch)
        else:
            args.append("--all")
        args.extend([f"-n", str(limit)])
        
        returncode, stdout, stderr = self._run_git_command(args, cwd=repo_path)
        if returncode != 0:
            return []
        
        commits = []
        for line in stdout.strip().split("\n"):
            if "|" in line:
                parts = line.split("|")
                if len(parts) >= 4:
                    commits.append({
                        "hash": parts[0],
                        "subject": parts[1],
                        "author": parts[2],
                        "date": parts[3],
                    })
        return commits
    
    def get_diff(
        self,
        repo_path: Path,
        target: str = "HEAD",
        base: str | None = None
    ) -> str:
        if base:
            returncode, stdout, stderr = self._run_git_command(
                ["diff", base, target],
                cwd=repo_path
            )
        else:
            returncode, stdout, stderr = self._run_git_command(
                ["diff", target],
                cwd=repo_path
            )
        
        if returncode == 0:
            return stdout
        return f"Diff failed: {stderr}"
    
    def get_commit_diff(self, repo_path: Path, commit: str) -> str:
        returncode, stdout, stderr = self._run_git_command(
            ["show", "--format=", "-p", commit],
            cwd=repo_path
        )
        if returncode == 0:
            return stdout
        return f"Show commit failed: {stderr}"
    
    def get_commit_info(self, repo_path: Path, commit: str) -> dict[str, Any] | None:
        returncode, stdout, stderr = self._run_git_command(
            ["show", "--format=%H|%s|%an|%ae|%ad", "--date=iso", "-s", commit],
            cwd=repo_path
        )
        if returncode != 0:
            return None
        
        parts = stdout.strip().split("|")
        if len(parts) >= 5:
            return {
                "hash": parts[0],
                "subject": parts[1],
                "author_name": parts[2],
                "author_email": parts[3],
                "date": parts[4],
            }
        return None
    
    def show_file_at_commit(self, repo_path: Path, commit: str, file_path: str) -> str:
        returncode, stdout, stderr = self._run_git_command(
            ["show", f"{commit}:{file_path}"],
            cwd=repo_path
        )
        if returncode == 0:
            return stdout
        return f"File not found at commit: {stderr}"
    
    def get_remote_url(self, repo_path: Path) -> str | None:
        returncode, stdout, stderr = self._run_git_command(
            ["remote", "get-url", "origin"],
            cwd=repo_path
        )
        if returncode == 0:
            return stdout.strip()
        return None
    
    def checkout_branch(self, repo_path: Path, branch: str) -> tuple[bool, str]:
        returncode, stdout, stderr = self._run_git_command(
            ["checkout", branch],
            cwd=repo_path
        )
        if returncode == 0:
            return True, "Checkout successful"
        return False, f"Checkout failed: {stderr}"


git_clone_service = GitCloneService()
