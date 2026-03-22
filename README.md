# Synth AI Agent

Прототип многопользовательского ИИ-агента для командной работы.

## Назначение

Synth предназначен для команд разработки и помогает:

- **Разработчикам** - писать код по единым стандартам и спецификациям
- **DevOps-инженерам** - разворачивать приложения
- **Администраторам** - администрировать инфраструктуру и прикладное ПО
- **Аналитикам** - писать документацию
- **Специалистам по безопасности** - проводить аудит
- **Тестировщикам** - планировать и проводить тесты

## Компоненты

- **synth** - Flask API сервер (порт 5000)
- **synth-ui** - Веб-интерфейс (htmx + CSS) (порт 5001)
- **synth-cli** - Командная строка

## Возможности

- **Множественные провайдеры** - OpenAI, Anthropic, Ollama, кастомные OpenAI-совместимые
- **MCP (Model Context Protocol)** - подключение внешних инструментов через MCP серверы
- **Контекст** - Markdown-файлы подмешиваются в system prompt
- **Default context files** - встроенные файлы COMPANY.md, ABOUT.md, SOUL.md (включены по умолчанию)
- **3-уровневая память** - Краткосрочная (диалог), рабочая (текущая задача), долговременная (проект)
- **TSM (Task State Machine)** - 3 режима работы: Simple Prompt, Orchestrator (подзадачи), Deterministic (жёсткая валидация)
- **Система проектов** - Проекты хранятся в `data/projects/<project_name>/`
- **Статус задачи** - Модель возвращает статус в JSON-блоке, валидация с retry до 3 раз
- **Профиль пользователя** - Данные пользователя (имя, роль, отметки) передаются модели
- **Оптимизация контекста** - Суммаризация, скользящее окно
- **Сессии** - История хранится в файлах
- **Админ-панель** - Настройка провайдеров, контекста, API ключей
- **Debug режим** - Просмотр запросов и ответов LLM
- **Ветки и чекпоинты** - Экспериментировать с ответвлениями
- **Две панели** - Параллельные сессии в одном окне
- **Импорт/экспорт** - Сессии можно экспортировать и импортировать
- **Scheduled tasks** - Запланированные задачи (cron/one-time) с уведомлениями через SSE
- **Token limits** - Warning при 80%, abort при 95% от лимита токенов

## Быстрый старт

### 1. Установка зависимостей

```bash
# Synth (Backend)
cd synth
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Synth UI
cd ../synth-ui
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Synth CLI
cd ../synth-cli
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Настройка

```bash
cp synth/config.example.yaml synth/config.yaml
cp synth-ui/config.example.yaml synth-ui/config.yaml
cp synth-cli/config.example.yaml synth-cli/config.yaml
# Отредактируйте config.yaml, добавив API ключи
```

### 3. Запуск

```bash
# Terminal 1 - Synth Backend (порт 5000)
cd synth && source venv/bin/activate && python run.py

# Terminal 2 - Synth UI (порт 5001)
cd synth-ui && source venv/bin/activate && python run.py
```

### 4. Использование

- **Web UI**: http://localhost:5001
- **Админ-панель**: http://localhost:5000/admin
- **CLI**: см. документацию synth-cli

## Конфигурация

См. `config.example.yaml` в каждом компоненте для доступных опций.

### Контекстные файлы

Создайте Markdown-файлы в директории `data/context/`. Управление какими файлами включать в system prompt осуществляется через конфигурацию.

По умолчанию доступны встроенные файлы:
- `COMPANY.md` - Информация о компании
- `ABOUT.md` - Описание продукта/проекта
- `SOUL.md` - Ценности и принципы работы

Эти файлы включены по умолчанию, управление через админ-панель.

### 3-уровневая память

Synth использует трёхуровневую систему памяти:

1. **Краткосрочная память** - Текущий диалог (сообщения в сессии)
2. **Рабочая память** - Текущая задача (`status.current_task_info` сохраняется в `data/projects/<project>/current_task.md`)
3. **Долговременная память** - Профиль пользователя и описание проекта

### Профиль пользователя

При каждом запросе модели передаётся информация о пользователе:
- Имя (из профиля пользователя)
- Роль на проекте (team_role)
- Особые отметки (notes)

### Система проектов

Проекты хранятся в директории `data/projects/<project_name>/`:
- `info.md` - Описание проекта, участники, технологии, знания и решения
- `current_task.md` - Текущая задача по проекту

Модель возвращает статус с полями:
- `project` - Название проекта
- `updated_project_info` - Обновлённое описание проекта (сохраняется в `info.md`)
- `current_task_info` - Текущая задача (сохраняется в `current_task.md`)

### Оптимизация контекста

Synth поддерживает несколько стратегий оптимизации контекста:

1. **Нет** - Все сообщения отправляются модели
2. **Суммаризация** - Старые сообщения сжимаются в краткое резюме
3. **Скользящее окно** - Отправляются только N последних сообщений

## Структура проекта

```
synth/
├── synth/                  # Flask API (порт 5000)
│   ├── app/
│   │   ├── routes.py           # HTTP endpoints
│   │   ├── session.py          # Session & SessionManager
│   │   ├── tsm.py              # Orchestrator mode
│   │   ├── orchestration.py    # OrchestrationController (NEW)
│   │   ├── context_builder.py  # ContextBuilder (NEW)
│   │   ├── handlers/           # Request handlers (NEW)
│   │   │   ├── base.py
│   │   │   ├── chat_handler.py
│   │   │   ├── stream_handler.py
│   │   │   └── session_handler.py
│   │   ├── llm/
│   │   │   ├── base.py         # BaseProvider, LLMResponse
│   │   │   ├── providers.py    # OpenAI, Anthropic, Ollama
│   │   │   └── client.py       # LLMClient, PromptBuilder
│   │   ├── storage.py          # FileStorage
│   │   ├── debug.py           # DebugCollector
│   │   └── config.py
│   ├── config.yaml
│   └── run.py
├── synth-ui/              # Web UI (порт 5001)
├── synth-cli/             # CLI
├── docs/                  # Документация
│   ├── README.md          # Этот файл с схемами
│   └── architecture.md    # Архитектурные диаграммы
├── data/
│   ├── context/           # Markdown файлы для system prompt
│   ├── projects/         # Проекты и их описание
│   └── sessions/          # Сессии
└── README.md
```

## Архитектурные схемы

Полные схемы обработки сообщений доступны в [docs/README.md](./docs/README.md):

- [Non-Stream режим](./docs/README.md#non-stream-режим-chat)
- [Stream режим](./docs/README.md#stream-режим-chatstream)
- [Orchestrator Mode](./docs/README.md#orchestrator-mode-детали)
- [Архитектура компонентов](./docs/README.md#архитектура-компонентов)

### Быстрый обзор архитектуры

```
┌─────────────────────────────────────────────┐
│ RequestHandler (routes.py)                  │
│   - /chat, /chat/stream endpoints           │
└────────────────────┬────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────┐
│ ContextBuilder (context_builder.py)          │
│   - System prompt + RAG + MCP               │
└────────────────────┬────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────┐
│ OrchestrationController (orchestration.py)  │
│   - Simple / Orchestrator modes             │
└────────────────────┬────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────┐
│ LLMProvider (llm/providers.py)              │
│   - OpenAI, Anthropic, Ollama               │
└────────────────────┬────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────┐
│ SessionManager (session.py)                  │
│   - Persistence + branches + checkpoints    │
└─────────────────────────────────────────────┘
```

## API Endpoints

### Chat
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/chat` | Send a message |
| POST | `/api/chat/stream` | Stream response |
| POST | `/api/chat/reset` | Reset session |

### Sessions
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/sessions` | List all sessions |
| POST | `/api/sessions` | Create session |
| GET | `/api/sessions/<id>` | Get session |
| DELETE | `/api/sessions/<id>` | Delete session |
| POST | `/api/sessions/<id>/rename` | Rename session |
| POST | `/api/sessions/<id>/copy` | Copy session |
| POST | `/api/sessions/<id>/clear-debug` | Clear debug info |
| POST | `/api/sessions/export` | Export session |
| POST | `/api/sessions/import` | Import session |

### Messages
| Method | Endpoint | Description |
|--------|----------|-------------|
| DELETE | `/api/sessions/<id>/messages/<index>` | Delete message |
| POST | `/api/sessions/<id>/messages/<index>/toggle` | Toggle message |

### Context
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/sessions/<id>/context-settings` | Get context settings |
| POST | `/api/sessions/<id>/context-settings` | Update context settings |
| POST | `/api/sessions/<id>/summarize` | Summarize messages |

### MCP
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/mcp/servers` | List MCP servers |
| GET | `/api/mcp/servers/<name>/tools` | Get server tools |
| GET | `/api/sessions/<id>/mcp` | Get session MCP servers |
| PUT | `/api/sessions/<id>/mcp` | Update session MCP servers |
| POST | `/api/sessions/<id>/mcp` | Add MCP server to session |
| DELETE | `/api/sessions/<id>/mcp/<name>` | Remove MCP server |
| DELETE | `/api/sessions/<id>/mcp` | Clear session MCP servers |

### Scheduled Tasks
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/schedules` | List all schedules |
| POST | `/api/schedules` | Create schedule |
| GET | `/api/schedules/<id>` | Get schedule |
| PUT | `/api/schedules/<id>` | Update schedule |
| DELETE | `/api/schedules/<id>` | Delete schedule |
| POST | `/api/schedules/<id>/enable` | Enable schedule |
| POST | `/api/schedules/<id>/disable` | Disable schedule |
| GET | `/api/schedules/events` | SSE for task notifications |

### TSM (Task State Machine)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/sessions/<id>/tsm-settings` | Get TSM settings |
| POST | `/api/sessions/<id>/tsm-settings` | Update TSM settings |

### Checkpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/sessions/<id>/checkpoints` | List checkpoints |
| POST | `/api/sessions/<id>/checkpoints` | Create checkpoint |
| POST | `/api/sessions/<id>/checkpoints/<cp_id>/rename` | Rename checkpoint |
| DELETE | `/api/sessions/<id>/checkpoints/<cp_id>` | Delete checkpoint |
| POST | `/api/sessions/<id>/checkpoints/<cp_id>/branch` | Branch from checkpoint |

### Branches
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/sessions/<id>/branches` | List branches |
| POST | `/api/sessions/<id>/branches/<branch_id>/switch` | Switch branch |
| POST | `/api/sessions/<id>/branches/<branch_id>/rename` | Rename branch |
| DELETE | `/api/sessions/<id>/branches/<branch_id>` | Delete branch |
| POST | `/api/sessions/<id>/branches/<branch_id>/reset` | Reset branch |
| GET | `/api/sessions/<id>/tree` | Get session tree |

### Admin
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/admin/config` | Get config |
| POST | `/admin/config` | Update config |
| POST | `/admin/config/validate` | Validate config |
| GET | `/admin/providers/<name>/models` | Get provider models |
| POST | `/admin/models/fetch` | Fetch models |
| POST | `/admin/providers/fetch-models` | Fetch all models |
| GET | `/admin/context` | List context files |
| POST | `/admin/context` | Add context file |
| POST | `/admin/context/enabled` | Toggle context |
| GET/POST/DELETE | `/admin/context/<filename>` | Manage context file |
| GET | `/admin/models` | List models |
| GET | `/admin/models/available` | Available models |
| POST | `/admin/models` | Add model |
| DELETE | `/admin/models/<name>` | Delete model |

## Требования

- Python 3.13+
- Flask 3.1+
- PyYAML 6.0+
- Requests 2.32+
- Click 8.1+

## Лицензия

MIT
