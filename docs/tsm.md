# TSM (Task State Management)

## Обзор

TSM — это система управления состояниями задач, которая позволяет LLM отслеживать прогресс работы над задачей и переключаться между различными этапами.

## Состояния

```mermaid
stateDiagram-v2
    [*] --> conversation
    conversation --> planning : начало задачи
    planning --> execution : план одобрен
    execution --> validation : задача выполнена
    validation --> done : проверено
    validation --> execution : найдены проблемы
    execution --> planning : требуется пересмотр
    done --> [*]
    conversation --> [*]
```

| Состояние | Описание | Доступные переходы |
|----------|----------|-------------------|
| `conversation` | Свободный разговор | → `planning` |
| `planning` | Планирование задачи | → `execution` |
| `execution` | Выполнение задачи | → `validation`, → `planning` |
| `validation` | Проверка результатов | → `done`, → `execution` |
| `done` | Задача завершена | — |

## Режимы работы

### Simple (простой)
Базовый системный промпт с инструкцией по статусу задачи. Использует файл `STATUS_SIMPLE.md`.

```python
tsm_mode = session.session_settings.get("tsm_mode", "simple")
```

### Orchestrator (оркестратор)
Отдельный system prompt-оркестратор, который:
- Следит за общей картиной
- Запускает подзадачи (subtasks) с собственными промтами
- Координирует работу сабагентов

Использует файл `STATUS_ORCHESTRATOR.md`.

```python
# Пример ответа с подзадачами
{
    "status": {
        "task_name": "Создание API",
        "state": "execution",
        "subtasks": [
            {"id": "1", "name": "Создать модель", "prompt": "..."},
            {"id": "2", "name": "Создать эндпоинты", "prompt": "..."}
        ]
    }
}
```

### Deterministic (детерминированный)
Жёсткая проверка переходов между состояниями с валидацией:
- Проверка допустимости перехода
- Логирование переходов
- Обработка ошибок перехода

```python
# Валидация перехода
is_valid, error = validate_state_transition(current_state, new_state, task_name)
```

## JSON блок статуса

LLM возвращает статус в JSON блоке в конце ответа:

```json
{
    "status": {
        "task_name": "Название задачи",
        "state": "execution",
        "progress": "50%",
        "project": "Название проекта",
        "updated_project_info": "Обновлённое описание",
        "current_task_info": "Информация о текущей задаче",
        "approved_plan": "Одобренный план",
        "already_done": "Уже сделано",
        "currently_doing": "Сейчас делаю",
        "invariants": {
            "язык": "Python",
            "фреймворк": "Flask"
        },
        "schedule": {
            "type": "cron",
            "name": "Ежедневный отчёт",
            "cron": "0 9 * * *"
        }
    }
}
```

## Файлы промптов

| Файл | Использование |
|------|---------------|
| `STATUS_SIMPLE.md` | Простой режим |
| `STATUS_ORCHESTRATOR.md` | Режим оркестратора |
| `STATUS_ORCHESTRATOR_DEBUG.md` | Оркестратор с отладкой |
| `TSM_PLANNING.md` | Планирование |
| `TSM_EXECUTION.md` | Выполнение |
| `TSM_VALIDATION.md` | Проверка |
| `TSM_DONE.md` | Завершение |
| `SCHEDULER.md` | Планировщик |

## Конфигурация

### Установка режима

```python
from app import tsm

# Установить режим
tsm.set_tsm_mode(session, "orchestrator")

# Получить текущий режим
mode = tsm.get_tsm_mode(session)
```

### Получение промпта

```python
prompt = tsm.get_tsm_prompt(session)
```

## Пример работы

```python
# 1. Пользователь начинает задачу
session.status = {"task_name": "conversation", "state": None}

# 2. LLM возвращает новый статус
parsed_status = {
    "task_name": "Новая задача",
    "state": "planning"
}

# 3. Валидация перехода (deterministic mode)
parsed_status = tsm.process_state_transition(session, parsed_status)

# 4. Обновление статуса
session.update_status(parsed_status)

# 5. Результат
print(session.status)
# {'task_name': 'Новая задача', 'state': 'planning', ...}
```

## Диаграмма потока

```mermaid
sequenceDiagram
    participant U as User
    participant LLM as LLM
    participant S as Session
    participant T as TSM
    participant V as status_validator

    U->>LLM: Сообщение
    LLM-->>V: Ответ + JSON блок
    V->>T: Валидация статуса
    alt deterministic mode
        T->>T: Проверка перехода
        alt Переход валиден
            T->>S: update_status()
        else Переход невалиден
            T->>T: Логировать ошибку
            T->>S: Оставить старый state
        end
    else other modes
        T->>S: update_status()
    end
    S-->>U: Результат
```

## Интеграция с проектами

TSM автоматически связывается с системой проектов:

- `project` — название проекта из статуса
- `updated_project_info` — обновлённое описание проекта
- `current_task_info` — текущая задача проекта
- `invariants` — инварианты проекта (язык, фреймворк, ограничения)
- `schedule` — создание расписаний
