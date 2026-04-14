from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timezone
from typing import Sequence

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message

telegram_notification_timestamps: dict[str, float] = {}


def is_telegram_chat_id_mode(argv: Sequence[str]) -> bool:
    if len(argv) < 2:
        return False
    return argv[1].strip().lower() in {"telegram-chat-id", "telegram_chat_id", "tg-chat-id", "tg_chat_id"}


async def send_telegram_notification_async(bot_token: str, chat_id: str, title: str, message: str) -> None:
    bot = Bot(token=bot_token)
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=f"{title}\n{message}",
            disable_web_page_preview=True,
        )
    finally:
        await bot.session.close()


def send_telegram_notification_sync(notifications_enabled: bool, bot_token: str, chat_id: str, title: str, message: str) -> None:
    if not notifications_enabled or not bot_token or not chat_id:
        return

    try:
        asyncio.run(send_telegram_notification_async(bot_token, chat_id, title, message))
    except Exception as exc:
        print(f"[TELEGRAM] Ошибка отправки уведомления: {exc}", flush=True)


def queue_telegram_notification(
    *,
    title: str,
    message: str,
    dedup_key: str,
    enabled: bool,
    notifications_enabled: bool,
    bot_token: str,
    chat_id: str,
    cooldown_seconds: float,
) -> None:
    if not enabled or not notifications_enabled or not bot_token or not chat_id:
        return

    now_ts = datetime.now(timezone.utc).timestamp()
    last_ts = telegram_notification_timestamps.get(dedup_key)
    if last_ts is not None and now_ts - last_ts < cooldown_seconds:
        return

    telegram_notification_timestamps[dedup_key] = now_ts
    threading.Thread(
        target=send_telegram_notification_sync,
        args=(notifications_enabled, bot_token, chat_id, title, message),
        daemon=True,
    ).start()


async def run_telegram_chat_id_helper(bot_token: str) -> None:
    if not bot_token:
        print("[TELEGRAM] TELEGRAM_BOT_TOKEN не задан. Заполните его в .env и повторите команду.", flush=True)
        return

    bot = Bot(token=bot_token)
    dp = Dispatcher()
    router = Router()

    @router.message(Command("start", "chatid", "id"))
    async def handle_chat_id_command(message: Message) -> None:
        chat_id = str(message.chat.id)
        chat_type = message.chat.type
        chat_title = getattr(message.chat, "title", None) or getattr(message.chat, "full_name", None) or "-"
        username = message.from_user.username if message.from_user else None

        print(
            f"[TELEGRAM] chat_id={chat_id} type={chat_type} title={chat_title} username={username or '-'}",
            flush=True,
        )
        await message.answer(
            "Ваш TELEGRAM_CHAT_ID:\n"
            f"{chat_id}\n\n"
            f"Тип чата: {chat_type}\n"
            f"Название: {chat_title}\n\n"
            "Добавьте в .env:\n"
            f"TELEGRAM_CHAT_ID={chat_id}"
        )

    @router.message()
    async def handle_any_message(message: Message) -> None:
        await handle_chat_id_command(message)

    dp.include_router(router)

    print("[TELEGRAM] Режим получения TELEGRAM_CHAT_ID запущен.", flush=True)
    print("[TELEGRAM] Напишите боту /chatid или любое сообщение, чтобы получить chat_id.", flush=True)

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, handle_signals=True)
    finally:
        await bot.session.close()