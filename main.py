"""
main.py — Wallet Watch Telegram bot entry point.

Security hardening applied:
  [CRIT-2]  Rate limiting on every incoming message
  [HIGH-8]  Key rotation index is per-request state (not a shared global)
  [LOW-12]  Structured logging — tool args never printed to stdout
  [MED-11]  Recurring bill processing is a scheduled job, not per-message

Bug fixes:
  - httpx INFO logs suppressed to stop Telegram bot token leaking in log URLs
  - Unused import reset_rate_limit removed
  - generate_morning_report called with user_id only (fetches name from DB)
"""

import os
import threading
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters,
)

from database.manager import (
    init_db,
    get_user_expenses,
    get_total_spent,
    register_user,
    get_active_users,
)
from database.recurring_manager import process_pending_bills
from tools.report_generator import generate_morning_report

from security.config_manager import get_secret, get_secrets_list
from security.rate_limiter import check_rate_limit
from security.audit_log import log_rate_limit_blocked

from agent import run_agent
import pytz
from datetime import time as dt_time

load_dotenv()

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# FIX: Suppress httpx INFO logs — they print the full Telegram URL including the bot token
# e.g. "POST https://api.telegram.org/bot<TOKEN>/getUpdates"
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# ── Bot tokens ────────────────────────────────────────────────────────────────
BOT_TOKENS = get_secrets_list("TELEGRAM_BOT_TOKEN")
if not BOT_TOKENS:
    raise RuntimeError("No TELEGRAM_BOT_TOKEN found. Set it as an environment variable.")

IST = pytz.timezone("Asia/Kolkata")


# ── Command Handlers ──────────────────────────────────────────────────────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.first_name)
    welcome = (
        f"👋 Hey {user.first_name}! I'm *Wallet Watch*, your personal finance assistant.\n\n"
        "I help you track expenses and income in plain English. Just tell me what you spent or earned!\n\n"
        "*Examples:*\n"
        "• `spent ₹200 on lunch`\n"
        "• `got paid ₹50,000 salary`\n"
        "• `show my recent transactions`\n"
        "• `delete my last transaction`\n"
        "• `edit the ₹200 lunch to ₹250`\n\n"
        "*Commands:*\n"
        "/start — Show this welcome message\n"
        "/summary — Quick spending overview\n"
        "/history — Last 5 transactions\n\n"
        "I'll also send you a 🌅 *Daily Morning Report* at 7 AM IST! 💰"
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_chat_action("typing")
    total = get_total_spent(user_id)
    await update.message.reply_text(f"📊 *Your Spending Summary*\n\n{total}", parse_mode="Markdown")


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_chat_action("typing")
    history = get_user_expenses(user_id, limit=5)
    await update.message.reply_text(f"🧾 *Recent Transactions*\n\n{history}", parse_mode="Markdown")


# ── Message Handler ───────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user    = update.effective_user
    user_id = user.id   # always from Telegram auth — never from message text

    # Rate limiting — checked BEFORE any processing
    allowed, reason = await check_rate_limit(user_id)
    if not allowed:
        log_rate_limit_blocked(user_id, reason)
        await update.message.reply_text(reason)
        return

    register_user(user_id, user.first_name)
    await update.message.reply_chat_action("typing")

    try:
        response   = await run_agent(user_id, update.message.text)
        text       = response["text"]
        attachment = response["attachment"]

        if attachment:
            path = attachment["path"]
            if attachment["type"] == "photo":
                with open(path, "rb") as f:
                    await update.message.reply_photo(photo=f, caption=text, parse_mode="Markdown")
            elif attachment["type"] == "document":
                with open(path, "rb") as f:
                    await update.message.reply_document(document=f, caption=text, parse_mode="Markdown")
            _safe_delete(path)
        else:
            await update.message.reply_text(text, parse_mode="Markdown")

    except Exception as exc:
        logger.error("Agent error for user %d: %s", user_id, type(exc).__name__)
        await update.message.reply_text("🤔 Something went wrong. Please try again in a moment.")


def _safe_delete(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError as exc:
        logger.warning("Could not delete temp file: %s", exc)


# ── Scheduled Jobs ────────────────────────────────────────────────────────────

async def daily_morning_report_job(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Running daily morning report job")
    for uid in get_active_users(days=7):
        try:
            # FIX: pass user_id only — report_generator fetches the name from DB
            report = generate_morning_report(uid)
            await context.bot.send_message(chat_id=uid, text=report, parse_mode="Markdown")
        except Exception as exc:
            logger.error("Morning report failed for user %d: %s", uid, type(exc).__name__)


async def recurring_bills_job(context: ContextTypes.DEFAULT_TYPE):
    """Runs every hour — processes due recurring bills for all active users."""
    logger.info("Running recurring bills processing job")
    for uid in get_active_users(days=90):
        try:
            process_pending_bills(uid)
        except Exception as exc:
            logger.error("Recurring bill processing failed for user %d: %s", uid, type(exc).__name__)


# ── Error Handler ─────────────────────────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error_str = str(context.error)
    if "Conflict: terminated by other getUpdates" in error_str:
        logger.warning("Polling conflict — another instance may be running")
        return
    if "Unauthorized" in error_str:
        logger.error("Bot token rejected mid-session")
        return
    logger.error("Unhandled telegram error: %s", type(context.error).__name__)


# ── Health Check ──────────────────────────────────────────────────────────────

class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *args):
        pass  # suppress access logs


def _run_health_server():
    port = int(os.environ.get("PORT", 8000))
    logger.info("Health check server on port %d", port)
    HTTPServer(("0.0.0.0", port), _HealthHandler).serve_forever()


# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    threading.Thread(target=_run_health_server, daemon=True).start()

    logger.info("Starting Wallet Watch with %d token(s)", len(BOT_TOKENS))

    for i, token in enumerate(BOT_TOKENS):
        try:
            logger.info("Attempting login with token option %d", i + 1)
            app = (
                ApplicationBuilder()
                .token(token)
                .connect_timeout(30.0)
                .read_timeout(45.0)
                .write_timeout(30.0)
                .pool_timeout(30.0)
                .build()
            )

            ist_tz = pytz.timezone("Asia/Kolkata")
            app.job_queue.run_daily(
                daily_morning_report_job,
                time=dt_time(hour=7, minute=0, tzinfo=ist_tz),
            )
            app.job_queue.run_repeating(
                recurring_bills_job,
                interval=3600,
                first=60,
            )

            app.add_handler(CommandHandler("start",   start_command))
            app.add_handler(CommandHandler("summary", summary_command))
            app.add_handler(CommandHandler("history", history_command))
            app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
            app.add_error_handler(error_handler)

            logger.info("Token %d verified — bot is live", i + 1)
            app.run_polling(allowed_updates=Update.ALL_TYPES)
            break

        except Exception as exc:
            err = str(exc).lower()
            if any(k in err for k in ("unauthorized", "invalid", "401")):
                logger.error("Token %d failed authentication", i + 1)
                if i == len(BOT_TOKENS) - 1:
                    logger.critical("All bot tokens exhausted — cannot start")
            else:
                logger.error("Launch failure with token %d: %s", i + 1, type(exc).__name__)
                break
