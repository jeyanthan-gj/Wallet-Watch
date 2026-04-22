import os
import logging
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
from database.manager import init_db, get_user_expenses, get_total_spent, register_user, get_active_users
from database.recurring_manager import process_pending_bills
from tools.report_generator import generate_morning_report
from tools.config_manager import get_secret
from agent import run_agent
import pytz
from datetime import time

# Load environment variables
load_dotenv()

# Configuration (Supabase FIRST, then .env)
TELEGRAM_BOT_TOKEN = get_secret("TELEGRAM_BOT_TOKEN")

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Command Handlers ──────────────────────────────────────────────────────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a welcome message when the /start command is issued."""
    user = update.effective_user
    register_user(user.id, user.first_name)
    
    welcome = (
        f"👋 Hey {user.first_name}! I'm *Wallet Watch*, your personal finance assistant.\n\n"
        "I help you track expenses and income in plain English. Just tell me what you spent or earned!\n\n"
        "*Examples:*\n"
        "• `spent ₹200 on lunch`\n"
        "• `got paid ₹50,000 salary`\n"
        "• `show my recent transactions`\n"
        "• `how much have I spent in total?`\n\n"
        "*Commands:*\n"
        "/start — Show this welcome message\n"
        "/summary — Quick spending overview\n"
        "/history — Last 5 transactions\n\n"
        "I'll also send you a personalized 🌅 *Daily Morning Report* at 7 AM IST to keep you updated! 💰"
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show a quick spending summary for the user."""
    user_id = update.effective_user.id
    await update.message.reply_chat_action("typing")
    total = get_total_spent(user_id)
    await update.message.reply_text(f"📊 *Your Spending Summary*\n\n{total}", parse_mode="Markdown")


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the last 5 transactions for the user."""
    user_id = update.effective_user.id
    await update.message.reply_chat_action("typing")
    history = get_user_expenses(user_id, limit=5)
    await update.message.reply_text(f"🧾 *Recent Transactions*\n\n{history}", parse_mode="Markdown")


# ── Message Handler ───────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives a message, runs the agent, delivers the response."""
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    user_text = update.message.text

    # Ensure user is registered/updated
    register_user(user.id, user.first_name)

    await update.message.reply_chat_action("typing")

    # 🔄 Process any pending recurring bills first (Silent)
    try:
        process_pending_bills(user.id)
    except Exception as e:
        logger.error(f"Error processing recurring bills: {e}")

    try:
        response = await run_agent(user.id, user_text)
        text = response["text"]
        attachment = response["attachment"]

        # Delivery layer — the only place we distinguish photo vs document vs text
        if attachment:
            if attachment["type"] == "photo":
                await update.message.reply_photo(
                    photo=open(attachment["path"], "rb"), 
                    caption=text,
                    parse_mode="Markdown"
                )
            elif attachment["type"] == "document":
                await update.message.reply_document(
                    document=open(attachment["path"], "rb"),
                    caption=text,
                    parse_mode="Markdown"
                )
        else:
            await update.message.reply_text(text, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Agent error: {e}", exc_info=True)
        await update.message.reply_text("🤔 Something went wrong. Please try again!")


# ── Error Handler ─────────────────────────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error."""
    logger.error(f"Exception while handling an update: {context.error}", exc_info=True)


# ── Daily Report Job ──────────────────────────────────────────────────────────

async def daily_morning_report_job(context: ContextTypes.DEFAULT_TYPE):
    """Fetches active users and sends them their morning report."""
    logger.info("Starting Daily Morning Report job...")
    active_user_ids = get_active_users(days=7)
    
    for uid in active_user_ids:
        try:
            # We don't have first_name easily here, but we can pass 'there' 
            # or add it to get_active_users return.
            report = generate_morning_report(uid)
            await context.bot.send_message(chat_id=uid, text=report, parse_mode="Markdown")
            logger.info(f"Report sent to user {uid}")
        except Exception as e:
            logger.error(f"Failed to send report to {uid}: {e}")

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: Please set TELEGRAM_BOT_TOKEN in your .env file.")
    else:
        print("🚀 Starting Wallet Watch (Gemini + LangGraph)...")
        init_db()

        # Build application and enable JobQueue
        application = (
            ApplicationBuilder()
            .token(TELEGRAM_BOT_TOKEN)
            .connect_timeout(30.0)
            .read_timeout(45.0)
            .write_timeout(30.0)
            .pool_timeout(30.0)
            .build()
        )

        # Schedule the daily report at 07:00 IST
        ist = pytz.timezone('Asia/Kolkata')
        report_time = time(hour=7, minute=0, tzinfo=ist)
        application.job_queue.run_daily(daily_morning_report_job, time=report_time)
        print(f"⏰ Daily Report scheduled for 07:00 IST.")

        # Register commands
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("summary", summary_command))
        application.add_handler(CommandHandler("history", history_command))

        # Route all text to the agent
        application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

        # Error handler
        application.add_error_handler(error_handler)

        print("✅ Bot is now listening...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
