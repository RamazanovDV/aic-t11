import os
import yaml
from pathlib import Path
from typing import Any

from app.config import config


class ProjectManager:
    def __init__(self):
        self._projects_dir = config.data_dir / "projects"
        self._ensure_projects_dir()

    def _ensure_projects_dir(self) -> None:
        self._projects_dir.mkdir(parents=True, exist_ok=True)

    def get_projects_list(self) -> list[str]:
        self._ensure_projects_dir()
        if not self._projects_dir.exists():
            return []
        return sorted([d.name for d in self._projects_dir.iterdir() if d.is_dir()])

    def _get_project_dir(self, project_name: str) -> Path:
        return self._projects_dir / project_name

    def _get_info_path(self, project_name: str) -> Path:
        return self._get_project_dir(project_name) / "info.md"

    def _get_current_task_path(self, project_name: str) -> Path:
        return self._get_project_dir(project_name) / "current_task.md"

    def _get_invariants_path(self, project_name: str) -> Path:
        return self._get_project_dir(project_name) / "invariants.yaml"

    def _get_config_path(self, project_name: str) -> Path:
        return self._get_project_dir(project_name) / "config.yaml"

    def project_exists(self, project_name: str) -> bool:
        return self._get_project_dir(project_name).exists()

    def get_project_info(self, project_name: str) -> str | None:
        info_path = self._get_info_path(project_name)
        if not info_path.exists():
            return None
        try:
            return info_path.read_text(encoding="utf-8")
        except Exception:
            return None

    def get_current_task(self, project_name: str) -> str | None:
        task_path = self._get_current_task_path(project_name)
        if not task_path.exists():
            return None
        try:
            return task_path.read_text(encoding="utf-8")
        except Exception:
            return None

    def create_project(self, project_name: str) -> bool:
        if not project_name or "/" in project_name or "\\" in project_name:
            return False

        project_dir = self._get_project_dir(project_name)
        if project_dir.exists():
            return False

        try:
            project_dir.mkdir(parents=True, exist_ok=True)
            default_info = f"""# Проект: {project_name}

## Описание
(Описание проекта)

## Участники
- (Список участников)

## Технологии
- (Используемые технологии)

## Особенности
- (Особенности проекта)

## Знания и решения
(Ключевые знания и принятые решения по проекту)
"""
            self._get_info_path(project_name).write_text(default_info, encoding="utf-8")
            return True
        except Exception:
            return False

    def update_project_info(self, project_name: str, content: str) -> bool:
        if not self.project_exists(project_name):
            return False

        try:
            self._get_info_path(project_name).write_text(content, encoding="utf-8")
            return True
        except Exception:
            return False

    def save_current_task(self, project_name: str, content: str) -> bool:
        if not self.project_exists(project_name):
            return False

        try:
            self._get_current_task_path(project_name).write_text(content, encoding="utf-8")
            return True
        except Exception:
            return False

    def get_invariants(self, project_name: str) -> dict[str, Any] | None:
        if not self.project_exists(project_name):
            return None

        invariants_path = self._get_invariants_path(project_name)
        if not invariants_path.exists():
            return None

        try:
            with open(invariants_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return None

    def save_invariants(self, project_name: str, invariants: dict[str, Any]) -> bool:
        if not self.project_exists(project_name):
            return False

        try:
            with open(self._get_invariants_path(project_name), "w", encoding="utf-8") as f:
                yaml.safe_dump(invariants, f, allow_unicode=True, sort_keys=False)
            return True
        except Exception:
            return False

    def get_project_config(self, project_name: str) -> dict[str, Any]:
        if not self.project_exists(project_name):
            return {}
        config_path = self._get_config_path(project_name)
        if not config_path.exists():
            return {}
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    def save_project_config(self, project_name: str, project_config: dict[str, Any]) -> bool:
        if not self.project_exists(project_name):
            return False
        try:
            config_path = self._get_config_path(project_name)
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(project_config, f, allow_unicode=True, sort_keys=False)
            return True
        except Exception:
            return False


project_manager = ProjectManager()
