#!/usr/bin/env python3
"""
Telegram OTP Fetcher - lightweight, Koyeb-ready version.

Instructions:
- Configure the environment variables (recommended on Koyeb dashboard):
    BOT_TOKEN  -> Telegram bot token (e.g. 123:ABC)
    CHAT_ID    -> Target group chat id (e.g. -1001234567890)
    API_KEY    -> Profile/API key for otprevenue (if used)
- Run: python bot.py

This version:
- Removes auto-install logic (use requirements.txt / Docker)
- Reads secrets from environment variables
- Keeps core OTP extraction + "success number" sender logic
- Uses python-telegram-bot (async Application)
"""

import os
import re
import asyncio
import logging
from datetime import datetime, timedelta

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

# Logging
logging.basicConfig(
    format="%(levelname)s: %(message)s",
    level=os.environ.get("LOG_LEVEL", "INFO"),
)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)


class TelegramOTPFetcher:
    def __init__(self, bot_token: str, chat_id: str, api_key: str | None = None):
        self.bot_token = bot_token
        self.chat_id = str(chat_id)
        self.api_key = api_key or ""
        self.application = Application.builder().token(self.bot_token).build()
        self.otp_patterns = [
            r"\b\d{4,8}\b",  # 4-8 digit codes
            r"\b[A-Z0-9]{4,8}\b",  # Alphanumeric codes
            r"verification code[:\s]*(\d+)",
            r"your code[:\s]*(\d+)",
            r"otp[:\s]*(\d+)",
            r"code[:\s]*(\d+)",
            r"pin[:\s]*(\d+)",
        ]
        self.api_base_url = "https://otprevenue.com/api/v1"
        self.sent_numbers = set()
        self.start_time = None

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Respond to /start"""
        await update.message.reply_text(
            "🤖 OTP Fetcher is running.\n"
            "It will monitor messages and send detected OTP notifications to the configured group.\n"
            "Use /status to check uptime.",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uptime = (
            "Not started"
            if not self.start_time
            else str(datetime.utcnow() - self.start_time).split(".")[0]
        )
        await update.message.reply_text(
            f"✅ Bot status: running\nUptime: {uptime}\nPatterns loaded: {len(self.otp_patterns)}",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def extract_otp(self, text: str) -> str | None:
        for pattern in self.otp_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                # some regex use capturing groups, others return plain strings
                first = matches[0]
                if isinstance(first, tuple):
                    first = next((m for m in first if m), None)
                return first
        return None

    def extract_application_name(self, text: str) -> str:
        text_lower = (text or "").lower()
        app_patterns = {
            "claude": "Claude",
            "openai": "OpenAI",
            "chatgpt": "ChatGPT",
            "google": "Google",
            "facebook": "Facebook",
            "instagram": "Instagram",
            "twitter": "Twitter",
            "x.com": "X (Twitter)",
            "whatsapp": "WhatsApp",
            "telegram": "Telegram",
            "discord": "Discord",
            "microsoft": "Microsoft",
            "apple": "Apple",
            "amazon": "Amazon",
            "netflix": "Netflix",
            "spotify": "Spotify",
            "uber": "Uber",
            "paypal": "PayPal",
        }
        for p, n in app_patterns.items():
            if p in text_lower:
                return n
        return "Unknown App"

    def extract_phone_number(self, text: str) -> str | None:
        if not text:
            return None
        phone_patterns = [
            r"\+?\d{9,15}",
        ]
        for pattern in phone_patterns:
            matches = re.findall(pattern, text)
            if matches:
                return max(matches, key=len)
        return None

    def format_phone_number(self, phone_number: str) -> str:
        if not phone_number:
            return "Unknown"
        digits = re.sub(r"\D", "", phone_number)
        if len(digits) < 6:
            return phone_number
        return f"{digits[:3]}*****{digits[-3:]}"

    async def get_country_from_database(self, phone_number: str) -> str:
        """Optional: Uses otprevenue lookup endpoint (if available)."""
        if not self.api_key or not phone_number:
            return "Unknown"
        try:
            headers = {"X-API-Key": self.api_key}
            async with aiohttp.ClientSession() as session:
                url = f"{self.api_base_url}/phone-country/{phone_number}"
                async with session.get(url, headers=headers, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("country", "Unknown")
        except Exception as e:
            logging.debug("Country lookup failed: %s", e)
        return "Unknown"

    async def send_success_numbers_to_group(self):
        """Fetch new success numbers from the profile API and announce them."""
        try:
            numbers = await self.get_recent_success_numbers_after_start(limit=50)
            if not numbers:
                return
            new = []
            for n in numbers:
                nid = n.get("id")
                if nid and nid not in self.sent_numbers:
                    new.append(n)
                    self.sent_numbers.add(nid)
            if not new:
                return

            for number in new:
                time_str = number.get("receivedAt", "N/A")
                formatted_time = time_str
                if time_str and time_str != "N/A":
                    try:
                        dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                        bd_time = dt + timedelta(hours=6)
                        formatted_time = bd_time.strftime("%d-%m-%Y %I:%M:%S %p")
                    except Exception:
                        formatted_time = time_str

                country = number.get("country", "N/A")
                phone_number = number.get("phoneNumber", "N/A")
                otp_code = number.get("otpCode", "N/A")
                service = number.get("service", "N/A")
                full_message = number.get("fullMessage", "N/A")

                def mask_number(num: str) -> str:
                    clean = re.sub(r"\D", "", str(num))
                    if len(clean) > 6:
                        return clean[:5] + "*****" + clean[-3:]
                    return clean or "N/A"

                masked_phone = mask_number(phone_number)
                if masked_phone and not masked_phone.startswith("+"):
                    masked_phone = "+" + masked_phone

                text = (
                    f"📬 \"{service}\" OTP Received!\n\n"
                    f"Number: {masked_phone}\n"
                    f"🔐OTP: {otp_code}\n"
                    f"Country: {country}\n"
                    f"Time: {formatted_time}\n\n"
                    f"Full Message:\n{full_message}"
                )

                keyboard = [
                    [
                        InlineKeyboardButton("Bot", url="https://t.me/YourBotUsername"),
                        InlineKeyboardButton("Group", url="https://t.me/YourGroupLink"),
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                # Send as plain text to avoid MarkdownV2 escaping issues from API text
                await self.application.bot.send_message(
                    chat_id=self.chat_id,
                    text=text,
                    disable_web_page_preview=True,
                    reply_markup=reply_markup,
                )

                logging.info("Sent new success number: %s", phone_number)

        except Exception as e:
            logging.error("Error sending success numbers: %s", e)

    async def get_recent_success_numbers(self, limit: int = 5):
        if not self.api_key:
            return []
        try:
            headers = {"X-API-Key": self.api_key}
            async with aiohttp.ClientSession() as session:
                url = f"{self.api_base_url}/success-numbers?page=1&limit={limit}"
                async with session.get(url, headers=headers, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("data", {}).get("numbers", [])
        except Exception as e:
            logging.debug("get_recent_success_numbers failed: %s", e)
        return []

    async def get_recent_success_numbers_after_start(self, limit: int = 50):
        if not self.start_time:
            return await self.get_recent_success_numbers(limit)
        try:
            start_time_iso = self.start_time.isoformat()
            headers = {"X-API-Key": self.api_key}
            async with aiohttp.ClientSession() as session:
                url = f"{self.api_base_url}/success-numbers?page=1&limit={limit}&after={start_time_iso}"
                async with session.get(url, headers=headers, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("data", {}).get("numbers", [])
        except Exception as e:
            logging.debug("get_recent_success_numbers_after_start failed: %s", e)
        return []

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message and update.message.text:
            message_text = update.message.text
            chat_id = str(update.effective_chat.id)

            # Only monitor the configured group
            if chat_id != self.chat_id:
                return

            otp = await self.extract_otp(message_text)
            if not otp:
                return

            application_name = self.extract_application_name(message_text)
            # try group title or message for phone
            phone_number = (
                self.extract_phone_number(update.effective_chat.title or "")
                or self.extract_phone_number(message_text)
                or "Unknown"
            )
            formatted_number = self.format_phone_number(phone_number)
            country = await self.get_country_from_database(phone_number)
            current_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

            response = f"*{application_name}* OTP Detected!\n\n"
            response += f"Number: {formatted_number}\n"
            response += f"OTP: {otp}\n"
            response += f"Application: {application_name}\n"
            response += f"Country: {country}\n"
            response += f"Time: {current_time}\n\n"
            response += f"Full Message:\n{message_text}"

            # Use Markdown (basic) but keep content simple
            await context.bot.send_message(
                chat_id=self.chat_id,
                text=response,
                parse_mode=ParseMode.MARKDOWN,
            )

            logging.info("OTP extracted: %s from group %s", otp, chat_id)

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        logging.error("Exception while handling an update:", exc_info=context.error)

    def run(self):
        # set start time
        self.start_time = datetime.utcnow()

        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("status", self.status))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        self.application.add_error_handler(self.error_handler)

        # job queue to fetch success numbers every 10 seconds (adjustable by env)
        interval = int(os.environ.get("POLL_INTERVAL", "10"))
        first = int(os.environ.get("POLL_FIRST", "10"))
        self.application.job_queue.run_repeating(self.check_and_send_success_numbers, interval=interval, first=first)

        logging.info("Starting Telegram OTP Fetcher (polling)...")
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)

    async def check_and_send_success_numbers(self, context: ContextTypes.DEFAULT_TYPE):
        await self.send_success_numbers_to_group()


def get_env(var: str, default: str | None = None, required: bool = False) -> str:
    val = os.environ.get(var, default)
    if required and not val:
        raise RuntimeError(f"Environment variable {var} is required but not set.")
    return val


if __name__ == "__main__":
    BOT_TOKEN = get_env("BOT_TOKEN", required=True)
    CHAT_ID = get_env("CHAT_ID", required=True)
    API_KEY = get_env("API_KEY", default="")

    bot = TelegramOTPFetcher(bot_token=BOT_TOKEN, chat_id=CHAT_ID, api_key=API_KEY)
    bot.run()