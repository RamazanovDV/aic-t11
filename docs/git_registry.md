# Git Repository Registry & Code Review

## Обзор

Система управления Git репозиториями с возможностью клонирования, обновления и автоматического индексирования документации. Позволяет проводить code review с использованием RAG контекста из проекта.

## Архитектура

```
┌─────────────────────────────────────────────────────────────────────┐
│                        agents.yaml                                    │
│  agents.{agent}.ssh_keys[] → SSH ключи (encrypted)                 │
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
```

## SSH Keys

### Структура в agents.yaml

```yaml
agents:
  developer:
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
GET    /projects/{project}/git-repos                    - список репозиториев
POST   /projects/{project}/git-repos                    - добавить репозиторий
DELETE /projects/{project}/git-repos/{repo}             - удалить репозиторий
POST   /projects/{project}/git-repos/{repo}/fetch       - fetch + reindex
GET    /projects/{project}/git-repos/{repo}/info        - информация о репозитории
```

### CLI Commands

```bash
# Клонировать репозиторий
python main.py git clone --project myproject --url https://github.com/org/repo.git --branch main

# Список репозиториев
python main.py git list --project myproject

# Fetch обновлений
python main.py git fetch --project myproject --repo backend

# Удалить репозиторий
python main.py git remove --project myproject --repo backend --delete-local
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

## Файловая структура

```
synth/
├── app/
│   ├── ssh_key_manager.py       # Управление SSH ключами
│   ├── git_clone_service.py     # Git операции (clone, fetch, diff)
│   ├── git_repo_manager.py      # Реестр репозиториев
│   └── handlers/
│       └── code_review_handler.py  # Code review логика
├── agents.yaml                  # Конфигурация агентов + SSH ключи
synth-mcp-git/
├── server.py                    # MCP Git сервер
└── requirements.txt
synth-cli/
└── main.py                      # CLI команды (git clone, git review)
data/
└── projects/
    └── {project}/
        ├── config.yaml          # git_repos: []
        └── repos/              # Клонированные репозитории
            └── {repo}/
```
