from telegram import Update
from telegram.ext import ContextTypes

async def chatid_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Chat ID: {update.effective_chat.id}"
    )
