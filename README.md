# Admiral Shop — Telegram-бот + Mini App

Магазин подписок на AI-сервисы: бот на aiogram 3, мини-апп на HTML/JS, оплата через CryptoBot (Crypto Pay).
Бот и мини-апп запускаются **одним процессом** на Bothost: `main.py` поднимает aiohttp-сервер и Telegram-вебхук.

## Структура

```
.
├── main.py            # бот + веб-сервер (miniapp, API, /webhook, /health)
├── index.html         # сам мини-апп
├── requirements.txt   # зависимости Python
├── Dockerfile         # сборка для Bothost
└── .env.example       # список переменных окружения
```

## Переменные окружения (Bothost → бот → «Переменные»)

| Переменная | Обязательно | Описание |
|---|---|---|
| `BOT_TOKEN` | да | токен от @BotFather (Bothost подставляет сам) |
| `CRYPTO_TOKEN` | да | токен Crypto Pay (@CryptoBot → Crypto Pay → Create App) |
| `DOMAIN` | да | домен бота, напр. `https://bot-1793892401-9155-noom.bothost.tech` (Bothost подставляет сам) |
| `WEBHOOK_SECRET` | рекомендуется | случайная строка для проверки вебхука |
| `ADMIN_IDS` | нет | ID админов через запятую — им приходят уведомления об оплате |
| `SUPPORT_USERNAME` | нет | ник поддержки без @ (по умолчанию `saiber`) |
| `USD_TO_RUB` | нет | курс для расчёта цены (по умолчанию 70) |
| `PORT` | нет | порт сервера, по умолчанию 3000 (на Bothost приходит автоматически) |
| `DATA_DIR` | нет | каталог для SQLite, по умолчанию `/app/data` |

## Настройки в панели Bothost

1. **Домен** → «Использовать свой домен» (включено), поле домена пустое (выдастся автоматический), **Порт: 3000**.
2. **Запуск** → «Главный файл»: `main.py`
3. **Репозиторий** → `https://github.com/nOOM123412/qweq.git`, ветка `main` → «Сохранить и пересобрать».
4. **Переменные** → `DATA_DIR=/app/data`, при желании `CRYPTO_TOKEN`, `ADMIN_IDS`, `WEBHOOK_SECRET`.
5. Свой `Dockerfile` не включать — используется Dockerfile из репозитория.

## Проверка после деплоя

- `https://<домен>/health` → `{"status":"ok","bot":"@..."}`
- `https://api.telegram.org/bot<ТОКЕН>/getWebhookInfo` → `url` = `https://<домен>/webhook`, без ошибок
- `/start` в боте → сообщение с кнопкой «Открыть магазин»

## Локальный запуск

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # заполнить BOT_TOKEN и CRYPTO_TOKEN
set -a && source .env && set +a
python main.py         # без DOMAIN работает polling, мини-апп на http://localhost:3000
```
