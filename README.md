# Raise Store — Telegram-бот + Mini App

Магазин подписок на AI-сервисы: бот на aiogram 3, мини-апп на HTML/JS, оплата через CryptoBot (Crypto Pay).
Бот и мини-апп запускаются **одним процессом** на Bothost: `main.py` поднимает aiohttp-сервер и Telegram-вебхук.

## Интерфейс

- **Бот (`/start`)** — одно сообщение с единственной кнопкой «🛍 Открыть Raise Store». Никаких кнопок поддержки и истории покупок.
- **Мини-апп** — нижний хотбар «стекло» в стиле iOS (`backdrop-filter: blur + saturate`) с тремя вкладками:
  1. **Главная** — информация о магазине и ровно две кнопки: «Отзывы (317)» и «Поддержка».
  2. **Магазин** — каталог товаров (Claude / ChatGPT / Gemini) с выбором периода и оплатой.
  3. **Поддержка** — окно с полем ввода: сообщение уходит админу в Telegram, ответ приходит пользователю в чат бота.

### Как работает поддержка

```
мини-апп (форма)  →  POST /api/support  →  SQLite (таблица tickets)  →  сообщение админам из ADMIN_IDS
                                                                             ↓ ответ реплаем
пользователь в чате бота  ←  bot.send_message  ←  обработчик on_private_message (админ)
```

Любое обычное сообщение в ЛС бота от пользователя тоже считается обращением в поддержку (антифлуд — 20 секунд).

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
| `ADMIN_IDS` | **да, для поддержки** | ID админов через запятую — им приходят обращения в поддержку и уведомления об оплате |
| `SUPPORT_USERNAME` | нет | ник поддержки без @ (по умолчанию `saiber`) |
| `USD_TO_RUB` | нет | курс для расчёта цены (по умолчанию 70) |
| `PORT` | нет | порт сервера, по умолчанию 3000 (на Bothost приходит автоматически) |
| `DATA_DIR` | нет | каталог для SQLite, по умолчанию `/app/data` |

> ⚠️ Если `ADMIN_IDS` не задан, обращения из формы поддержки сохраняются в БД, но админам не отправляются.

## Настройки в панели Bothost

1. **Домен** → «Использовать свой домен» (включено), поле домена пустое (выдастся автоматический), **Порт: 3000**.
2. **Запуск** → «Главный файл»: `main.py`
3. **Репозиторий** → `https://github.com/nOOM123412/qweq.git`, ветка `main` → «Сохранить и пересобрать».
4. **Переменные** → `DATA_DIR=/app/data`, `ADMIN_IDS=<ваш id>`, при желании `CRYPTO_TOKEN`, `WEBHOOK_SECRET`.
5. Свой `Dockerfile` не включать — используется Dockerfile из репозитория.

> Важно: сохранение переменных на Bothost **не пересобирает** контейнер — после сохранения нажмите кнопку пересборки (`updateBot`) на дашборде.

## API

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/` | мини-апп |
| GET | `/health` | `{"status":"ok","bot":"...","webhook":true,"crypto":true}` |
| GET | `/api/catalog` | товары, тарифы и цены |
| POST | `/api/buy` | `{user_id, amount, title}` → счёт CryptoBot (`pay_url`) |
| GET | `/api/invoice-status?invoice_id=` | статус оплаты счёта |
| POST | `/api/support` | `{user_id, text, username, name}` → `{ok:true, ticket_id}` |
| POST | `/webhook` | Telegram webhook (проверка `X-Telegram-Bot-Api-Secret-Token`) |

## Проверка после деплоя

- `https://<домен>/health` → `{"status":"ok","bot":"@...","crypto":true}`
- `https://api.telegram.org/bot<ТОКЕН>/getWebhookInfo` → `url` = `https://<домен>/webhook`, без ошибок
- `/start` в боте → сообщение с единственной кнопкой «Открыть Raise Store»
- В мини-аппе: 3 вкладки в стеклянном хотбаре, на главной — кнопки «Отзывы (317)» и «Поддержка»
- Отправить тестовое сообщение в форме поддержки → оно придёт админам из `ADMIN_IDS`; ответить реплаем → текст придёт пользователю в чат бота

## Команды бота

| Команда | Действие |
|---|---|
| `/start` | приветствие + кнопка магазина |
| `/orders` | мои заказы |
| `/support` | краткая справка по поддержке |
| `/help` | список команд |
| `/id` | ваш Telegram ID |

## Локальный запуск

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # заполнить BOT_TOKEN и CRYPTO_TOKEN
set -a && source .env && set +a
python main.py         # без DOMAIN работает polling, мини-апп на http://localhost:3000
```

