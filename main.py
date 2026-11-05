from __future__ import annotations

import asyncio
import html
import logging
import os
import secrets
from typing import Optional

import aiosqlite
from aiocryptopay import AioCryptoPay, Networks
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from aiohttp import web

# ============================================================
#  НАСТРОЙКИ — берутся из переменных окружения Bothost
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or ""
CRYPTO_TOKEN = os.getenv("CRYPTO_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()]
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "saiber")

PORT = int(os.getenv("PORT", "3000"))
DOMAIN = os.getenv("DOMAIN", "").strip()
WEBHOOK_PATH = "/webhook"
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

# Абсолютные пути: код живёт в /app, постоянные данные — в /app/data
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.getenv("DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "shop.db")
PUBLIC_DIR = os.path.join(BASE_DIR, "public")

# Каталог мини-аппа: сначала public/, затем корень репозитория
if not os.path.exists(os.path.join(PUBLIC_DIR, "index.html")):
    if os.path.exists(os.path.join(BASE_DIR, "index.html")):
        PUBLIC_DIR = BASE_DIR

PHOTO_CANDIDATES = [
    os.path.join(BASE_DIR, "Admiral.jpg"),
    os.path.join(PUBLIC_DIR, "Admiral.jpg"),
    "https://noom123412.github.io/qweq/Admiral.jpg",
]

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

if not BOT_TOKEN:
    raise SystemExit(
        "❌ BOT_TOKEN не задан. Добавьте переменную окружения BOT_TOKEN в настройках бота на Bothost."
    )

# Таймауты: на Bothost внешняя сеть может тормозить — не зависаем навсегда
API_TIMEOUT = int(os.getenv("API_TIMEOUT", "20"))

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML"),
    request_timeout=API_TIMEOUT,
)

dp = Dispatcher(storage=MemoryStorage())

# Имя бота заполняется при старте (get_me), нужно для /health и логов
BOT_USERNAME = os.getenv("BOT_USERNAME", "")

crypto: Optional[AioCryptoPay] = None
if CRYPTO_TOKEN:
    crypto = AioCryptoPay(token=CRYPTO_TOKEN, network=Networks.MAIN_NET)
else:
    log.warning("CRYPTO_TOKEN не задан — оплата через CryptoBot работать не будет")


# ============================================================
#  БАЗА (только для заявок на оплату)
# ============================================================
async def db_init() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS topups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                invoice_id INTEGER,
                amount REAL,
                title TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_topups_user ON topups(user_id, status);
            """
        )
        await db.commit()
    log.info("БД готова: %s", DB_PATH)


async def db_create_topup(user_id: int, invoice_id: int, amount: float, title: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO topups (user_id, invoice_id, amount, title) VALUES (?, ?, ?, ?)",
            (user_id, invoice_id, amount, title),
        )
        await db.commit()
        return int(cur.lastrowid or 0)


async def db_get_topup(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM topups WHERE user_id = ? AND status = 'pending' "
            "ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        return await cur.fetchone()


async def db_get_topup_by_invoice(invoice_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM topups WHERE invoice_id = ? ORDER BY id DESC LIMIT 1",
            (invoice_id,),
        )
        return await cur.fetchone()


async def db_user_topups(user_id: int, limit: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM topups WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
        return await cur.fetchall()


async def db_set_topup_status(req_id: int, status: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE topups SET status = ? WHERE id = ?", (status, req_id))
        await db.commit()



async def photo_file() -> Optional[FSInputFile]:
    for path in PHOTO_CANDIDATES:
        if path.startswith("http"):
            continue
        if os.path.exists(path):
            return FSInputFile(path)
    return None


async def send_photo_msg(target: Message, text: str, kb=None):
    photo = await photo_file()
    if photo is not None:
        try:
            return await target.answer_photo(photo=photo, caption=text, reply_markup=kb)
        except Exception:
            log.exception("не удалось отправить фото, отправляю текст")
    return await target.answer(text, reply_markup=kb, disable_web_page_preview=True)


# ============================================================
#  ТОВАРЫ
# ============================================================
PRODUCTS = {
    "claude": {
        "name": "Claude",
        "emoji": "🤖",
        "desc": "Anthropic Claude — мощный AI-ассистент для кодинга, текстов и аналитики.",
        "plans": [
            {"code": "pro",   "title": "Pro",   "usd": 20,  "desc": "~45 сообщений за 5 часов, 200K контекст, приоритетный доступ."},
            {"code": "max",   "title": "Max",   "usd": 100, "desc": "5× больше лимитов Pro, до 1M контекста, Claude Code."},
            {"code": "ultra", "title": "Ultra", "usd": 200, "desc": "Без 5-часового лимита, для разработчиков и агентов."},
        ],
    },
    "chatgpt": {
        "name": "ChatGPT",
        "emoji": "💬",
        "desc": "OpenAI ChatGPT — лучший инструмент для повседневных задач.",
        "plans": [
            {"code": "go",       "title": "Go",       "usd": 8,   "desc": "Больше сообщений, расширенные лимиты, память, голос."},
            {"code": "plus",     "title": "Plus",     "usd": 20,  "desc": "GPT-6, Deep Research, Codex, кастомные GPT."},
            {"code": "pro",      "title": "Pro",      "usd": 100, "desc": "Максимум лимитов, GPT-6 Astra, агент dot."},
            {"code": "business", "title": "Business", "usd": 25,  "desc": "Для команд: SSO, аудит, безопасность."},
        ],
    },
    "gemini": {
        "name": "Gemini",
        "emoji": "✨",
        "desc": "Google Gemini — AI от Google с интеграцией в экосистему.",
        "plans": [
            {"code": "plus",  "title": "AI Plus",  "usd": 5,   "desc": "128K контекст, Flash, 400 ГБ облака."},
            {"code": "pro",   "title": "AI Pro",   "usd": 20,  "desc": "5 ТБ, 1M контекст, Gemini 4 Argon."},
            {"code": "ultra", "title": "AI Ultra", "usd": 100, "desc": "Максимум лимитов, Project Genie, Colab."},
        ],
    },
}

PERIODS = [
    {"code": "1m",  "title": "1 месяц",   "months": 1},
    {"code": "3m",  "title": "3 месяца",  "months": 3},
    {"code": "6m",  "title": "6 месяцев", "months": 6},
    {"code": "12m", "title": "1 год",     "months": 12},
]

USD_TO_RUB = int(os.getenv("USD_TO_RUB", "70"))


def get_price(usd: int, months: int) -> int:
    return round(usd * USD_TO_RUB * months)


STATUS_RU = {
    "pending": "⏳ ожидает оплаты",
    "paid": "✅ оплачено",
    "cancelled": "❌ отменён",
    "expired": "⌛ истёк",
}


# ============================================================
#  ВЕБ-СЕРВЕР (мини-апп + API + вебхук + health)
# ============================================================
async def index_page(request: web.Request) -> web.StreamResponse:
    p = os.path.join(PUBLIC_DIR, "index.html")
    if not os.path.exists(p):
        return web.Response(text="index.html не найден", status=404)
    return web.FileResponse(p, headers={"Cache-Control": "no-cache"})


async def health(request: web.Request) -> web.Response:
    """Простой health-check без обращений к Telegram API (чтобы не зависеть от сети)."""
    return web.json_response({
        "status": "ok",
        "bot": BOT_USERNAME,
        "webhook": bool(DOMAIN),
        "crypto": crypto is not None,
    })


async def wa_catalog(request: web.Request) -> web.Response:
    result = []
    for key, p in PRODUCTS.items():
        plans = []
        for plan in p["plans"]:
            plans.append({
                "code": plan["code"],
                "title": plan["title"],
                "desc": plan["desc"],
                "prices": {pd["code"]: get_price(plan["usd"], pd["months"]) for pd in PERIODS},
            })
        result.append({
            "key": key,
            "name": p["name"],
            "emoji": p["emoji"],
            "desc": p["desc"],
            "plans": plans,
        })
    return web.json_response({"products": result, "periods": PERIODS})


async def wa_buy(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "bad json"}, status=400)

    user_id = data.get("user_id")
    amount = data.get("amount")
    title = str(data.get("title", "Подписка"))[:100]

    if not user_id or not amount:
        return web.json_response({"error": "missing params"}, status=400)

    try:
        amount = int(round(float(amount)))
    except (TypeError, ValueError):
        return web.json_response({"error": "bad amount"}, status=400)

    if amount <= 0:
        return web.json_response({"error": "bad amount"}, status=400)

    if crypto is None:
        return web.json_response({"error": "Оплата временно недоступна"}, status=503)

    try:
        invoice = await crypto.create_invoice(
            amount=amount,
            fiat="RUB",
            currency_type="fiat",
            description=title,
            expires_in=3600,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("crypto error")
        return web.json_response({"error": f"Ошибка платёжной системы: {e}"}, status=502)

    await db_create_topup(int(user_id), int(invoice.invoice_id), amount, title)
    log.info("создан счёт %s на %s ₽ для %s", invoice.invoice_id, amount, user_id)
    return web.json_response({
        "pay_url": invoice.bot_invoice_url or invoice.mini_app_invoice_url,
        "invoice_id": invoice.invoice_id,
    })


async def wa_invoice_status(request: web.Request) -> web.Response:
    """Проверка статуса оплаты счёта (вызывается мини-аппом после возврата из CryptoBot)."""
    try:
        invoice_id = int(request.query.get("invoice_id", "0"))
    except ValueError:
        return web.json_response({"error": "bad invoice_id"}, status=400)

    if not invoice_id:
        return web.json_response({"error": "missing invoice_id"}, status=400)

    if crypto is None:
        return web.json_response({"status": "unknown"})

    try:
        invoices = await crypto.get_invoices(invoice_ids=invoice_id)
    except Exception as e:  # noqa: BLE001
        log.warning("не удалось проверить счёт %s: %s", invoice_id, e)
        return web.json_response({"status": "unknown"})

    if not invoices:
        return web.json_response({"status": "not_found"})

    inv = invoices[0]
    topup = await db_get_topup_by_invoice(invoice_id)
    if inv.status == "paid" and topup is not None and topup["status"] != "paid":
        await db_set_topup_status(int(topup["id"]), "paid")
        await notify_admins(topup)
    elif inv.status == "expired" and topup is not None and topup["status"] == "pending":
        await db_set_topup_status(int(topup["id"]), "expired")

    return web.json_response({"status": inv.status})


async def wa_static(request: web.Request) -> web.StreamResponse:
    name = request.match_info.get("name", "")
    name = os.path.basename(name)
    p = os.path.join(PUBLIC_DIR, name)
    if not os.path.isfile(p):
        raise web.HTTPNotFound()
    return web.FileResponse(p)


async def tg_webhook(request: web.Request) -> web.Response:
    if WEBHOOK_SECRET:
        token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not secrets.compare_digest(token, WEBHOOK_SECRET):
            log.warning("вебхук: неверный secret token")
            return web.Response(status=403)

    try:
        update = await request.json()
    except Exception:
        return web.Response(status=400)

    asyncio.create_task(dp.feed_webhook_update(bot, update))
    return web.Response(text="ok")


def build_app() -> web.Application:
    app = web.Application(client_max_size=1024 * 1024)
    app.router.add_get("/", index_page)
    app.router.add_get("/health", health)
    app.router.add_get("/api/catalog", wa_catalog)
    app.router.add_post("/api/buy", wa_buy)
    app.router.add_get("/api/invoice-status", wa_invoice_status)
    app.router.add_post(WEBHOOK_PATH, tg_webhook)
    app.router.add_get("/{name:[^{}/]+\\.(?:css|js|png|jpg|jpeg|gif|svg|ico|webp|json)}", wa_static)
    return app


async def run_webserver() -> None:
    app = build_app()
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info("🌐 веб-сервер слушает 0.0.0.0:%s (домен: %s)", PORT, DOMAIN or "не задан")


# ============================================================
#  БОТ
# ============================================================
def kb_open_app(user_id: int = 0) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🚀 Открыть магазин", web_app=WebAppInfo(url=webapp_url(user_id)))],
        [InlineKeyboardButton(text="🧾 Мои покупки", callback_data="my_orders")],
        [InlineKeyboardButton(text="🆘 Поддержка", url=f"https://t.me/{SUPPORT_USERNAME}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


WELCOME_TEXT = (
    "👋 <b>Admiral Shop</b> — премиум-подписки на AI-сервисы.\n\n"
    "🤖 Claude · 💬 ChatGPT · ✨ Gemini\n\n"
    "Нажми кнопку ниже, чтобы открыть каталог."
)


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await send_photo_msg(message, WELCOME_TEXT, kb_open_app(message.from_user.id))


@dp.message(Command("help", "support"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "🆘 <b>Поддержка</b>\n\n"
        f"Напиши нам: @{SUPPORT_USERNAME}\n\n"
        "Доступные команды:\n"
        "/start — открыть магазин\n"
        "/orders — мои заказы\n"
        "/id — мой Telegram ID"
    )


@dp.message(Command("id"))
async def cmd_id(message: Message) -> None:
    await message.answer(f"🆔 Ваш Telegram ID: <code>{message.from_user.id}</code>")


@dp.message(Command("orders"))
async def cmd_orders(message: Message) -> None:
    await send_orders(message.from_user.id, message)


@dp.callback_query(F.data == "my_orders")
async def cb_my_orders(call: CallbackQuery) -> None:
    await call.answer()
    await send_orders(call.from_user.id, call.message)


async def send_orders(user_id: int, target: Optional[Message]) -> None:
    if target is None:
        return
    rows = await db_user_topups(user_id)
    if not rows:
        await send_photo_msg(
            target,
            "🧾 <b>Мои покупки</b>\n\nУ вас пока нет заказов.\n"
            "Откройте магазин и выберите подписку.",
            kb_open_app(user_id),
        )
        return

    lines = ["🧾 <b>Мои покупки</b>\n"]
    for row in rows:
        status = STATUS_RU.get(row["status"], row["status"])
        title = html.escape(str(row["title"] or "Подписка"))
        date = str(row["created_at"] or "")[:16]
        lines.append(
            f"• <b>{title}</b>\n"
            f"  {int(row['amount'] or 0)} ₽ · {status}\n"
            f"  <i>{date}</i>"
        )
    text = "\n".join(lines)
    if len(text) > 3800:
        text = text[:3800] + "\n…"
    await target.answer(text, reply_markup=kb_open_app(user_id), disable_web_page_preview=True)



# ------------------------------------------------------------
#  Уведомление админов об оплате
# ------------------------------------------------------------
async def notify_admins(topup) -> None:
    if not ADMIN_IDS:
        return
    title = html.escape(str(topup["title"] or "Подписка"))
    text = (
        "💰 <b>Новая оплата</b>\n\n"
        f"Пользователь: <code>{topup['user_id']}</code>\n"
        f"Товар: {title}\n"
        f"Сумма: {int(topup['amount'] or 0)} ₽\n"
        f"Счёт: <code>{topup['invoice_id']}</code>"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception:  # noqa: BLE001
            log.warning("не удалось уведомить админа %s", admin_id)


# ------------------------------------------------------------
#  Фоновая проверка неоплаченных счетов
# ------------------------------------------------------------
async def poll_invoices_task() -> None:
    while True:
        try:
            await asyncio.sleep(60)
            if crypto is None:
                continue
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                cur = await db.execute(
                    "SELECT * FROM topups WHERE status = 'pending' ORDER BY id DESC LIMIT 50"
                )
                pending = await cur.fetchall()
            if not pending:
                continue
            invoices = await crypto.get_invoices(
                invoice_ids=[int(r["invoice_id"]) for r in pending if r["invoice_id"]]
            )
            by_id = {int(inv.invoice_id): inv for inv in invoices}
            for row in pending:
                inv = by_id.get(int(row["invoice_id"] or 0))
                if inv is None:
                    continue
                if inv.status == "paid":
                    await db_set_topup_status(int(row["id"]), "paid")
                    await notify_admins(row)
                elif inv.status == "expired":
                    await db_set_topup_status(int(row["id"]), "expired")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("ошибка фоновой проверки счетов")



# ============================================================
#  ЗАПУСК
# ============================================================
async def main() -> None:
    global BOT_USERNAME
    await db_init()
    me = await bot.get_me()
    BOT_USERNAME = me.username or BOT_USERNAME
    log.info("✅ Бот @%s запущен", BOT_USERNAME)

    await run_webserver()
    asyncio.create_task(poll_invoices_task())

    if DOMAIN:
        hook_url = f"{DOMAIN.rstrip('/')}{WEBHOOK_PATH}"
        await bot.set_webhook(
            url=hook_url,
            secret_token=WEBHOOK_SECRET or None,
            drop_pending_updates=True,
            allowed_updates=dp.resolve_used_update_types(),
        )
        log.info("🔗 вебхук установлен: %s", hook_url)
        while True:  # апдейты приходят на вебхук, процесс должен жить
            await asyncio.sleep(3600)

    # домен не задан — обычный polling (локальный запуск)
    await bot.delete_webhook(drop_pending_updates=True)
    log.info("📡 polling режим (домен не задан)")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("остановлено")

