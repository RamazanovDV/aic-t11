# Synth Backend

Flask API сервер для Synth AI Agent.

## Возможности

- REST API для взаимодействия с LLM провайдерами
- Поддержка OpenAI, Anthropic, Ollama и кастомных OpenAI-совместимых провайдеров
- MCP (Model Context Protocol) - подключение внешних инструментов
- Управление сессиями с историей диалогов
- Контекстные файлы (Markdown), включая встроенные COMPANY.md, ABOUT.md, SOUL.md
- Оптимизация контекста: суммаризация, скользящее окно, sticky notes
- Scheduled tasks - запланированные задачи (cron/one-time)
- Real-time subagent progress через SSE
- Token limit handling (warning/abort)
- Ветки и чекпоинты
- Админ-панель
- Debug режим - сбор отладочной информации для каждого сообщения
- **Embeddings** - семантический поиск и RAG

## Установка

```bash
cd synth
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Настройка

```bash
cp config.example.yaml config.yaml
# Отредактируйте config.yaml, добавив API ключи
```

## Запуск

```bash
source venv/bin/activate
python run.py
```

Сервер запустится на http://localhost:5000

## API Endpoints

### Chat
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/health` | Проверка работоспособности |
| POST | `/api/chat` | Отправить сообщение |
| POST | `/api/chat/stream` | Streaming ответ |
| POST | `/api/chat/reset` | Сбросить историю |

### Sessions
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/sessions` | Список сессий |
| POST | `/api/sessions` | Создать сессию |
| GET | `/api/sessions/<id>` | Получить сессию |
| DELETE | `/api/sessions/<id>` | Удалить сессию |
| POST | `/api/sessions/<id>/rename` | Переименовать сессию |
| POST | `/api/sessions/<id>/copy` | Копировать сессию |
| POST | `/api/sessions/<id>/clear-debug` | Очистить debug данные |
| POST | `/api/sessions/export` | Экспорт сессий |
| POST | `/api/sessions/import` | Импорт сессий |

### Messages
| Метод | Путь | Описание |
|-------|------|----------|
| DELETE | `/api/sessions/<id>/messages/<index>` | Удалить сообщение |
| POST | `/api/sessions/<id>/messages/<index>/toggle` | Включить/выключить сообщение |
| GET | `/api/sessions/<id>/messages/<msg_id>/debug` | Получить debug информацию сообщения |

### Context
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/sessions/<id>/context-settings` | Настройки оптимизации контекста |
| POST | `/api/sessions/<id>/context-settings` | Сохранить настройки |
| POST | `/api/sessions/<id>/summarize` | Запустить суммаризацию |

### MCP
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/mcp/servers` | Список MCP серверов |
| GET | `/api/mcp/servers/<name>/tools` | Инструменты сервера |
| GET | `/api/sessions/<id>/mcp` | MCP серверы сессии |
| PUT | `/api/sessions/<id>/mcp` | Обновить MCP серверы |
| POST | `/api/sessions/<id>/mcp` | Добавить MCP сервер |
| DELETE | `/api/sessions/<id>/mcp/<name>` | Удалить MCP сервер |
| DELETE | `/api/sessions/<id>/mcp` | Очистить MCP серверы |

### Scheduled Tasks
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/schedules` | Список расписаний |
| POST | `/api/schedules` | Создать расписание |
| GET | `/api/schedules/<id>` | Получить расписание |
| PUT | `/api/schedules/<id>` | Обновить расписание |
| DELETE | `/api/schedules/<id>` | Удалить расписание |
| POST | `/api/schedules/<id>/enable` | Включить расписание |
| POST | `/api/schedules/<id>/disable` | Выключить расписание |
| GET | `/api/schedules/events` | SSE уведомления |

### Checkpoints
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/sessions/<id>/checkpoints` | Список чекпоинтов |
| POST | `/api/sessions/<id>/checkpoints` | Создать чекпоинт |
| POST | `/api/sessions/<id>/checkpoints/<cp_id>/rename` | Переименовать чекпоинт |
| DELETE | `/api/sessions/<id>/checkpoints/<cp_id>` | Удалить чекпоинт |
| POST | `/api/sessions/<id>/checkpoints/<cp_id>/branch` | Создать ветку из чекпоинта |

### Branches
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/sessions/<id>/branches` | Список веток |
| POST | `/api/sessions/<id>/branches/<branch_id>/switch` | Переключиться на ветку |
| POST | `/api/sessions/<id>/branches/<branch_id>/rename` | Переименовать ветку |
| DELETE | `/api/sessions/<id>/branches/<branch_id>` | Удалить ветку |
| POST | `/api/sessions/<id>/branches/<branch_id>/reset` | Сбросить ветку |
| GET | `/api/sessions/<id>/tree` | Дерево сессии |

### Admin
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/admin/config` | Получить конфиг |
| POST | `/admin/config` | Обновить конфиг |
| POST | `/admin/config/validate` | Валидировать конфиг |
| GET | `/admin/providers/<name>/models` | Модели провайдера |
| POST | `/admin/models/fetch` | Получить модели |
| POST | `/admin/providers/fetch-models` | Получить все модели |
| GET | `/admin/context` | Список контекстных файлов |
| POST | `/admin/context` | Добавить контекстный файл |
| POST | `/admin/context/enabled` | Включить/выключить контекст |
| GET/POST/DELETE | `/admin/context/<filename>` | Управление файлом |
| GET | `/admin/models` | Список моделей |
| GET | `/admin/models/available` | Доступные модели |
| POST | `/admin/models` | Добавить модель |
| DELETE | `/admin/models/<name>` | Удалить модель |

### Embeddings (Semantic Search)
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/embeddings` | Список индексов |
| POST | `/api/embeddings` | Создать индекс |
| GET | `/api/embeddings/<id>` | Информация об индексе |
| DELETE | `/api/embeddings/<id>` | Удалить индекс |
| POST | `/api/embeddings/search` | Семантический поиск |
| POST | `/api/embeddings/<id>/rate` | Оценить индекс |

Подробнее в [руководстве по индексам](./docs/EMBEDDINGS.md).

## Аутентификация

Используйте заголовок `X-API-Key` для авторизации.

## Конфигурация

См. `config.example.yaml` для доступных опций.

### MCP Configuration

```yaml
mcp:
  servers:
    filesystem:
      type: stdio
      command: "python"
      args: ["/path/to/mcp-filesystem/server.py"]
      env:
        ALLOWED_DIRS: "/home/user"
    brave-search:
      type: sse
      url: "http://localhost:3000/sse"
```

## Формат сессии

Сессии хранятся в JSON-файлах в директории `data/sessions/`.

### Структура (schema v1.0)

```json
{
  "schema_version": "1.0.0",
  "session_id": "string",
  "debug_enabled": true,
  "messages": [...],
  "created_at": "ISO8601",
  "updated_at": "ISO8601",
  "provider": "openai|anthropic|ollama|...",
  "model": "gpt-4|claude-3|...",
  "total_tokens": 0,
  "input_tokens": 0,
  "output_tokens": 0,
  "session_settings": {...},
  "branches": [...],
  "checkpoints": [...],
  "current_branch": "main",
  "status": {...},
  "owner_id": "user_id|null",
  "access": "owner|team|public"
}
```

### Message

| Поле | Тип | Описание |
|------|-----|----------|
| `role` | string | `system`, `user`, `assistant`, `error`, `note`, `info`, `summary` |
| `content` | string | Текст сообщения |
| `usage` | object | `{input_tokens, output_tokens, total_tokens}` |
| `model` | string? | Модель, сгенерировавшая сообщение |
| `created_at` | ISO8601 | Время создания |
| `disabled` | boolean | Исключено из LLM-контекста |
| `branch_id` | string | ID ветки (по умолчанию `main`) |
| `source` | string? | Источник: `web`, `cli` |
| `debug` | object? | Debug информация (null если выключено) |

### Settings (сессионные настройки)

```json
{
  "tsm_mode": "simple|orchestrator|deterministic",
  "context_optimization": "none|sliding_window|summarization|sticky_notes",
  "summarization_enabled": false,
  "summarize_after_n": 10,
  "summarize_after_minutes": 0,
  "summarize_context_percent": 0,
  "sliding_window_type": "messages|tokens",
  "sliding_window_limit": 10,
  "sticky_notes_limit": 6
}
```

### TSM Modes

| Mode | Описание |
|------|----------|
| `simple` | Базовый промт с инструкцией по статусу задачи |
| `orchestrator` | Оркестратор запускает subagent-задачи |
| `deterministic` | Детерминированный переход по states |

### Status (TSM state)

```json
{
  "task_name": "разговор на свободную тему",
  "state": "planning|execution|validation|done|null",
  "progress": "строка прогресса",
  "project": "название проекта",
  "subtasks": [...],
  "invariants": {...},
  "transition_log": [...]
}
```

### GraphSON Schema

Полная схема доступна в `schemas/session.json`. Валидация:

```bash
# Установить jsonschema
pip install jsonschema

# Валидировать файл
jsonschema -i data/sessions/mysession.json schemas/session.json
```

### Debug режим

Система сбора отладочной информации для диагностики работы LLM.

#### Включение/выключение

- **По умолчанию**: включён для новых сессий
- **Переключение**: через UI (галочка Debug) или API:
  ```bash
  # Включить
  curl -X POST http://localhost:5000/api/sessions/<id>/context-settings \
    -H "Content-Type: application/json" \
    -d '{"debug_enabled": true}'
  
  # Выключить
  curl -X POST http://localhost:5000/api/sessions/<id>/context-settings \
    -H "Content-Type: application/json" \
    -d '{"debug_enabled": false}'
  ```

#### Получение debug информации

```bash
# Через API
curl http://localhost:5000/api/sessions/<id>/messages/<msg_id>/debug
```

#### Структура debug данных

```json
{
  "api_request": {
    "url": "https://api.openai.com/v1/chat/completions",
    "method": "POST",
    "headers": {...},
    "body": {...}
  },
  "api_response": {...},
  "raw_model_response": "...",
  "reasoning": "...",
  "status": {...},
  "session": {
    "session_id": "...",
    "model": "gpt-4",
    "provider": "openai"
  },
  "subagents": [...],
  "mcp_calls": [...]
}
```

#### DebugCollector

Класс `DebugCollector` в `app/debug.py` отвечает за сбор отладочной информации:

```python
from app.debug import DebugCollector

# Создать из настроек сессии
dc = DebugCollector.from_session(session)

# Сбор данных
dc.capture_api_request(url, method, headers, body)
dc.capture_api_response(response)
dc.capture_reasoning(reasoning)
dc.capture_status(status)
dc.capture_session_info(session_id, model, provider)
dc.capture_mcp_call(tool, arguments, result, is_error)

# Получить результат
debug_info = dc.get_debug_info()  # None если debug выключен
```

### Legacy Fields

Поле `session_settings` считается устаревшим — используйте `settings`. При загрузке старых сессий выполняется автоматическая миграция.
