# Руководство по Embeddings

Модуль семантического поиска и RAG (Retrieval-Augmented Generation) для Synth AI Agent.

## Возможности

- **Семантический поиск** - поиск по смыслу, а не по ключевым словам
- **RAG в чате** - добавление релевантного контекста к LLM-ответам
- **Несколько стратегий чанкинга** - фиксированный размер и структурный
- **Версионирование** - один name = новая версия
- **Оценка качества** - thumbs up/down для будущего анализа
- **Пагинация** - CLI читает файлы локально и отправляет батчами

## Архитектура

```
CLI (локально)              Backend (удаленно)
    |                              |
Читает файлы            ←      
Чанкует                          
    |                              |
Отправляет чанки      →      Создает эмбединги
                           Сохраняет индекс
```

CLI использует локальный chunker (аналогичный серверному), читает файлы с диска и отправляет на сервер батчами. Это позволяет создавать индексы из локальных файлов для удаленного бэкенда.

## Настройки провайдера и модели

Настройки провайдера и модели для эмбедингов задаются в админке и используются по умолчанию в CLI.

### Админка

1. http://localhost:5000/admin → вкладка "Эмбединги"
2. Вверху: выберите провайдер и модель → "Сохранить"
3. Эти настройки будут использоваться по умолчанию при создании индексов

### CLI

По умолчанию CLI использует настройки из конфига. Можно переопределить:

```bash
# Использовать настройки из конфига
python main.py embeddings create --name "My Index" --source ./docs

# Переопределить
python main.py embeddings create --name "My Index" --source ./docs --provider openai --model text-embedding-3-small
```

## Создание индекса

### CLI

```bash
# Создать индекс (CLI читает файлы локально)
python main.py embeddings create \
    --name "My Knowledge" \
    --source /path/to/docs \
    --strategy fixed \
    --chunk-size 50 \
    --overlap 5

# Создать с переопределением провайдера
python main.py embeddings create \
    --name "My Knowledge" \
    --source /path/to/docs \
    --provider openai \
    --model text-embedding-3-small
```

CLI автоматически:
1. Читает все `.md` файлы из указанной директории (рекурсивно)
2. Применяет чанкинг
3. Отправляет батчами на сервер (по 50 чанков по умолчанию)

### API

```bash
curl -X POST http://localhost:5000/api/embeddings \
    -H "Content-Type: application/json" \
    -H "X-API-Key: your-secret-api-key" \
    -d '{
        "name": "My Knowledge",
        "description": "База знаний компании",
        "source_dir": "/path/to/docs",
        "provider": "ollama",
        "model": "nomic-embed-text-v2-moe:latest",
        "chunking_strategy": "fixed",
        "chunking_params": {"chunk_size": 50, "overlap": 5}
    }'
```

## Поиск

### CLI

```bash
python main.py embeddings search "вопрос" --name "My Knowledge" --top-k 5
```

### API

```bash
curl -X POST http://localhost:5000/api/embeddings/search \
    -H "Content-Type: application/json" \
    -H "X-API-Key: your-secret-api-key" \
    -d '{
        "query": "вопрос",
        "index_name": "My Knowledge",
        "version": 1,
        "top_k": 5
    }'
```

## RAG в чате

### Выбор индекса и версии

В UI (чат):
1. Нажмите кнопку RAG (🔍)
2. Выберите индекс из списка
3. Выберите версию индекса
4. Настройте top_k
5. Сохраните

### API

```bash
curl -X POST http://localhost:5000/api/chat \
    -H "Content-Type: application/json" \
    -H "X-API-Key: your-secret-api-key" \
    -d '{
        "message": "Ваш вопрос",
        "use_rag": true,
        "rag_index_name": "My Knowledge",
        "rag_version": 1,
        "rag_top_k": 3
    }'
```

## Версионирование

При создании индекса с существующим именем создаётся новая версия:

```json
{
    "name": "My Knowledge",
    "version": 2
}
```

Поиск всегда использует последнюю версию (или указанную через `version`).

### API для версий

```bash
# Получить все версии индекса
curl http://localhost:5000/api/embeddings/by-name/My%20Knowledge \
    -H "X-API-Key: your-secret-api-key"
```

## Стратегии чанкинга

### Fixed (фиксированный размер)

Разбивает текст на чанки одинакового размера с перекрытием.

**Параметры:**

| Параметр | Тип | По умолчанию | Описание |
|----------|-----|--------------|----------|
| `chunk_size` | int | 50 | Размер чанка в токенах |
| `overlap` | int | 5 | Перекрытие между чанками в токенах |

**Рекомендации:**
- Малые размеры (10-25 токенов) - больше чанков, точнее поиск
- Средние (40-50) - баланс
- qwen3-embedding работает быстрее nomic

### Structure (структурный)

Разбивает текст по заголовкам Markdown (#, ##, ###).

**Параметры:**

| Параметр | Тип | По умолчанию | Описание |
|----------|-----|--------------|----------|
| `min_chunk_size` | int | 20 | Минимальный размер чанка |
| `max_chunk_size` | int | 150 | Максимальный размер чанка |
| `preserve_headers` | bool | true | Сохранять заголовки в чанках |

## Провайдеры

### Ollama

Модели:
- `qwen3-embedding:latest` - рекомендуется, быстрее
- `nomic-embed-text:latest` - легче, 768 измерений
- `nomic-embed-text-v2-moe:latest` - качественнее, но медленнее

**Ограничения:**
- Нестабильна с текстами > ~1500 символов ( small chunk_size!)
- При превышении возвращает 500 ошибку

**Рекомендуемые настройки:**
- chunk_size ≤ 50 для fixed
- max_chunk_size ≤ 150 для structure

### OpenAI

Модели: `text-embedding-3-small`, `text-embedding-ada-002`

```json
{
    "provider": "openai",
    "model": "text-embedding-3-small"
}
```

## CLI команды

```bash
# Создать индекс (чтение файлов локально, отправка батчами)
python main.py embeddings create \
    --name "Name" \
    --source ./docs \
    --strategy fixed \
    --chunk-size 50 \
    --batch-size 50

# Список индексов
python main.py embeddings list

# Информация об индексе
python main.py embeddings info <index_id>

# Поиск
python main.py embeddings search "query" --name "Name" --top-k 5

# Удалить индекс
python main.py embeddings delete <index_id>

# Оценить
python main.py embeddings rate <index_id> --thumbs-up
python main.py embeddings rate <index_id> --thumbs-down
```

## API Endpoints

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/embeddings` | Список всех индексов |
| GET | `/api/embeddings/by-name/<name>` | Все версии индекса |
| POST | `/api/embeddings` | Создать индекс |
| GET | `/api/embeddings/<id>` | Информация об индексе |
| DELETE | `/api/embeddings/<id>` | Удалить индекс |
| POST | `/api/embeddings/search` | Семантический поиск |
| POST | `/api/embeddings/<id>/rate` | Оценить (thumbs_up/thumbs_down) |
| GET | `/api/embeddings/config` | Настройки провайдеров и моделей |

## Структура хранения

```
data/embeddings/
├── index.json           # Список всех индексов
└── {index_id}/
    ├── config.json      # Параметры индекса
    ├── metadata.json    # Чанки с метаданными
    └── index.faiss      # FAISS индекс
```

## Метаданные чанка

Каждый чанк содержит:

| Поле | Описание |
|------|----------|
| `id` | UUID чанка |
| `content` | Текстовое содержимое |
| `source` | Путь к исходному файлу |
| `title` | Название файла |
| `section` | Заголовок раздела (для structure) |
| `chunk_index` | Номер чанка в документе |
| `total_chunks` | Всего чанков в документе |

## Примеры созданных индексов

| Индекс | Чанков | Модель |
|--------|--------|--------|
| Obsidian-Fixed-10-qwen | 2039 | qwen3-embedding:latest |
| Obsidian-Fixed-15-qwen | 1374 | qwen3-embedding:latest |
| Obsidian-Fixed-25-nomic | 848 | nomic-embed-text:latest |
| Obsidian-Fixed-40-nomic | 511 | nomic-embed-text:latest |
| Obsidian-Fixed-50-nomic | 416 | nomic-embed-text:latest |
| AI-Challenge-Fixed-15 | 530 | nomic-embed-text-v2-moe:latest |
| AI-Challenge-Fixed-25 | 322 | nomic-embed-text-v2-moe:latest |
| AI-Challenge-Fixed-40 | 191 | nomic-embed-text-v2-moe:latest |

## Админ-панель

В разделе "Эмбединги" админ-панели (http://localhost:5000/admin) можно:
- Настроить провайдер и модель по умолчанию
- Создать индекс (через форму)
- Просмотреть все индексы
- Удалить индексы
- Видеть статистику (количество чанков, файлов, оценки)

## Известные проблемы

1. **Ollama 500 errors** - при слишком больших чанках
   - Решение: используйте меньший chunk_size

2. **Версионирование при пагинации** - при использовании CLI с пагинацией версия определяется при первом батче

3. **Network timeout** - при большом количестве чанков возможны таймауты
   - Решение: уменьшите batch-size
