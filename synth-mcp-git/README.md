# Synth MCP Git Server

MCP сервер для работы с Git репозиториями.

## Возможности

- Получение текущей ветки
- Список файлов в репозитории
- Git diff (staged, unstaged, between commits)
- Git status
- История коммитов
- Информация о файлах/коммитах

## Установка

### 1. Установка зависимостей

```bash
cd synth-mcp-git
pip install -r requirements.txt
```

Или установите только mcp:
```bash
pip install mcp
```

### 2. Настройка в Synth

Добавьте в `synth/config.yaml`:

```yaml
mcp:
  servers:
    git:
      type: stdio
      command: "python"
      args:
        - "/path/to/synth-mcp-git/server.py"
      env:
        ALLOWED_DIRS: "/home:/workspace:/projects"
        GIT_REPO_PATH: "/path/to/default/repo"
```

## Переменные окружения

| Переменная | Описание |
|-----------|----------|
| `ALLOWED_DIRS` | Разрешённые директории (через `:`) |
| `GIT_REPO_PATH` | Путь по умолчанию к репозиторию |
| `SYNTH_MCP_GIT_CONFIG` | Путь к config.yaml Synth |

## Использование

### Как MCP сервер

```bash
python server.py
```

Сервер работает через stdio, принимая JSON-RPC команды от MCP клиента.

### Доступные инструменты

#### git_branch
Получить текущую ветку.

```python
{"name": "git_branch", "arguments": {"repo_path": "/path/to/repo"}}
```

#### git_files
Список файлов репозитория.

```python
{
    "name": "git_files",
    "arguments": {
        "repo_path": "/path/to/repo",
        "pattern": "*.py",  # опционально
        "include_untracked": true
    }
}
```

#### git_diff
Diff изменений.

```python
{
    "name": "git_diff",
    "arguments": {
        "repo_path": "/path/to/repo",
        "staged": false,
        "stat": false,
        "from_commit": "abc123",  # опционально
        "to_commit": "def456"
    }
}
```

#### git_status
Статус репозитория.

```python
{
    "name": "git_status",
    "arguments": {
        "repo_path": "/path/to/repo",
        "short": true
    }
}
```

#### git_log
История коммитов.

```python
{
    "name": "git_log",
    "arguments": {
        "repo_path": "/path/to/repo",
        "max_count": 10,
        "format": "%h %s"
    }
}
```

#### git_show
Информация о коммите/файле.

```python
{
    "name": "git_show",
    "arguments": {
        "repo_path": "/path/to/repo",
        "object": "HEAD",
        "file": "path/to/file.txt"  # опционально
    }
}
```

#### git_list_branches
Список веток.

```python
{
    "name": "git_list_branches",
    "arguments": {
        "repo_path": "/path/to/repo",
        "all": false
    }
}
```

## Безопасность

- По умолчанию доступ ограничен директориями в `ALLOWED_DIRS`
- Пути вне разрешённых директорий будут отклонены
- subprocess timeout = 30 секунд

## Лицензия

MIT
