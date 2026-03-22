# Synth — описание проекта

## Общее представление

**Synth** — это многопользовательская AI-система с веб-интерфейсом и CLI для взаимодействия с большими языковыми моделями (LLM). Проект состоит из трёх основных компонентов:

| Компонент | Порт | Технология | Назначение |
|-----------|------|------------|------------|
| **synth** | 5000 | Flask | Backend API |
| **synth-ui** | 5001 | Flask + htmx | Веб-интерфейс |
| **synth-cli** | — | Click | Командная строка |

## Архитектура системы

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   User      │────▶│  synth-ui   │────▶│   synth     │
│  (Browser)  │◀────│  (:5001)    │◀────│   (:5000)   │
└─────────────┘     └─────────────┘     └─────────────┘
                                                  │
                                                  ▼
                                           ┌─────────────┐
                                           │   LLM       │
                                           │  Providers  │
                                           │(OpenAI,     │
                                           │ Anthropic,  │
                                           │ Ollama...)  │
                                           └─────────────┘
```

## Основные возможности

### 1. Управление сессиями
- Создание, сохранение и загрузка сессий чата
- Поддержка ветвления разговоров (branches) и чекпоинтов
- Контекстная оптимизация (sliding window, summarization, sticky notes)

### 2. Множественные LLM провайдеры
- OpenAI (GPT-4, GPT-4o, GPT-3.5)
- Anthropic (Claude)
- Ollama (локальные модели)
- MiniMax
- Возможность подключения любого OpenAI-совместимого API

### 3. Task State Management (TSM)
Система управления состоянием задач с тремя режимами:
- **simple** — базовый промпт с инструкцией по статусу
- **orchestrator** — оркестратор с поддержкой сабагентов
- **deterministic** — детерминированный переход между состояниями

Состояния: `planning` → `execution` → `validation` → `done`

### 4. MCP (Model Context Protocol)
- Подключение к MCP серверам для расширения функциональности
- Динамическая загрузка и вызов инструментов
- Поддержка stdio и SSE соединений

### 5. Проекты и планировщик
- Управление проектами с описанием, задачами и инвариантами
- Планировщик задач по cron
- автоматическое выполнение задач

### 6. Суммаризация
- Автоматическая суммаризация длинных разговоров
- Настраиваемые интервалы суммаризации

---

## Схемы обработки сообщений

### Non-Stream режим (`/chat`)

```
POST /chat
    │
    ▼
┌──────────────────────────────┐
│ 1. Валидация & Парсинг        │
└──────────────────────────────┘
    │
    ▼
┌──────────────────────────────┐
│ 2. Session Management        │
│    - add_user_message()      │
└──────────────────────────────┘
    │
    ▼
┌──────────────────────────────┐
│ 3. System Prompt Build       │
│    (profile + project +      │
│     status + interview)      │
└──────────────────────────────┘
    │
    ▼
┌──────────────────────────────┐
│ 4. RAG (если включен)        │
└──────────────────────────────┘
    │
    ▼
┌──────────────────────────────┐
│ 5. TSM Mode Check            │
└──────────────────────────────┘
    │
    ├─→ simple ──→ provider.chat()
    │                │
    │                ▼
    │            validate_status_block()
    │                │
    │                ▼
    │            save_session()
    │
    └─→ orchestrator ──→ tsm.process_orchestrator_response()
                            │
                            ▼
                        (iteration loop)
                            │
                            ├─→ detect subtasks
                            ├─→ run subagents
                            └─→ return final
```

### Stream режим (`/chat/stream`)

```
GET /chat/stream (SSE)
    │
    ▼
┌──────────────────────────────┐
│ 1-5. Same as Non-Stream      │
└──────────────────────────────┘
    │
    ├─→ simple ──→ provider.stream_chat()
    │                │
    │                ▼
    │            yield chunks (SSE)
    │                │
    │                ▼
    │            tool calls handling
    │
    └─→ orchestrator ──→ tsm.process_orchestrator_response()
                            │
                            ▼
                        progress_queue events
                            │
                            ▼
                        yield orchestrator_content
```

### Orchestrator Mode (детали)

```
tsm.process_orchestrator_response()
    │
    ▼
for iteration in range(max_iterations):
    │
    ├─→ 1. build_system_prompt()
    │
    ├─→ 2. provider.chat()
    │        └─→ capture_reasoning() ✓
    │
    ├─→ 3. validate_status_block()
    │
    ├─→ 4. extract subtasks
    │        │
    │        ├─→ no subtasks ──→ return final
    │        │
    │        └─→ has subtasks ──→ run subagents
    │                                │
    │                                ▼
    │                            continue loop
    │
    ▼
return {
    final_content,
    final_status,
    reasoning,       ✓
    usage,
    debug_info
}
```

### Архитектура компонентов

```
┌─────────────────────────────────────────────────────────────┐
│              RequestHandler (routes.py)                     │
│   - HTTP endpoints                                          │
│   - Валидация, маршрутизация                                 │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              ContextBuilder (context_builder.py)            │
│   - build_system_prompt()                                   │
│   - build_rag_context()                                     │
│   - build_mcp_tools()                                       │
│   - build_messages()                                        │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              OrchestrationController (orchestration.py)     │
│   - run_simple()                                            │
│   - run_simple_stream()                                     │
│   - run_orchestrator()                                      │
│   - save_response()                                         │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              LLMProvider (llm/providers.py)                 │
│   - chat()                                                  │
│   - stream_chat()                                           │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              SessionManager (session.py)                    │
│   - save/load, branches, checkpoints                       │
└─────────────────────────────────────────────────────────────┘
```

---

## Связанные документы

| Документ | Описание |
|----------|----------|
| [Архитектура и диаграммы](./architecture.md) | Полная диаграмма компонентов, классов и потоков данных |
| [API Endpoints](./api.md) | Описание всех REST API эндпоинтов |
| [Конфигурация](./configuration.md) | Настройка проекта, переменные окружения, структура данных |
| [MCP интеграция](./mcp.md) | Подключение внешних инструментов через MCP |
| [TSM система](./tsm.md) | Управление состояниями задач |
| [Память задачи](./tsm.md#память-задачи-task-memory) | Что пользователь уточнил, ограничения, цель диалога |
| [Embeddings и семантический поиск](./embeddings.md) | Создание индексов, RAG, стратегии чанкинга |
