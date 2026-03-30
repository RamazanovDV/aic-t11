# Project RAG - Retrieval-Augmented Generation для проектов

## Обзор

Project RAG позволяет Synth AI Agent работать с документацией проектов:
- **README файлы** - автоматическая индексация и поиск
- **docs/** - документация проекта
- **Схемы данных** - JSON Schema, YAML модели, types
- **API описания** - OpenAPI, Swagger, GraphQL

## Архитектура

```
┌──────────────────────────────────────────────────────────────┐
│                      Synth AI Agent                          │
├──────────────────────────────────────────────────────────────┤
│  Chat Handler                                                │
│  ├── /help <вопрос>    → Project RAG + MCP                  │
│  ├── /project <path>   → Индексация + Git                   │
│  ├── /index            → Переиндексация                     │
│  └── /git <command>    → Git MCP Tools                      │
├──────────────────────────────────────────────────────────────┤
│  Project RAG Module                                         │
│  ├── ProjectRAGIndexer    → Индексация документации         │
│  ├── ProjectRAGSearch    → Поиск по индексам               │
│  └── ProjectRAGManager   → Высокоуровневый API             │
├──────────────────────────────────────────────────────────────┤
│  MCP Servers                                               │
│  ├── synth-mcp-git     → Git: branch, files, diff, status │
│  └── synth-mcp-tools    → Search, summarize                │
└──────────────────────────────────────────────────────────────┘
```

## Команды

### /help <вопрос>

Отвечает на вопросы о проекте, используя документацию.

```
/help что это за проект?
/help как запустить приложение?
/help какие API endpoints есть?
```

**Пример использования:**
```bash
curl -X POST http://localhost:5000/api/chat \
    -H "Content-Type: application/json" \
    -H "X-API-Key: your-secret-api-key" \
    -d '{
        "message": "/help что это за проект?"
    }'
```

### /project <путь>

Подключает проект и автоматически индексирует документацию.

```
/project /home/user/my-project
/project /workspace/api-service
```

### /index

Переиндексирует документацию текущего проекта.

### /git <команда>

Выполняет git команду через MCP.

```
/git branch     → Показать текущую ветку
/git status     → Статус репозитория
/git diff       → Изменения
/git log        → История коммитов
```

## MCP Git Server

MCP сервер для работы с Git репозиториями.

### Установка

```bash
# Путь к серверу в config.yaml
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

### Доступные инструменты

| Инструмент | Описание |
|------------|--------|
| `git_branch` | Текущая ветка |
| `git_files` | Список файлов репозитория |
| `git_diff` | Diff изменений |
| `git_status` | Статус репозитория |
| `git_log` | История коммитов |
| `git_show` | Информация о коммите/файле |
| `git_list_branches` | Список веток |

## API Endpoints

### POST /api/project-rag/index

Индексировать документацию проекта.

```bash
curl -X POST http://localhost:5000/api/project-rag/index \
    -H "Content-Type: application/json" \
    -H "X-API-Key: your-secret-api-key" \
    -d '{
        "project_path": "/home/user/my-project"
    }'
```

**Response:**
```json
{
    "success": true,
    "project_path": "/home/user/my-project",
    "indexed": {
        "readme": 1,
        "docs": 15,
        "schemas": 3,
        "api": 1
    },
    "total": 20
}
```

### POST /api/project-rag/search

Поиск в документации проекта.

```bash
curl -X POST http://localhost:5000/api/project-rag/search \
    -H "Content-Type: application/json" \
    -H "X-API-Key: your-secret-api-key" \
    -d '{
        "project_path": "/home/user/my-project",
        "query": "authentication",
        "doc_types": ["readme", "docs", "api"],
        "limit": 5
    }'
```

### GET /api/project-rag/projects

Список проиндексированных проектов.

```bash
curl http://localhost:5000/api/project-rag/projects \
    -H "X-API-Key: your-secret-api-key"
```

### GET /api/project-rag/<project_path>/summary

Получить сводку по документации проекта.

```bash
curl http://localhost:5000/api/project-rag//home/user/my-project/summary \
    -H "X-API-Key: your-secret-api-key"
```

### POST /api/project-rag/help

Ответить на вопрос о проекте.

```bash
curl -X POST http://localhost:5000/api/project-rag/help \
    -H "Content-Type: application/json" \
    -H "X-API-Key: your-secret-api-key" \
    -d '{
        "project_path": "/home/user/my-project",
        "question": "Как настроить окружение?",
        "use_mcp": true
    }'
```

## Индексация

### Что индексируется

| Тип | Пути поиска |
|-----|------------|
| README | `README.md`, `README.rst`, `README.txt` |
| Docs | `docs/*.md`, `docs/**/*.md` |
| Schemas | `schemas/`, `models/`, `types/`, `*schema*.json` |
| API | `openapi.yaml`, `api.json`, `swagger.yaml` |

### Хранение индексов

```
data/project_rag/
├── readme_index.json    # Индекс README файлов
├── docs_index.json      # Индекс документации
├── schemas_index.json   # Индекс схем данных
└── api_index.json      # Индекс API описаний
```

## Интеграция с Git

При подключении проекта (/project):
1. Автоматически индексируется документация
2. Git репозиторий становится доступен через MCP
3. Команда /git использует synth-mcp-git сервер

### Пример workflow

```
1. /project /workspace/my-api
   → Подключение проекта
   → Индексация README, docs/, schemas/
   → Подключение Git MCP

2. /help как запустить API?
   → Поиск в индексах
   → Ответ на основе документации

3. /git status
   → Вызов git_git_status через MCP
   → Возврат статуса репозитория
```

## Конфигурация

### config.yaml

```yaml
# MCP Git Server
mcp:
  servers:
    git:
      type: stdio
      command: "python"
      args: ["/path/to/synth-mcp-git/server.py"]
      env:
        ALLOWED_DIRS: "/home:/workspace"
        GIT_REPO_PATH: "/workspace"

# Project RAG
project_rag:
  enabled: true
  auto_index_on_connect: true
  default_doc_types:
    - "readme"
    - "docs"
    - "schema"
    - "api"
```

## Известные ограничения

1. **Безопасность**: MCP git сервер запускается локально и требует настройки ALLOWED_DIRS
2. **Индексация**: Только текстовые файлы (.md, .txt, .rst, .json, .yaml)
3. **Git**: Требуется установленный git в системе
