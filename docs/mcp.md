# MCP (Model Context Protocol)

## Обзор

MCP (Model Context Protocol) — это протокол для расширения возможностей LLM через подключение внешних инструментов и сервисов. Synth поддерживает подключение к MCP серверам для доступа к файловой системе, базам данных, Git и другим инструментам.

## Архитектура MCP

```mermaid
graph TB
    subgraph "Synth"
        R["routes.py"]
        MM["MCPManager"]
        MC["MCPClient"]
    end
    
    subgraph "MCP"
        MCP1["MCP Server 1<br/>filesystem"]
        MCP2["MCP Server 2<br/>github"]
        MCP3["MCP Server N<br/>..."]
    end
    
    subgraph "LLM"
        LLM["LLM Provider"]
    end
    
    R --> MM
    MM --> MC
    MC --> MCP1
    MC --> MCP2
    MC --> MCP3
    LLM <--> R
```

## Конфигурация MCP серверов

MCP серверы настраиваются в `synth/config.yaml`:

```yaml
mcp:
  servers:
    filesystem:
      type: "stdio"
      command: "npx"
      args:
        - "-y"
        - "@modelcontextprotocol/server-filesystem"
        - "/path/to/allowed/directory"
      env:
        NODE_ENV: "production"

    github:
      type: "sse"
      url: "http://localhost:3000/sse"

    postgres:
      type: "stdio"
      command: "python"
      args:
        - "-m"
        - "mcp_server_postgres"
      env:
        DATABASE_URL: "postgresql://user:pass@localhost/db"
```

## Типы подключения

### STDIO
Локальные серверы, запускаемые как дочерние процессы:
- `command` — исполняемая команда
- `args` — аргументы
- `env` — переменные окружения

### SSE
Удалённые серверы по Server-Sent Events:
- `url` — URL SSE endpoint

## Использование в коде

### Подключение к серверу

```python
from app.mcp import MCPManager, tools_to_provider_format

# Получить список инструментов
tools = await MCPManager.get_tools(["filesystem", "github"])

# Преобразовать в формат провайдера
formatted_tools = tools_to_provider_format(tools, "openai")
```

### Вызов инструмента

```python
result = await MCPManager.call_tool("filesystem_read", {
    "path": "/path/to/file.txt"
})
```

## API эндпоинты

### GET /mcp/servers
Список настроенных серверов.

### GET /mcp/servers/<server_name>/tools
Получить инструменты конкретного сервера.

### GET /session/mcp
Получить MCP сервера текущей сессии.

```json
{
    "mcp_servers": ["filesystem"],
    "all_mcp_servers": [
        {"name": "filesystem", "active": "true"}
    ]
}
```

### PUT /session/mcp
Обновить список MCP серверов сессии.

```json
{
    "mcp_servers": ["filesystem", "github"]
}
```

### POST /session/mcp
Добавить MCP сервер.

### DELETE /session/mcp/<server_name>
Удалить MCP сервер.

## Доступные инструменты

Инструменты от MCP серверов автоматически передаются LLM. Примеры:

- **filesystem**: read_file, write_file, list_directory, etc.
- **github**: create_issue, get_pr, create_branch, etc.
- **postgres**: query, execute, list_tables, etc.

## Обработка ошибок

```python
try:
    result = await MCPManager.call_tool(tool_name, args)
except MCPConnectionError as e:
    logger.error(f"MCP connection error: {e}")
except Exception as e:
    logger.error(f"Tool execution error: {e}")
```

## Примеры MCP серверов

| Сервер | Описание | Команда установки |
|--------|----------|------------------|
| filesystem | Доступ к файловой системе | `npx -y @modelcontextprotocol/server-filesystem` |
| github | Интеграция с GitHub | `npm install -g @modelcontextprotocol/server-github` |
| postgres | PostgreSQL клиент | `pip install mcp-server-postgres` |
| sqlite | SQLite клиент | `pip install mcp-server-sqlite` |
