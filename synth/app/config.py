import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from app.context import ContextManager


class Config:
    _instance = None
    _config: dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_config()
        return cls._instance

    def _load_config(self) -> None:
        config_path = Path(__file__).parent.parent / "config.yaml"
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path, "r") as f:
            self._config = yaml.safe_load(f)

    def reload(self) -> None:
        self._load_config()

    @property
    def config_path(self) -> Path:
        return Path(__file__).parent.parent / "config.yaml"

    def save(self) -> None:
        with open(self.config_path, "w") as f:
            yaml.dump(self._config, f, default_flow_style=False, allow_unicode=True)

    def update_config(self, new_config: dict[str, Any]) -> None:
        self._config = new_config
        self.save()
        self.reload()

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
    def secret_key(self) -> str:
        return self.auth.get("secret_key", "dev-secret-key-change-in-production")

    @property
    def default_provider(self) -> str:
        return self._config.get("default_provider", "openai")

    @property
    def timeout(self) -> int:
        return self._config.get("timeout", 120)

    @property
    def orchestrator_timeout(self) -> int:
        return self._config.get("orchestrator_timeout", 300)

    @property
    def token_warning_percent(self) -> int:
        return self._config.get("token_warning_percent", 80)

    @property
    def token_abort_percent(self) -> int:
        return self._config.get("token_abort_percent", 95)

    @property
    def providers(self) -> dict[str, dict[str, Any]]:
        return self._config.get("providers", {})

    def get_provider_config(self, name: str) -> dict[str, Any]:
        provider = self.providers.get(name, {}).copy()
        if "default_model" not in provider:
            provider["default_model"] = self.get_default_model(name)
        return provider

    @property
    def storage(self) -> dict[str, Any]:
        return self._config.get("storage", {})

    @property
    def data_dir(self) -> Path:
        dir_name = self.storage.get("data_dir", "./data")
        return Path(__file__).parent.parent.parent / dir_name

    @property
    def context_dir(self) -> Path:
        return self.data_dir / "context"

    @property
    def context_manager(self) -> "ContextManager":
        from app.context import ContextManager
        return ContextManager()
    
    def get_context_file(self, filename: str) -> str | None:
        from app.context import ContextManager
        return ContextManager().get_context_file(filename)

    def save_context_file(self, filename: str, content: str) -> None:
        from app.context import ContextManager
        return ContextManager().save_context_file(filename, content)

    def get_default_model(self, provider: str) -> str:
        return self.providers.get(provider, {}).get("default_model", "")

    @property
    def context_config(self) -> dict[str, Any]:
        return self._config.get("context", {})

    def get_enabled_context_files(self) -> list[str]:
        return self.context_config.get("enabled_files", [])

    def set_enabled_context_files(self, files: list[str]) -> None:
        if "context" not in self._config:
            self._config["context"] = {}
        self._config["context"]["enabled_files"] = files
        self.save()

    def create_context_file(self, filename: str, content: str = "") -> None:
        if not filename.endswith(".md"):
            filename = filename + ".md"
        filepath = self.context_dir / filename
        if filepath.exists():
            raise FileExistsError(f"File already exists: {filename}")
        filepath.write_text(content, encoding="utf-8")

    def delete_context_file(self, filename: str) -> None:
        filepath = self.context_dir / filename
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filename}")
        filepath.unlink()
        enabled = self.get_enabled_context_files()
        if filename in enabled:
            enabled.remove(filename)
            self.set_enabled_context_files(enabled)

    def rename_context_file(self, old_name: str, new_name: str) -> None:
        if not new_name.endswith(".md"):
            new_name = new_name + ".md"
        old_path = self.context_dir / old_name
        new_path = self.context_dir / new_name
        if not old_path.exists():
            raise FileNotFoundError(f"File not found: {old_name}")
        if new_path.exists():
            raise FileExistsError(f"File already exists: {new_name}")
        old_path.rename(new_path)
        enabled = self.get_enabled_context_files()
        if old_name in enabled:
            enabled = [new_name if f == old_name else f for f in enabled]
            self.set_enabled_context_files(enabled)

    @property
    def summarizer_config(self) -> dict[str, Any]:
        return self._config.get("summarizer", {})

    @property
    def summarizer_provider(self) -> str:
        return self.summarizer_config.get("provider", "openai")

    @property
    def summarizer_model(self) -> str:
        return self.summarizer_config.get("model", "gpt-4o-mini")

    @property
    def summarizer_prompt_source(self) -> str:
        return self.summarizer_config.get("prompt_source", "SUMMARIZER.md")

    @property
    def summarizer_temperature(self) -> float:
        return self.summarizer_config.get("temperature", 0.3)

    @property
    def summarization_config(self) -> dict[str, Any]:
        return self._config.get("summarization", {})

    @property
    def default_messages_interval(self) -> int:
        return self.summarization_config.get("default_messages_interval", 10)

    @property
    def debug_config(self) -> dict[str, Any]:
        return self._config.get("debug", {})

    @property
    def debug_groups(self) -> dict[str, str]:
        return self.debug_config.get("groups", {
            "ANTHROPIC": "INFO",
            "MCP": "INFO",
            "ROUTES": "WARNING",
            "ORCHESTRATOR": "INFO",
            "CHAT_STREAM": "WARNING",
            "TSM": "INFO",
            "STORAGE": "WARNING",
            "SCHEDULER": "INFO",
            "INIT": "INFO",
            "DEBUG": "DEBUG",
        })

    def set_debug_group(self, group: str, level: str) -> None:
        if "debug" not in self._config:
            self._config["debug"] = {}
        if "groups" not in self._config["debug"]:
            self._config["debug"]["groups"] = {}
        self._config["debug"]["groups"][group] = level
        self.save()

    DEFAULT_MODELS = {
        "gpt-4o": {
            "provider": "openai",
            "context_window": 128000,
            "input_price": 2.5,
            "output_price": 10.0,
            "cache_read_price": 1.25,
            "cache_write_price": 3.75,
            "enabled": True,
        },
        "gpt-4o-mini": {
            "provider": "openai",
            "context_window": 128000,
            "input_price": 0.15,
            "output_price": 0.6,
            "cache_read_price": 0.075,
            "cache_write_price": 0.3,
            "enabled": True,
        },
        "gpt-4-turbo": {
            "provider": "openai",
            "context_window": 128000,
            "input_price": 10.0,
            "output_price": 30.0,
            "cache_read_price": 10.0,
            "cache_write_price": 15.0,
        },
        "gpt-3.5-turbo": {
            "provider": "openai",
            "context_window": 16385,
            "input_price": 0.5,
            "output_price": 1.5,
            "cache_read_price": 0.0,
            "cache_write_price": 0.0,
        },
        "claude-3-5-sonnet-20241022": {
            "provider": "anthropic",
            "context_window": 200000,
            "input_price": 3.0,
            "output_price": 15.0,
            "cache_read_price": 3.75,
            "cache_write_price": 15.0,
        },
        "claude-3-5-sonnet-20240620": {
            "provider": "anthropic",
            "context_window": 200000,
            "input_price": 3.0,
            "output_price": 15.0,
            "cache_read_price": 3.75,
            "cache_write_price": 15.0,
        },
        "claude-3-opus-20240229": {
            "provider": "anthropic",
            "context_window": 200000,
            "input_price": 15.0,
            "output_price": 75.0,
            "cache_read_price": 15.0,
            "cache_write_price": 75.0,
        },
        "claude-3-haiku-20240307": {
            "provider": "anthropic",
            "context_window": 200000,
            "input_price": 0.25,
            "output_price": 1.25,
            "cache_read_price": 0.3,
            "cache_write_price": 1.25,
        },
        "llama3": {
            "provider": "ollama",
            "context_window": 8192,
            "input_price": 0.0,
            "output_price": 0.0,
            "cache_read_price": 0.0,
            "cache_write_price": 0.0,
        },
        "llama3.1": {
            "provider": "ollama",
            "context_window": 128000,
            "input_price": 0.0,
            "output_price": 0.0,
            "cache_read_price": 0.0,
            "cache_write_price": 0.0,
        },
        "mistral": {
            "provider": "ollama",
            "context_window": 8192,
            "input_price": 0.0,
            "output_price": 0.0,
            "cache_read_price": 0.0,
            "cache_write_price": 0.0,
        },
    }

    @property
    def models(self) -> dict[str, dict]:
        return self._config.get("models", self.DEFAULT_MODELS)

    def get_model_info(self, model_name: str) -> dict | None:
        # First check in _config["models"], then in DEFAULT_MODELS
        in_config = self._config.get("models", {}).get(model_name)
        in_defaults = self.DEFAULT_MODELS.get(model_name)
        return in_config or in_defaults

    def get_context_window(self, model_name: str) -> int:
        info = self.get_model_info(model_name)
        return info.get("context_window", 128000) if info else 128000

    def set_model_info(self, model_name: str, info: dict) -> None:
        if "models" not in self._config:
            self._config["models"] = dict(self.DEFAULT_MODELS)
        
        existing = self._config["models"].get(model_name)
        if existing:
            self._config["models"][model_name] = {**existing, **info}
        else:
            self._config["models"][model_name] = info
        self.save()

    def delete_model(self, model_name: str) -> bool:
        if "models" not in self._config:
            self._config["models"] = dict(self.DEFAULT_MODELS)
        
        if model_name in self._config["models"]:
            del self._config["models"][model_name]
            self.save()
            return True
        return False

    @property
    def rag_config(self) -> dict[str, Any]:
        return self._config.get("rag", {})

    def get_rag_config(self) -> dict[str, Any]:
        rag = self._config.get("rag", {})
        return {
            "enabled": rag.get("enabled", False),
            "default_index": rag.get("default_index", ""),
            "top_k": rag.get("top_k", 5),
            "reranker": rag.get("reranker", {
                "enabled": False,
                "type": "relative",
                "threshold": 0.3,
                "multiplier": 1.5,
                "std_multiplier": 2.0,
                "top_k_before": 20,
            }),
            "say_unknown_enabled": rag.get("say_unknown_enabled", False),
            "say_unknown_threshold": rag.get("say_unknown_threshold", 0.3),
        }

    def save_rag_config(self, config: dict[str, Any]) -> None:
        self._config["rag"] = config
        self.save()

    @property
    def agents_config_path(self) -> Path:
        return Path(__file__).parent.parent / "agents.yaml"

    def _load_agents_config(self) -> dict[str, Any]:
        agents_path = self.agents_config_path
        if not agents_path.exists():
            return {}
        with open(agents_path, "r") as f:
            return yaml.safe_load(f) or {}

    def _save_agents_config(self, agents_config: dict[str, Any]) -> None:
        with open(self.agents_config_path, "w") as f:
            yaml.dump(agents_config, f, default_flow_style=False, allow_unicode=True)

    @property
    def agents(self) -> dict[str, dict[str, Any]]:
        return self._load_agents_config().get("agents", {})

    def get_agent(self, name: str) -> dict[str, Any] | None:
        return self.agents.get(name)

    def save_agent(self, name: str, agent_config: dict[str, Any]) -> None:
        agents_config = self._load_agents_config()
        if "agents" not in agents_config:
            agents_config["agents"] = {}
        agents_config["agents"][name] = agent_config
        self._save_agents_config(agents_config)

    def delete_agent(self, name: str) -> bool:
        agents_config = self._load_agents_config()
        if "agents" in agents_config and name in agents_config["agents"]:
            del agents_config["agents"][name]
            self._save_agents_config(agents_config)
            return True
        return False

    def get_role_prompt(self, role_name: str) -> str | None:
        agent = self.get_agent(role_name)
        if not agent:
            return None
        context_file = agent.get("context_file")
        if not context_file:
            return None
        return self.get_context_file(context_file)


config = Config()
