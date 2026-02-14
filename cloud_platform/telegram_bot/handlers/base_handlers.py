from telegram import Update
from telegram.ext import ContextTypes

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    await update.message.reply_text("Hello! Welcome to the bot.")

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /help command."""
    help_text = ("""
        Available commands:
        /start - Start the bot
        /help - Show this help message
        /calc - Calculate a simple expression
    """
    )
    await update.message.reply_text(help_text)

async def echo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Echo the user message."""
    # user_message = update.message.text
    await update.message.reply_text(update.message.text)