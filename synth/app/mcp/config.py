from typing import Any

from app.config import config


class MCPConfig:
    @property
    def servers(self) -> dict[str, dict[str, Any]]:
        mcp_config = config._config.get("mcp")
        if mcp_config is None:
            return {}
        return mcp_config.get("servers", {}) or {}

    def get_server_config(self, name: str) -> dict[str, Any] | None:
        return self.servers.get(name)

    def list_servers(self) -> list[str]:
        return list(self.servers.keys())

    def is_server_configured(self, name: str) -> bool:
        return name in self.servers

    def get_default_enabled_servers(self) -> list[str]:
        return [
            name for name, cfg in self.servers.items()
            if cfg.get("enabled_by_default", False)
        ]


mcp_config = MCPConfig()
