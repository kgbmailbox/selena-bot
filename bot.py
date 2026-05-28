import os
import logging
import sqlite3
from datetime import datetime, timedelta
from groq import Groq
from telegram import Update, LabeledPrice, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    PreCheckoutQueryHandler, CallbackQueryHandler,
    filters, ContextTypes
)
from pdf_report import generate_pdf_report

# ── Ключи из переменных окружения ──
TELEGRAM_TOKEN    = os.environ["TELEGRAM_TOKEN"]
GROQ_API_KEY      = os.environ["GROQ_API_KEY"]
PAYMENT_PROVIDER  = os.environ["PAYMENT_PROVIDER_TOKEN"]  # от @BotFather → Payments

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

client = Groq(api_key=GROQ_API_KEY)
MODEL  = "llama-3.3-70b-versatile"

# ── Тарифы (цены в копейках / звёздах) ──
PLANS = {
    "sub_month": {
        "title": "⭐ Подписка на месяц",
        "description": "Безлимитные вопросы Селене на 30 дней",
        "price": 39900,   # 399 руб
        "days": 30,
        "label": "Подписка 30 дней — 399 ₽",
    },
    "report_numerology": {
        "title": "🔢 Нумерологический портрет",
        "description": "Полный PDF-отчёт по дате рождения: число жизненного пути, судьбы, личности",
        "price": 49000,   # 490 руб
        "days": 0,
        "label": "Нумерология PDF — 490 ₽",
    },
    "report_compatibility": {
        "title": "💞 Совместимость партнёров",
        "description": "PDF-анализ совместимости двух людей по нумерологии и астрологии",
        "price": 39000,   # 390 руб
        "days": 0,
        "label": "Совместимость PDF — 390 ₽",
    },
    "report_year": {
        "title": "🌙 Прогноз на год",
        "description": "Астрологический и нумерологический прогноз на текущий год",
        "price": 79000,   # 790 руб
        "days": 0,
        "label": "Прогноз на год PDF — 790 ₽",
    },
}

FREE_LIMIT = 3   # бесплатных вопросов в день

SYSTEM_PROMPT = """Ты — Селена, мудрый консультант, объединяющий психологию, нумерологию и астрологию.
Говори по-русски, мягко, глубоко и образно.

Что ты умеешь:
- Нумерологический портрет по дате рождения
- Психологический анализ личности и паттернов
- Астрологические влияния: знак зодиака, планеты
- Помощь в вопросах отношений и выбора пути

Правила:
- Всегда спрашивай имя и дату рождения для персонального анализа
- Используй символы 🌙 ✨ 🔮 ⭐ умеренно
- Каждый ответ содержит конкретный инсайт"""

histories: dict[int, list] = {}
MAX_HISTORY = 20

# ── База данных ──
def init_db():
    conn = sqlite3.connect("selena.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        sub_until TEXT,
        questions_today INTEGER DEFAULT 0,
        last_question_date TEXT,
        name TEXT,
        birthdate TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        plan TEXT,
        amount INTEGER,
        date TEXT
    )""")
    conn.commit()
    conn.close()

def get_user(user_id: int) -> dict:
    conn = sqlite3.connect("selena.db")
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return {"user_id": user_id, "sub_until": None, "questions_today": 0,
                "last_question_date": None, "name": None, "birthdate": None}
    keys = ["user_id", "username", "sub_until", "questions_today", "last_question_date", "name", "birthdate"]
    return dict(zip(keys, row))

def upsert_user(user_id: int, **kwargs):
    conn = sqlite3.connect("selena.db")
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    for key, val in kwargs.items():
        c.execute(f"UPDATE users SET {key}=? WHERE user_id=?", (val, user_id))
    conn.commit()
    conn.close()

def log_payment(user_id: int, plan: str, amount: int):
    conn = sqlite3.connect("selena.db")
    c = conn.cursor()
    c.execute("INSERT INTO payments (user_id, plan, amount, date) VALUES (?,?,?,?)",
              (user_id, plan, amount, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def is_subscribed(user: dict) -> bool:
    if not user["sub_until"]:
        return False
    return datetime.fromisoformat(user["sub_until"]) > datetime.now()

def can_ask(user: dict) -> tuple[bool, int]:
    """Возвращает (может_спрашивать, осталось_вопросов)"""
    if is_subscribed(user):
        return True, 999
    today = datetime.now().date().isoformat()
    if user["last_question_date"] != today:
        return True, FREE_LIMIT
    remaining = FREE_LIMIT - user["questions_today"]
    return remaining > 0, max(0, remaining)

def increment_questions(user_id: int, user: dict):
    today = datetime.now().date().isoformat()
    if user["last_question_date"] != today:
        upsert_user(user_id, questions_today=1, last_question_date=today)
    else:
        upsert_user(user_id, questions_today=user["questions_today"] + 1)

# ── Клавиатуры ──
def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔮 Задать вопрос Селене", callback_data="ask")],
        [InlineKeyboardButton("💳 Подписка на месяц — 399 ₽", callback_data="buy_sub_month")],
        [InlineKeyboardButton("📄 Нумерология PDF — 490 ₽", callback_data="buy_report_numerology")],
        [InlineKeyboardButton("💞 Совместимость PDF — 390 ₽", callback_data="buy_report_compatibility")],
        [InlineKeyboardButton("🌙 Прогноз на год PDF — 790 ₽", callback_data="buy_report_year")],
    ])

def back_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Главное меню", callback_data="menu")]
    ])

# ── Groq чат ──
def chat(user_id: int, user_text: str) -> str:
    history = histories.setdefault(user_id, [])
    history.append({"role": "user", "content": user_text})
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]
        histories[user_id] = history
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": SYSTEM_PROMPT}] + history,
        max_tokens=1000,
        temperature=0.85,
    )
    reply = response.choices[0].message.content
    history.append({"role": "assistant", "content": reply})
    return reply

# ── Handlers ──
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or ""
    upsert_user(user_id, username=username)
    histories[user_id] = []

    user = get_user(user_id)
    sub_status = "✅ Подписка активна" if is_subscribed(user) else f"🆓 Бесплатно: {FREE_LIMIT} вопроса/день"

    text = (
        "🔮 *Добро пожаловать к Селене*\n\n"
        "Я объединяю психологию, нумерологию и астрологию, "
        "чтобы помочь тебе познать себя и найти свой путь.\n\n"
        f"_{sub_status}_"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Главное меню 🔮", reply_markup=main_menu_keyboard())

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if is_subscribed(user):
        until = datetime.fromisoformat(user["sub_until"]).strftime("%d.%m.%Y")
        text = f"✅ Подписка активна до {until}\nБезлимитные вопросы Селене 🔮"
    else:
        _, remaining = can_ask(user)
        text = f"🆓 Бесплатный план\nОсталось вопросов сегодня: *{remaining}* из {FREE_LIMIT}"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=back_keyboard())

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "menu":
        await query.edit_message_text("Главное меню 🔮", reply_markup=main_menu_keyboard())

    elif data == "ask":
        user = get_user(user_id)
        ok, remaining = can_ask(user)
        if not ok:
            await query.edit_message_text(
                "⚠️ Ты исчерпал бесплатные вопросы на сегодня.\n\n"
                "Оформи подписку за *399 ₽/месяц* — безлимит на все вопросы 🔮",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Оформить подписку", callback_data="buy_sub_month")],
                    [InlineKeyboardButton("⬅️ Назад", callback_data="menu")],
                ])
            )
        else:
            hint = "" if is_subscribed(user) else f"\n_(осталось бесплатных вопросов: {remaining})_"
            await query.edit_message_text(
                f"Напиши свой вопрос Селене 🌙{hint}",
                parse_mode="Markdown",
                reply_markup=back_keyboard()
            )

    elif data.startswith("buy_"):
        plan_key = data[4:]
        plan = PLANS.get(plan_key)
        if not plan:
            return
        await context.bot.send_invoice(
            chat_id=user_id,
            title=plan["title"],
            description=plan["description"],
            payload=plan_key,
            provider_token=PAYMENT_PROVIDER,
            currency="RUB",
            prices=[LabeledPrice(plan["label"], plan["price"])],
            need_name=False,
            need_email=False,
        )

async def on_precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def on_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payment = update.message.successful_payment
    plan_key = payment.invoice_payload
    amount = payment.total_amount
    plan = PLANS.get(plan_key)

    log_payment(user_id, plan_key, amount)
    user = get_user(user_id)

    if plan_key == "sub_month":
        # Активируем подписку
        if is_subscribed(user):
            base = datetime.fromisoformat(user["sub_until"])
        else:
            base = datetime.now()
        new_until = (base + timedelta(days=plan["days"])).isoformat()
        upsert_user(user_id, sub_until=new_until)
        until_str = datetime.fromisoformat(new_until).strftime("%d.%m.%Y")
        await update.message.reply_text(
            f"✅ Подписка активирована до *{until_str}*!\n\n"
            "Теперь ты можешь задавать Селене неограниченное количество вопросов 🔮\n\n"
            "Напиши что угодно — и звёзды ответят.",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )
    else:
        # Генерируем PDF-отчёт
        await update.message.reply_text("⏳ Генерирую твой персональный отчёт... Это займёт несколько секунд 🔮")
        user_data = get_user(user_id)
        name = user_data.get("name") or update.effective_user.first_name or "Дорогой друг"
        birthdate = user_data.get("birthdate") or "не указана"

        # Получаем контент от Селены через Groq
        prompts = {
            "report_numerology": f"Составь подробный нумерологический портрет для {name}, дата рождения: {birthdate}. Включи: число жизненного пути, число судьбы, число личности, кармические уроки, сильные и слабые стороны, рекомендации. Подробно, минимум 600 слов.",
            "report_compatibility": f"Составь анализ совместимости для {name} (дата рождения: {birthdate}). Включи нумерологическую и астрологическую совместимость, идеальных партнёров, сложности и рекомендации. Минимум 600 слов.",
            "report_year": f"Составь астрологический и нумерологический прогноз на 2025 год для {name} (дата рождения: {birthdate}). По кварталам, ключевые периоды, рекомендации. Минимум 600 слов.",
        }
        prompt = prompts.get(plan_key, "Составь общий анализ личности.")
        content = chat(user_id, prompt)

        # Генерируем отчёт (PDF или TXT)
        report_path = generate_pdf_report(
            title=plan["title"],
            name=name,
            content=content,
            filename=f"/tmp/selena_{plan_key}_{user_id}.pdf"
        )

        is_txt = report_path.endswith(".txt")
        out_name = f"Селена_{plan_key}.{'txt' if is_txt else 'pdf'}"
        caption = f"✨ Твой персональный отчёт готов, {name}!\n\nСохрани его — в нём твой путь 🔮"

        with open(report_path, "rb") as f:
            await context.bot.send_document(
                chat_id=user_id,
                document=f,
                filename=out_name,
                caption=caption
            )
        await update.message.reply_text("Желаешь задать вопрос или заказать другой отчёт?",
                                        reply_markup=main_menu_keyboard())

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    ok, remaining = can_ask(user)

    if not ok:
        await update.message.reply_text(
            f"⚠️ Бесплатный лимит исчерпан ({FREE_LIMIT} вопроса/день).\n\n"
            "Оформи подписку за *399 ₽/месяц* 🔮",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Оформить подписку", callback_data="buy_sub_month")]
            ])
        )
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    increment_questions(user_id, user)

    try:
        reply = chat(user_id, update.message.text)
        # Подсказка об оставшихся вопросах для бесплатных
        if not is_subscribed(user) and remaining <= 2:
            reply += f"\n\n_⚡ Осталось бесплатных вопросов: {remaining - 1}_"
        await update.message.reply_text(reply, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await update.message.reply_text("🔮 Космические помехи... Попробуй ещё раз.")

async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    histories[update.effective_user.id] = []
    await update.message.reply_text("🌙 История очищена.", reply_markup=main_menu_keyboard())

def main():
    init_db()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(PreCheckoutQueryHandler(on_precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_payment))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    logger.info("Селена PRO запущена 🔮")
    app.run_polling()

if __name__ == "__main__":
    main()
