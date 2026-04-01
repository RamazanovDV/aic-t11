# Git Repository Registry & Code Review

## Обзор

Система управления Git репозиториями с возможностью клонирования, обновления и автоматического индексирования документации. Позволяет проводить code review с использованием RAG контекста из проекта.

## Архитектура

```
┌─────────────────────────────────────────────────────────────────────┐
│                        agents.yaml                                    │
│  agents.{agent}.ssh_keys[] → SSH ключи (encrypted)                 │
│  agents.{agent}.capabilities[] → capabilities агента                │
│  Привязка ключей к агентам/ролям                                    │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│              data/projects/{project}/config.yaml                      │
│  git_repos: [] → список репозиториев проекта                         │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│              data/projects/{project}/repos/                           │
│  {repo_name}/ → клонированные репозитории                           │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                     Builtin Tools (LLM)                              │
│  code_review, get_current_project, list_project_repos,             │
│  get_repo_info, read_file, list_directory, grep_files             │
└─────────────────────────────────────────────────────────────────────┘
```

## SSH Keys

### Структура в agents.yaml

```yaml
agents:
  developer:
    capabilities:
      - development
      - code_review
    ssh_keys:
      - id: "key-1"
        name: "GitHub Deploy Key"
        type: "deploy"  # deploy | user
        private_key: "encrypted:base64..."
        passphrase: "encrypted:base64..."
```

### API Endpoints

```
GET    /admin/agents/{agent}/ssh-keys       - список ключей агента
POST   /admin/agents/{agent}/ssh-keys       - добавить ключ
PUT    /admin/agents/{agent}/ssh-keys/{id}  - обновить ключ
DELETE /admin/agents/{agent}/ssh-keys/{id}  - удалить ключ
```

### CLI

```bash
# SSH ключи управляются через админку
```

## Repository Registry

### Структура в data/projects/{project}/config.yaml

```yaml
git_repos:
  - name: "backend"
    url: "https://github.com/org/backend.git"  # или git@github.com:...
    type: "https"  # или "ssh"
    branch: "main"
    local_path: "repos/backend"
    last_fetch: "2026-03-31T12:00:00Z"
    auto_index: true  # переиндексировать RAG после fetch
    required_agent: "developer"  # агент с SSH ключом
    ssh_key_id: "key-1"  # конкретный ключ (опционально)
```

### API Endpoints

```
GET    /api/projects/{project}/git-repos                    - список репозиториев
POST   /api/projects/{project}/git-repos                    - добавить репозиторий
DELETE /api/projects/{project}/git-repos/{repo}             - удалить репозиторий
POST   /api/projects/{project}/git-repos/{repo}/fetch       - fetch + reindex
GET    /api/projects/{project}/git-repos/{repo}/info        - информация о репозитории
```

### UI

Репозитории управляются через модальное окно в интерфейсе (кнопка "Репозитории" в branch-panel).

## Slash Commands

Slash команды работают как в streaming, так и в non-streaming режимах.

### Доступные команды

| Команда | Описание |
|---------|---------|
| `/help <вопрос>` | Ответить на вопрос о проекте с помощью RAG |
| `/add_repo <url> [--name <name>] [--branch <branch>] [--agent <agent>]` | Добавить git репозиторий к проекту |
| `/review <repo> [--target <target>] [--base <branch>]` | Провести code review |
| `/commands` | Показать список доступных команд |

### Примеры

```
/review aic-t11
/review aic-t11 --target feature-branch --base main
/add_repo https://github.com/org/repo.git --name my-repo --branch develop
```

## Builtin Tools для LLM

LLM имеет доступ к следующим инструментам (tools) для выполнения различных операций.

### code_review

Perform code review на репозитории. Анализирует git diff и возвращает findings с severity, title, message и suggestions.

```json
{
  "repo_name": "backend",
  "project_name": "my-project",
  "target": "HEAD",
  "base": "main"
}
```

### get_current_project

Получить информацию о текущем проекте сессии.

```json
{}
```

Возвращает: название проекта, путь, количество репозиториев, список репозиториев.

### list_project_repos

Список всех git репозиториев проекта.

```json
{
  "project_name": "my-project"
}
```

### get_repo_info

Детальная информация о репозитории.

```json
{
  "project_name": "my-project",
  "repo_name": "backend"
}
```

### read_file

Прочитать содержимое файла.

```json
{
  "file_path": "/path/to/file.py",
  "offset": 0,
  "limit": 500
}
```

### list_directory

Список файлов в директории.

```json
{
  "path": "/path/to/dir",
  "recursive": false,
  "max_depth": 3,
  "include_hidden": false
}
```

### grep_files

Поиск текста в файлах (regex).

```json
{
  "path": "/path/to/search",
  "pattern": "function_name",
  "file_glob": "*.py",
  "case_sensitive": false,
  "max_results": 100
}
```

### manageembeddings

Управление RAG индексами проекта.

```json
{
  "action": "list|create|delete|enable|disable",
  "project_name": "my-project",
  "index_name": "index-name"
}
```

## Code Review

### API Endpoint

```bash
POST /api/git/review
{
    "project": "my-project",
    "repo": "backend",
    "target": "feature-login",  # branch или commit
    "base": "main",             # base для diff (опционально)
    "commit": "abc123",         # конкретный коммит (опционально)
    "include_rag": true         # использовать RAG контекст
}
```

### Response

```json
{
    "review_id": "rev-12345678",
    "project": "my-project",
    "repo": "backend",
    "target": "feature-login",
    "summary": {
        "critical": 1,
        "major": 3,
        "minor": 5,
        "suggestions": 10
    },
    "findings": [
        {
            "file": "src/auth.py",
            "line": 42,
            "severity": "critical",
            "category": "security",
            "message": "SQL injection vulnerability",
            "suggestion": "Use parameterized query"
        }
    ],
    "created_at": "2026-03-31T12:00:00Z"
}
```

### CLI

```bash
# Review ветки
python main.py git review --project myproject --repo backend --target feature-login --base main

# Review конкретного коммита
python main.py git review --project myproject --repo backend --commit abc123

# Вывод в JSON
python main.py git review --project myproject --repo backend --target feature-login --format json
```

## MCP Git Server

### Конфигурация

```yaml
mcp:
  servers:
    git:
      type: stdio
      command: "/path/to/venv/bin/python"
      args: ["/path/to/synth-mcp-git/server.py"]
      env:
        ALLOWED_DIRS: "/home:/workspace:/projects"
        GIT_REPO_PATH: "/data/projects"
```

### Доступные инструменты

| Tool | Description |
|------|-------------|
| `git_clone` | Клонировать репозиторий |
| `git_fetch` | Fetch обновлений |
| `git_branch` | Текущая ветка |
| `git_list_branches` | Список веток |
| `git_status` | Статус репозитория |
| `git_diff` | Diff изменений |
| `git_log` | История коммитов |
| `git_show` | Информация о коммите |
| `git_checkout` | Checkout ветки |
| `git_remote_url` | Remote URL |
| `git_current_commit` | Текущий commit |

### Использование в чате

```
Проверь коммит abc123 в репозитории backend
/review backend feature-login vs main
```

## Автоматическое индексирование

При fetch репозитория:
1. Выполняется `git fetch`
2. Если `auto_index: true`, запускается переиндексация RAG
3. Документация репозитория индексируется в проектный RAG

## Безопасность

- SSH ключи шифруются с использованием Fernet (AES-128-CBC)
- Ключ шифрования генерируется из Machine ID + PBKDF2
- Файлы ключей (`*.key`, `*.salt`) хранятся в gitignore
- Агенты имеют доступ только к своим ключам

## Capabilities Агентов

Агенты могут иметь capabilities, которые определяют их специализацию:

```yaml
agents:
  developer:
    capabilities:
      - development
      - code_review
      - testing
  qa:
    capabilities:
      - testing
      - code_review
```

Code review автоматически выбирает агента с `code_review` capability.

## Файловая структура

```
synth/
├── app/
│   ├── ssh_key_manager.py       # Управление SSH ключами
│   ├── git_clone_service.py      # Git операции (clone, fetch, diff)
│   ├── git_repo_manager.py       # Реестр репозиториев
│   ├── handlers/
│   │   ├── code_review_handler.py  # Code review логика
│   │   └── chat_handler.py         # Slash commands
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── code_review.py          # code_review tool
│   │   ├── project.py              # project tools
│   │   └── filesystem.py           # filesystem tools
│   └── mcp/
│       └── processor.py            # Builtin tools integration
├── agents.yaml                    # Конфигурация агентов + SSH ключи
synth-mcp-git/
├── server.py                      # MCP Git сервер
└── requirements.txt
synth-mcp-tools/
└── server.py                      # MCP tools server
synth-cli/
└── main.py                       # CLI команды (git clone, git review)
data/
└── projects/
    └── {project}/
        ├── config.yaml            # git_repos: []
        └── repos/                 # Клонированные репозитории
            └── {repo}/
```

## Конфигурация

### synth/config.yaml

```yaml
mcp:
  servers:
    git:
      type: stdio
      command: "/path/to/venv/bin/python"
      args: ["/path/to/synth-mcp-git/server.py"]
      enabled_by_default: true
      env:
        ALLOWED_DIRS: "/home:/workspace:/projects"
        GIT_REPO_PATH: "/home/eof/dev/aic/t11/data/projects"
    synth-tools:
      type: stdio
      command: "/path/to/venv/bin/python"
      args: ["/path/to/synth-mcp-tools/server.py"]
      enabled_by_default: true
```
