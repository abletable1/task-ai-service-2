# Результаты тестирования

Проверено 22 октября 2026 года на Windows, Python 3.12.10.

## Сценарии и скриншоты

| Сценарий | Результат | Подтверждение |
| --- | --- | --- |
| Запуск сервиса | `Application startup complete`, адрес `127.0.0.1:8000` | [01-startup.png](docs/screenshots/01-startup.png) |
| Текст с абзацами → резюме GigaChat | HTTP 200, `source=gigachat`, `cached=false`, непустое резюме | [02-success.png](docs/screenshots/02-success.png) |
| Короткий текст `short` | HTTP 422, `string_too_short` | [03-validation.png](docs/screenshots/03-validation.png) |
| Запрос без ключа модели | HTTP 200, `source=fallback`, `cached=false`, предупреждение | [04-fallback.png](docs/screenshots/04-fallback.png) |
| Повтор успешного запроса | HTTP 200, то же резюме, `cached=true`, новый request ID | [05-cache.png](docs/screenshots/05-cache.png) |

Скриншоты получены при ручной работе с сервисом. Исходный текст успешного запроса:
[success-request.txt](docs/examples/success-request.txt). Команда отправки — в [README](README.md).
Для проверки кеша запрос повторяется без изменения текста в пределах TTL.

Для воспроизведения fallback запустите сервис в отдельном терминале:

```powershell
$env:PORT = '8001'
$env:GIGACHAT_CREDENTIALS = ' '
.\.venv\Scripts\python.exe -m task_ai_service
```

Пробел перекрывает ключ из `.env` только для этого процесса. Из другого терминала:

```powershell
curl.exe -i -X POST 'http://127.0.0.1:8001/process/text?max_sentences=2' `
  -H 'Content-Type: text/plain; charset=utf-8' `
  --data-binary '@docs/examples/paragraphs.txt'
```

После проверки остановите второй процесс через Ctrl+C и закройте его терминал.

## Автоматические проверки

| Проверка | Результат |
| --- | --- |
| Ruff: линтер и форматирование | Пройдено |
| pytest | 98 тестов пройдены, покрытие 99.45% |
| `pip check`, сборка wheel/sdist | Пройдено |
| Установка wheel в отдельное окружение и HTTP-запуск вне исходников | Пройдено: `/health` → 200, `/process` без ключа → fallback |

Тесты проверяют валидацию, абзацы, очистку ответа, OAuth, таймауты, сетевые ошибки,
ретраи, fallback, TTL/LRU кеш, конфигурацию, TLS и логи. Внешний API в тестах подменяется;
реальный вызов GigaChat подтверждён отдельным ручным сценарием выше.
Команды повторного запуска проверок приведены в [README](README.md).

## Самопроверка перед сдачей

- [x] Сервис запускается по README; настройки вынесены в окружение, секреты исключены из Git.
- [x] Успех, ошибка ввода, fallback и кеш проверены; скриншоты сохранены.
- [x] Линтер, тесты, сборка и запуск установленного пакета проходят.
- [ ] Оформленный PR и успешный запуск удалённого GitHub Actions подтверждены.
