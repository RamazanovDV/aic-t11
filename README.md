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
- **Контекст** - Markdown-файлы подмешиваются в system prompt
- **Оптимизация контекста** - Суммаризация, скользящее окно, sticky notes
- **Сессии** - История хранится в файлах
- **Админ-панель** - Настройка провайдеров, контекста, API ключей
- **Debug режим** - Просмотр запросов и ответов LLM
- **Ветки и чекпоинты** - Экспериментировать с ответвлениями
- **Две панели** - Параллельные сессии в одном окне
- **Импорт/экспорт** - Сессии можно экспортировать и импортировать

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

Для режима **Sticky Notes** автоматически подключается `FACTS_EXTRACTION.md` с инструкцией для извлечения фактов.

### Оптимизация контекста

Synth поддерживает несколько стратегий оптимизации контекста:

1. **Нет** - Все сообщения отправляются модели
2. **Суммаризация** - Старые сообщения сжимаются в краткое резюме
3. **Скользящее окно** - Отправляются только N последних сообщений
4. **Sticky Notes** - Из диалога извлекаются ключевые факты, которые отправляются вместе с N последними сообщениями

## Структура проекта

```
synth/
├── synth/                  # Flask API (порт 5000)
│   ├── app/
│   ├── config.yaml
│   └── run.py
├── synth-ui/              # Web UI (порт 5001)
│   ├── app.py
│   ├── static/
│   ├── templates/
│   ├── config.yaml
│   └── run.py
├── synth-cli/             # CLI
│   ├── main.py
│   └── config.yaml
├── data/
│   ├── context/           # Markdown файлы для system prompt
│   └── sessions/          # Сессии
└── README.md
```

## Требования

- Python 3.13+
- Flask 3.1+
- PyYAML 6.0+
- Requests 2.32+
- Click 8.1+

## Лицензия

MIT
