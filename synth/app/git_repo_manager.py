import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import config
from app.git_clone_service import git_clone_service, GitCloneResult, GitRepoInfo
from app.project_manager import project_manager


@dataclass
class RepoConfig:
    name: str
    url: str
    repo_type: str
    branch: str
    local_path: str
    last_fetch: str | None
    auto_index: bool
    required_agent: str | None
    ssh_key_id: str | None = None


class GitRepoManager:
    def __init__(self):
        self._projects_dir = config.data_dir / "projects"
    
    def _get_repos_dir(self, project_name: str) -> Path:
        return self._projects_dir / project_name / "repos"
    
    def _get_git_repos_config(self, project_name: str) -> list[dict[str, Any]]:
        project_config = project_manager.get_project_config(project_name)
        return project_config.get("git_repos", [])
    
    def _save_git_repos_config(self, project_name: str, repos: list[dict[str, Any]]) -> bool:
        project_config = project_manager.get_project_config(project_name)
        project_config["git_repos"] = repos
        return project_manager.save_project_config(project_name, project_config)
    
    def _find_repo_config(self, project_name: str, repo_name: str) -> dict[str, Any] | None:
        repos = self._get_git_repos_config(project_name)
        for repo in repos:
            if repo.get("name") == repo_name:
                return repo
        return None
    
    def _repo_config_to_info(self, project_name: str, repo_config: dict[str, Any]) -> GitRepoInfo:
        repo_path = Path(self._get_repos_dir(project_name)) / repo_config["name"]
        
        current_commit = None
        branches = []
        status = None
        
        if repo_path.exists() and (repo_path / ".git").exists():
            current_commit = git_clone_service.get_current_commit(repo_path)
            branches = git_clone_service.list_branches(repo_path)
            status = git_clone_service.get_status(repo_path)
        
        return GitRepoInfo(
            name=repo_config["name"],
            url=repo_config["url"],
            repo_type=repo_config.get("type", "https"),
            branch=repo_config.get("branch", "main"),
            local_path=str(repo_path),
            last_fetch=repo_config.get("last_fetch"),
            auto_index=repo_config.get("auto_index", True),
            required_agent=repo_config.get("required_agent"),
            current_commit=current_commit,
            branches=branches,
            status=status,
        )
    
    def list_repos(self, project_name: str) -> list[GitRepoInfo]:
        if not project_manager.project_exists(project_name):
            return []
        
        repos = self._get_git_repos_config(project_name)
        return [self._repo_config_to_info(project_name, repo) for repo in repos]
    
    def get_repo(self, project_name: str, repo_name: str) -> GitRepoInfo | None:
        repo_config = self._find_repo_config(project_name, repo_name)
        if not repo_config:
            return None
        return self._repo_config_to_info(project_name, repo_config)
    
    def get_repo_path(self, project_name: str, repo_name: str) -> Path | None:
        repo_config = self._find_repo_config(project_name, repo_name)
        if not repo_config:
            return None
        return self._get_repos_dir(project_name) / repo_name
    
    def add_repo(
        self,
        project_name: str,
        url: str,
        name: str | None = None,
        repo_type: str = "https",
        branch: str = "main",
        required_agent: str | None = None,
        ssh_key_id: str | None = None,
        auto_index: bool = True
    ) -> tuple[bool, str, GitRepoInfo | None]:
        if not project_manager.project_exists(project_name):
            return False, "Project not found", None
        
        repos = self._get_git_repos_config(project_name)
        
        repo_name = name or url.split("/")[-1].replace(".git", "")
        
        for existing in repos:
            if existing.get("name") == repo_name:
                return False, f"Repository '{repo_name}' already exists", None
        
        local_path = str(self._get_repos_dir(project_name) / repo_name)
        
        result = git_clone_service.clone(
            url=url,
            local_path=Path(local_path),
            agent_name=required_agent,
            key_id=ssh_key_id,
            branch=branch
        )
        
        if not result.success:
            return False, result.message, None
        
        repo_config = {
            "name": repo_name,
            "url": url,
            "type": repo_type,
            "branch": branch,
            "local_path": local_path,
            "last_fetch": datetime.utcnow().isoformat() + "Z",
            "auto_index": auto_index,
            "required_agent": required_agent,
            "ssh_key_id": ssh_key_id,
        }
        
        repos.append(repo_config)
        if not self._save_git_repos_config(project_name, repos):
            return False, "Failed to save repository config", None
        
        repo_info = self._repo_config_to_info(project_name, repo_config)
        
        if auto_index:
            self._trigger_rag_index(project_name, repo_name)
        
        return True, "Repository added successfully", repo_info
    
    def remove_repo(self, project_name: str, repo_name: str, delete_local: bool = False) -> tuple[bool, str]:
        if not project_manager.project_exists(project_name):
            return False, "Project not found"
        
        repos = self._get_git_repos_config(project_name)
        repo_config = self._find_repo_config(project_name, repo_name)
        
        if not repo_config:
            return False, "Repository not found"
        
        new_repos = [r for r in repos if r.get("name") != repo_name]
        if not self._save_git_repos_config(project_name, new_repos):
            return False, "Failed to save repository config"
        
        if delete_local:
            repo_path = self._get_repos_dir(project_name) / repo_name
            if repo_path.exists():
                import shutil
                try:
                    shutil.rmtree(repo_path)
                except Exception as e:
                    return True, f"Repository removed from config, but failed to delete local: {e}"
        
        return True, "Repository removed"
    
    def fetch_repo(
        self,
        project_name: str,
        repo_name: str,
        reindex: bool = True
    ) -> tuple[bool, str]:
        if not project_manager.project_exists(project_name):
            return False, "Project not found"
        
        repo_config = self._find_repo_config(project_name, repo_name)
        if not repo_config:
            return False, "Repository not found"
        
        repo_path = self._get_repos_dir(project_name) / repo_name
        if not repo_path.exists():
            return False, "Local repository not found"
        
        success, message = git_clone_service.fetch(
            repo_path=repo_path,
            agent_name=repo_config.get("required_agent"),
            key_id=repo_config.get("ssh_key_id")
        )
        
        if success:
            repo_config["last_fetch"] = datetime.utcnow().isoformat() + "Z"
            repos = self._get_git_repos_config(project_name)
            for i, r in enumerate(repos):
                if r.get("name") == repo_name:
                    repos[i] = repo_config
                    break
            self._save_git_repos_config(project_name, repos)
            
            if reindex and repo_config.get("auto_index"):
                self._trigger_rag_index(project_name, repo_name)
        
        return success, message
    
    def update_repo_config(
        self,
        project_name: str,
        repo_name: str,
        updates: dict[str, Any]
    ) -> tuple[bool, str]:
        if not project_manager.project_exists(project_name):
            return False, "Project not found"
        
        repos = self._get_git_repos_config(project_name)
        
        for i, repo in enumerate(repos):
            if repo.get("name") == repo_name:
                for key, value in updates.items():
                    if key not in ["name", "url", "local_path"]:
                        repo[key] = value
                repos[i] = repo
                self._save_git_repos_config(project_name, repos)
                return True, "Repository updated"
        
        return False, "Repository not found"
    
    def _trigger_rag_index(self, project_name: str, repo_name: str) -> None:
        try:
            from app.embeddings.indexer import index_project_rag
            repo_path = self._get_repos_dir(project_name) / repo_name
            if repo_path.exists():
                index_project_rag(project_name, str(repo_path))
        except Exception:
            pass
    
    def get_repo_diff(
        self,
        project_name: str,
        repo_name: str,
        target: str = "HEAD",
        base: str | None = None
    ) -> tuple[bool, str, str | None]:
        repo_path = self.get_repo_path(project_name, repo_name)
        if not repo_path:
            return False, "Repository not found", None
        
        if not repo_path.exists():
            return False, "Local repository not found", None
        
        diff = git_clone_service.get_diff(repo_path, target, base)
        return True, "Diff retrieved", diff
    
    def get_repo_commit_diff(
        self,
        project_name: str,
        repo_name: str,
        commit: str
    ) -> tuple[bool, str, str | None]:
        repo_path = self.get_repo_path(project_name, repo_name)
        if not repo_path:
            return False, "Repository not found", None
        
        if not repo_path.exists():
            return False, "Local repository not found", None
        
        diff = git_clone_service.get_commit_diff(repo_path, commit)
        return True, "Commit diff retrieved", diff
    
    def get_repo_info(
        self,
        project_name: str,
        repo_name: str
    ) -> tuple[bool, str, dict | None]:
        repo = self.get_repo(project_name, repo_name)
        if not repo:
            return False, "Repository not found", None
        
        return True, "Repository info retrieved", asdict(repo)


git_repo_manager = GitRepoManager()
