import asyncio
import csv
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from telegram import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", encoding="utf-8-sig")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
MANAGER_CHAT_ID = os.getenv("MANAGER_CHAT_ID", "").strip()
LEADS_FILE = BASE_DIR / "leads.csv"
PARTICIPANTS_FILE = BASE_DIR / "participants.json"

BTN_LAUNCH = "🚀 Запустить бота"
BTN_ROLL = "🎲 Кинуть кубик"
BTN_SHARE_CONTACT = "📱 Поделиться контактом"

STATE_AWAIT_LAUNCH = "await_launch"
STATE_AWAIT_ROLL = "await_roll"
STATE_AWAIT_PHONE = "await_phone"
STATE_DONE = "done"

PRIZES = {
    1: "Бесплатное обучение в автошколе",
    2: "Скидка на обучение 10%",
    3: "2 бесплатных занятия",
    4: "Фирменная футболка автошколы",
    5: "Прокатим с ветерком на BMW",
    6: "Секретный супер-приз",
}


@dataclass
class Session:
    dice_value: int | None = None
    prize: str | None = None
    state: str = STATE_AWAIT_LAUNCH


SESSIONS: dict[int, Session] = {}
PARTICIPANTS: dict[int, str] = {}


def load_participants() -> dict[int, str]:
    if not PARTICIPANTS_FILE.exists():
        return {}
    try:
        data = json.loads(PARTICIPANTS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            # Backward compatibility with old format: [user_id, ...]
            return {int(user_id): "" for user_id in data}
        if isinstance(data, dict):
            result: dict[int, str] = {}
            for user_id, prize in data.items():
                result[int(user_id)] = str(prize or "")
            return result
        return {}
    except Exception:
        return {}


def refresh_participants() -> None:
    global PARTICIPANTS
    PARTICIPANTS = load_participants()


def save_participants() -> None:
    data = {str(user_id): prize for user_id, prize in sorted(PARTICIPANTS.items())}
    PARTICIPANTS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def has_participated(user_id: int) -> bool:
    # Keep in-memory state aligned with file changes made while bot is running.
    refresh_participants()
    return user_id in PARTICIPANTS


def get_saved_prize(user_id: int) -> str | None:
    refresh_participants()
    prize = PARTICIPANTS.get(user_id, "").strip()
    return prize or None


def mark_participated(user_id: int, prize: str) -> None:
    # First prize is final and should not be overwritten.
    if user_id in PARTICIPANTS:
        return
    PARTICIPANTS[user_id] = prize
    save_participants()


def get_or_create_session(user_id: int) -> Session:
    if user_id not in SESSIONS:
        SESSIONS[user_id] = Session()
    return SESSIONS[user_id]


def launch_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton(BTN_LAUNCH)]], resize_keyboard=True)


def roll_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton(BTN_ROLL)]], resize_keyboard=True)


def phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(BTN_SHARE_CONTACT, request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def normalize_phone(raw_phone: str) -> str | None:
    phone = raw_phone.strip()
    if not phone:
        return None
    return phone


def get_prize_for_user(user_id: int) -> str | None:
    if not LEADS_FILE.exists():
        return None
    try:
        with LEADS_FILE.open("r", newline="", encoding="utf-8") as file_obj:
            reader = csv.DictReader(file_obj)
            result = None
            for row in reader:
                if str(row.get("user_id", "")).strip() == str(user_id):
                    result = row.get("prize")
            return result
    except Exception:
        return None


def has_submitted_phone(user_id: int) -> bool:
    return get_prize_for_user(user_id) is not None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.message
    if not user or not message:
        return

    if has_participated(user.id):
        prize = get_saved_prize(user.id) or get_prize_for_user(user.id)
        if prize and not has_submitted_phone(user.id):
            SESSIONS[user.id] = Session(prize=prize, state=STATE_AWAIT_PHONE)
            await message.reply_text(
                f"Ты уже выиграл(а) приз: {prize}.\n"
                "Кубик повторно кидать нельзя. Отправь номер телефона для получения приза.",
                reply_markup=phone_keyboard(),
            )
            return

        prize_text = f"Твой приз: {prize}\n" if prize else ""
        await message.reply_text(
            "Ты уже участвовал(а) в розыгрыше.\n"
            f"{prize_text}"
            "Ты уже выиграл(а) этот приз, заново кинуть кубик нельзя.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    SESSIONS[user.id] = Session(state=STATE_AWAIT_LAUNCH)
    await message.reply_text(
        "Нажми кнопку ниже, чтобы начать розыгрыш.",
        reply_markup=launch_keyboard(),
    )


async def launch_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.message
    if not user or not message:
        return

    if has_participated(user.id):
        await start(update, context)
        return

    session = get_or_create_session(user.id)
    session.state = STATE_AWAIT_ROLL

    prizes_text = "\n".join([f"{idx}. {name}" for idx, name in PRIZES.items()])
    text = (
        "Добро пожаловать в розыгрыш автошколы.\n\n"
        "Условия:\n"
        "1) Нажми «Кинуть кубик»\n"
        "2) Какое число выпадет, такой приз ты получаешь\n"
        "3) Оставь номер телефона\n"
        "4) Менеджер свяжется с тобой для выдачи приза\n\n"
        "Призы:\n"
        f"{prizes_text}"
    )
    await message.reply_text(text, reply_markup=roll_keyboard())


async def roll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.message
    if not user or not message:
        return

    if has_participated(user.id):
        prize = get_saved_prize(user.id) or get_prize_for_user(user.id)
        if prize and not has_submitted_phone(user.id):
            SESSIONS[user.id] = Session(prize=prize, state=STATE_AWAIT_PHONE)
            await message.reply_text(
                f"Твой приз уже зафиксирован: {prize}.\n"
                "Повторный бросок недоступен. Отправь номер телефона для получения приза.",
                reply_markup=phone_keyboard(),
            )
            return

        prize_text = f"Твой приз: {prize}\n" if prize else ""
        await message.reply_text(
            "Повторный бросок недоступен.\n"
            f"{prize_text}"
            "Ты уже выиграл(а) этот приз, заново кинуть кубик нельзя.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    session = get_or_create_session(user.id)
    if session.state != STATE_AWAIT_ROLL:
        await message.reply_text(
            "Сначала нажми «Запустить бота», затем «Кинуть кубик».",
            reply_markup=launch_keyboard() if session.state == STATE_AWAIT_LAUNCH else roll_keyboard(),
        )
        return

    await message.reply_text("Кубик брошен. Удачи!")
    dice_msg = await message.reply_dice(emoji="🎲")

    dice_value = dice_msg.dice.value if dice_msg.dice else 1
    prize = PRIZES[dice_value]

    session.dice_value = dice_value
    session.prize = prize
    session.state = STATE_AWAIT_PHONE
    mark_participated(user.id, prize)

    await message.reply_text(
        f"Поздравляем! Выпало число {dice_value}.\n"
        f"Ты выиграл(а): {prize}.\n\n"
        "Менеджер свяжется с тобой, чтобы выдать приз."
    )

    await message.reply_text(
        "Нажмите кнопку « Поделиться контактом » или Можно написать номер сообщением \n\n"
        "Отправляя номер, вы соглашаетесь на "
        "<a href=\"https://virazh-tomsk.ru/index.php/politika-konfidentsialnosti\">обработку персональных данных</a>.",
        parse_mode="HTML",
        reply_markup=phone_keyboard(),
    )


async def process_phone(update: Update, context: ContextTypes.DEFAULT_TYPE, raw_phone: str) -> None:
    user = update.effective_user
    message = update.message
    if not user or not message:
        return

    session = get_or_create_session(user.id)
    # User can still submit phone right after first roll.
    if has_participated(user.id) and session.state != STATE_AWAIT_PHONE:
        await start(update, context)
        return

    if session.state != STATE_AWAIT_PHONE or not session.prize:
        await message.reply_text(
            "Сначала пройди шаги розыгрыша: запуск, кубик и подтверждение согласия.",
            reply_markup=launch_keyboard(),
        )
        return

    normalized_phone = normalize_phone(raw_phone)
    if not normalized_phone:
        await message.reply_text(
            "Номер не должен быть пустым. Введи номер или нажми кнопку «Поделиться контактом».",
            reply_markup=phone_keyboard(),
        )
        return

    username = user.username or ""
    full_name = user.full_name or ""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    file_exists = LEADS_FILE.exists()
    with LEADS_FILE.open("a", newline="", encoding="utf-8") as file_obj:
        writer = csv.writer(file_obj)
        if not file_exists:
            writer.writerow(["timestamp", "user_id", "username", "full_name", "phone", "dice", "prize"])
        writer.writerow([now, user.id, username, full_name, normalized_phone, session.dice_value, session.prize])

    if MANAGER_CHAT_ID:
        manager_text = (
            "Новая заявка из бота:\n"
            f"Время: {now}\n"
            f"Пользователь: {full_name} (@{username})\n"
            f"User ID: {user.id}\n"
            f"Телефон: {normalized_phone}\n"
            f"Выпало: {session.dice_value}\n"
            f"Приз: {session.prize}"
        )
        try:
            await context.bot.send_message(chat_id=MANAGER_CHAT_ID, text=manager_text)
        except Exception:
            pass

    mark_participated(user.id, session.prize)
    session.state = STATE_DONE

    await message.reply_text(
        "Отлично, номер получен.\n"
        f"Поздравляем, твой приз: {session.prize}.\n"
        "Скоро с тобой свяжется менеджер для выдачи.",
        reply_markup=ReplyKeyboardRemove(),
    )


async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not message.contact:
        return
    await process_phone(update, context, message.contact.phone_number)


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.message
    if not user or not message or not message.text:
        return

    text = message.text.strip()
    session = get_or_create_session(user.id)

    if text == BTN_LAUNCH:
        await launch_flow(update, context)
        return

    if text == BTN_ROLL:
        await roll(update, context)
        return

    if session.state == STATE_AWAIT_PHONE:
        await process_phone(update, context, text)
        return

    if has_participated(user.id):
        await start(update, context)
        return

    await message.reply_text(
        "Используй кнопки для продолжения.",
        reply_markup=launch_keyboard() if session.state == STATE_AWAIT_LAUNCH else roll_keyboard(),
    )


def validate_env() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("Не найден TELEGRAM_BOT_TOKEN. Добавь его в .env")


def main() -> None:
    global PARTICIPANTS
    validate_env()
    PARTICIPANTS = load_participants()
    asyncio.set_event_loop(asyncio.new_event_loop())

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.CONTACT, contact_handler))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), text_handler))

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
