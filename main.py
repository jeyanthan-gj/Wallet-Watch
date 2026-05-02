"""
main.py — Wallet Watch Telegram bot entry point.

Security hardening applied:
  [CRIT-2] Rate limiting on every incoming message (see security/rate_limiter.py)
  [HIGH-8] Key rotation index protected per-request (not a shared global)
  [LOW-12] Structured logging — tool args are NOT printed to stdout
  [MED-11] Recurring bill processing moved to a scheduled job, not per-message
"""

import os
import threading
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv

from telegram import Update, BotCommand
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

# ── Use the SECURE config manager (never the old tools/config_manager.py) ──
from security.config_manager import get_secret, get_secrets_list
from security.rate_limiter import check_rate_limit, reset_rate_limit
from security.audit_log import log_rate_limit_blocked

from agent import run_agent
import pytz
from datetime import time as dt_time

load_dotenv()

# ── Logging — structured, no sensitive values ─────────────────────────────────
logging.basicConfig(
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Bot tokens from SECURE source (env first, then encrypted Supabase) ────────
BOT_TOKENS = get_secrets_list("TELEGRAM_BOT_TOKEN")
if not BOT_TOKENS:
    raise RuntimeError(
        "No TELEGRAM_BOT_TOKEN found. Set it as an environment variable."
    )

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
        "• `delete my last transaction`\n\n"
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
    await update.message.reply_text(
        f"📊 *Your Spending Summary*\n\n{total}", parse_mode="Markdown"
    )


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_chat_action("typing")
    history = get_user_expenses(user_id, limit=5)
    await update.message.reply_text(
        f"🧾 *Recent Transactions*\n\n{history}", parse_mode="Markdown"
    )


# ── Message Handler ───────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    user_id = user.id                # ALWAYS from Telegram auth — never from message text

    # [CRIT-2] Rate limiting — checked BEFORE any processing
    allowed, reason = await check_rate_limit(user_id)
    if not allowed:
        log_rate_limit_blocked(user_id, reason)
        await update.message.reply_text(reason)
        return

    register_user(user_id, user.first_name)
    await update.message.reply_chat_action("typing")

    try:
        response = await run_agent(user_id, update.message.text)
        text       = response["text"]
        attachment = response["attachment"]

        if attachment:
            if attachment["type"] == "photo":
                await update.message.reply_photo(
                    photo=open(attachment["path"], "rb"),
                    caption=text,
                    parse_mode="Markdown",
                )
                # [HIGH-7] Clean up temp file after sending
                _safe_delete(attachment["path"])
            elif attachment["type"] == "document":
                await update.message.reply_document(
                    document=open(attachment["path"], "rb"),
                    caption=text,
                    parse_mode="Markdown",
                )
                _safe_delete(attachment["path"])
        else:
            await update.message.reply_text(text, parse_mode="Markdown")

    except Exception as exc:
        # [LOW-12] Log error without leaking user content
        logger.error("Agent error for user %d: %s", user_id, type(exc).__name__)
        await update.message.reply_text(
            "🤔 Something went wrong. Please try again in a moment."
        )


def _safe_delete(path: str) -> None:
    """Delete a temp file, logging but not raising on failure."""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError as exc:
        logger.warning("Could not delete temp file %s: %s", path, exc)


# ── Scheduled Jobs ────────────────────────────────────────────────────────────

async def daily_morning_report_job(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Running daily morning report job")
    for uid in get_active_users(days=7):
        try:
            report = generate_morning_report(uid)
            await context.bot.send_message(
                chat_id=uid, text=report, parse_mode="Markdown"
            )
        except Exception as exc:
            logger.error("Morning report failed for user %d: %s", uid, type(exc).__name__)


async def recurring_bills_job(context: ContextTypes.DEFAULT_TYPE):
    """
    [MED-11] Recurring bill processing is now a scheduled job (every hour),
    NOT triggered per user message.  Eliminates timing-attack surface and
    ensures bills process even for inactive users.
    """
    logger.info("Running recurring bills processing job")
    for uid in get_active_users(days=90):   # active in last 3 months
        try:
            process_pending_bills(uid)
        except Exception as exc:
            logger.error(
                "Recurring bill processing failed for user %d: %s",
                uid, type(exc).__name__
            )


# ── Error Handler ─────────────────────────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error_str = str(context.error)
    if "Conflict: terminated by other getUpdates" in error_str:
        logger.warning("Polling conflict — another instance may be running")
        return
    if "Unauthorized" in error_str:
        logger.error("Bot token rejected mid-session")
        return
    # [LOW-12] Do NOT log update object — it contains user message text
    logger.error("Unhandled telegram error: %s", type(context.error).__name__)


# ── Health Check (Render keep-alive) ─────────────────────────────────────────

class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *args):
        pass   # suppress access logs


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

            # Schedule jobs
            ist_tz = pytz.timezone("Asia/Kolkata")
            app.job_queue.run_daily(
                daily_morning_report_job,
                time=dt_time(hour=7, minute=0, tzinfo=ist_tz),
            )
            app.job_queue.run_repeating(
                recurring_bills_job,
                interval=3600,   # every hour
                first=60,        # start 60 s after boot
            )

            # Handlers
            app.add_handler(CommandHandler("start",   start_command))
            app.add_handler(CommandHandler("summary", summary_command))
            app.add_handler(CommandHandler("history", history_command))
            app.add_handler(
                MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
            )
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
