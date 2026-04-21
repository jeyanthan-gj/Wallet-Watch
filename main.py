import os
import logging
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
from database.manager import init_db, get_user_expenses, get_total_spent
from agent import run_agent

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Command Handlers ──────────────────────────────────────────────────────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a welcome message when the /start command is issued."""
    name = update.effective_user.first_name or "there"
    welcome = (
        f"👋 Hey {name}! I'm *Wallet Watch*, your personal finance assistant.\n\n"
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
        "Let's get started! 💰"
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

    user_id = update.effective_user.id
    user_text = update.message.text

    await update.message.reply_chat_action("typing")

    try:
        response = await run_agent(user_id, user_text)
        text = response["text"]
        attachment = response["attachment"]

        # Delivery layer — the only place we distinguish photo vs text (Telegram API requirement)
        if attachment and attachment["type"] == "photo":
            await update.message.reply_photo(
                photo=open(attachment["path"], "rb"), 
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


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: Please set TELEGRAM_BOT_TOKEN in your .env file.")
    else:
        print("🚀 Starting Wallet Watch (Gemini + LangGraph)...")
        init_db()

        application = (
            ApplicationBuilder()
            .token(TELEGRAM_BOT_TOKEN)
            .connect_timeout(30.0)
            .read_timeout(45.0)
            .write_timeout(30.0)
            .pool_timeout(30.0)
            .build()
        )

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
