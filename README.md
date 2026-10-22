# GigaChat Summary API

HTTP-сервис на FastAPI: принимает русский текст и возвращает краткое резюме через
GigaChat. При недоступности модели возвращает первые предложения исходного текста
с предупреждением. Успешные ответы кешируются.

## Запуск

Нужен Python 3.11+. Команды из корня проекта в PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
Copy-Item .env.example .env
```

В `.env` заполните `GIGACHAT_CREDENTIALS` — Authorization Key без префикса `Basic` —
и выберите доступную аккаунту `GIGACHAT_MODEL`. При необходимости укажите PEM-файл
доверенных CA в `GIGACHAT_CA_BUNDLE`; проверка TLS всегда включена.
[Инструкция GigaChat](https://developers.sber.ru/docs/ru/gigachain/tools/python/gigachat).

Запуск одной командой после установки:

```powershell
.\.venv\Scripts\python.exe -m task_ai_service
```

Swagger: <http://127.0.0.1:8000/docs>. Без ключа сервис работает через fallback.
На Linux/macOS используйте `python3` и `.venv/bin/python` вместо Windows-путей.

## API

| Метод и путь | Вход |
| --- | --- |
| `POST /process` | JSON: `text`, необязательный `max_sentences` |
| `POST /process/text?max_sentences=2` | Обычный текст UTF-8, `Content-Type: text/plain` |
| `GET /health` | Без тела; проверяет процесс, не доступность GigaChat |

Текст: 20–20000 символов; `max_sentences`: целое от 1 до 10, по умолчанию 3.
Пример JSON-запроса:

```json
{"text": "Команда завершила разработку сервиса.\n\nТесты прошли успешно.", "max_sentences": 2}
```

В JSON переносы внутри строки записываются как `\n`. Для вставки абзацев напрямую
используйте `/process/text` в Swagger или отправьте файл из PowerShell:

```powershell
curl.exe -i -X POST 'http://127.0.0.1:8000/process/text?max_sentences=2' `
  -H 'Content-Type: text/plain; charset=utf-8' `
  --data-binary '@docs/examples/success-request.txt'
```

Пример формата ответа:

```json
{
  "summary": "Разработка сервиса завершена, тесты прошли успешно.",
  "source": "gigachat",
  "cached": false,
  "warning": null,
  "request_id": "8a79fbc1-2924-4898-83db-837a5649024e"
}
```

HTTP 200 — ответ модели, кеш или fallback. Повтор успешного запроса возвращает
`cached=true`. При сбое модели возвращаются `source=fallback`, `cached=false`
и предупреждение в `warning`; такой результат не кешируется.
HTTP 422 — ошибка ввода (`error`, `details`, `request_id`); HTTP 500 — внутренняя ошибка.
Каждый ответ содержит заголовок `X-Request-ID`.

## Архитектура и конфигурация

| Компонент | Ответственность |
| --- | --- |
| `src/task_ai_service/api/` | HTTP API, валидация, статусы и request ID |
| `src/task_ai_service/services/` | Сценарий обработки и ограниченный TTL/LRU кеш |
| `src/task_ai_service/llm/` | System/user prompt, OAuth, вызов GigaChat и ошибки |
| `src/task_ai_service/postprocessing.py` | Нормализация и очистка результата, ограничения длины |
| `src/task_ai_service/config.py`, `config/` | Проверка настроек и профили dev/prod |

Вызовы провайдера ограничены таймаутами и общим дедлайном; временные ошибки
повторяются с ограниченным числом попыток. Кеш учитывает текст и параметры запроса,
имеет TTL и ограничение размера; хранится в памяти процесса. JSON-логи фиксируют
приём запроса, cache hit/miss, подготовку промпта, ответ модели и ошибки без текста
запросов и секретов. Переносы нормализуются в пробелы; локальный fallback извлекает
начало текста, а не формирует смысловое резюме.

Настройки и значения по умолчанию: [.env.example](.env.example). Приоритет:
переменные процесса → `.env` → `config/{APP_ENV}.env` → значения по умолчанию.
`APP_ENV=dev` включает Swagger и DEBUG-логи, `prod` отключает Swagger и использует INFO.
Модель, URL, таймауты, ретраи и кеш настраиваются переменными `GIGACHAT_*`, `LLM_*`,
`CACHE_*`. `.env`, ключи и сертификаты исключены из Git.

## Проверки

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pytest --cov=task_ai_service --cov-report=term-missing
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m build
```

GitHub Actions на push/PR устанавливает зависимости, запускает линтер, тесты,
сборку и проверку запуска установленного wheel на Python 3.11/3.12/3.13.
Ключ GigaChat для CI не нужен. [Результаты и скриншоты](TESTING.md).

Pull Request: [#1](https://github.com/abletable1/task-ai-service-2/pull/1).
[GitHub Actions](https://github.com/abletable1/task-ai-service-2/actions/runs/39839640601)
прошёл успешно.
