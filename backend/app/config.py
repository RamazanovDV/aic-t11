import os
from pathlib import Path
from typing import Any

import yaml


class Config:
    _instance = None
    _config: dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_config()
        return cls._instance

    def _load_config(self) -> None:
        config_path = Path(__file__).parent.parent.parent / "config.yaml"
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path, "r") as f:
            self._config = yaml.safe_load(f)

    @property
    def app(self) -> dict[str, Any]:
        return self._config.get("app", {})

    @property
    def host(self) -> str:
        return self.app.get("host", "0.0.0.0")

    @property
    def port(self) -> int:
        return self.app.get("port", 5000)

    @property
    def auth(self) -> dict[str, Any]:
        return self._config.get("auth", {})

    @property
    def api_key(self) -> str:
        return self.auth.get("api_key", "")

    @property
    def llm(self) -> dict[str, Any]:
        return self._config.get("llm", {})

    @property
    def default_provider(self) -> str:
        return self.llm.get("default_provider", "openai")

    @property
    def providers(self) -> dict[str, dict[str, Any]]:
        return self.llm.get("providers", {})

    def get_provider_config(self, name: str) -> dict[str, Any]:
        return self.providers.get(name, {})

    @property
    def context(self) -> dict[str, Any]:
        return self._config.get("context", {})

    @property
    def context_dir(self) -> Path:
        dir_name = self.context.get("dir", "context")
        return Path(__file__).parent.parent.parent / dir_name

    @property
    def storage(self) -> dict[str, Any]:
        return self._config.get("storage", {})

    @property
    def data_dir(self) -> Path:
        dir_name = self.storage.get("data_dir", "./data")
        return Path(__file__).parent.parent.parent / dir_name


config = Config()
