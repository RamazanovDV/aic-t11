# Synth MCP Tools

MCP-сервер с инструментами для работы с сессиями и проектами Synth.

## Инструменты

### search

Поиск текста в сессиях и проектах.

**Параметры:**
- `query` (required) - текст для поиска
- `scope` (optional) - область поиска: `all` | `sessions` | `projects` (по умолчанию `all`)
- `session_ids` (optional) - конкретные ID сессий для поиска

**Области поиска:**
- **sessions**: сообщения из сессий (без debug, usage, tool_use)
- **projects**: 
  - `info.md` - описание проекта
  - `current_task.md` - текущая задача
  - `schedules.yaml` - задания планировщика
  - `project_data/*` - пользовательские данные

### summarize

Суммаризация текста с использованием настроек суммаризатора из конфига Synth.

**Параметры:**
- `content` (required) - текст для суммаризации
- `max_length` (optional) - максимальное количество слов (по умолчанию 200)

### save_to_file

Сохранение контента в файл в директории `project_data` проекта.

**Параметры:**
- `project_name` (required) - имя проекта
- `filename` (required) - имя файла
- `content` (required) - содержание
- `mode` (optional) - режим записи: `overwrite` | `append` (по умолчанию `overwrite`)

**Ограничения:**
- Файлы сохраняются в `{data_dir}/projects/{project_name}/project_data/`
- Разрешённые расширения: `.json`, `.txt`, `.md`, `.yaml`, `.csv`

## Установка

```bash
cd synth-mcp-tools
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Конфигурация

Сервер автоматически ищет конфиг:
1. `T6_CONFIG_PATH` (переменная окружения)
2. `config.yaml` в директории с server.py
3. `../synth/config.yaml` (относительно server.py)

## Интеграция с Synth

Добавить в `synth/config.yaml`:

```yaml
mcp:
  servers:
    synth-tools:
      type: stdio
      command: "python"
      args: ["../synth-mcp-tools/server.py"]
```

## Запуск вручную

```bash
cd synth-mcp-tools
source venv/bin/activate
python server.py
```
