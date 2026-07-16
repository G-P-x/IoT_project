from telegram import Update
from telegram.ext import ContextTypes


async def _reply(update: Update, text: str) -> None:
    message = update.effective_message
    if message is None:
        return
    await message.reply_text(text, parse_mode="Markdown")


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    welcome_text = (
        "👋 *Benvenuto nel sistema di monitoraggio sicurezza escursionisti.*\n\n"
        "Questo bot ti permette di visualizzare lo stato di sicurezza in tempo reale. "
        "Inoltre, il sistema ti invierà notifiche automatiche in caso di allarmi o anomalie rilevate dai sensori.\n\n"
        "Usa /help per vedere i comandi disponibili.\n"
        "Usa /register per ricevere gli allarmi su questo dispositivo."
    )
    await _reply(update, welcome_text)


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /help command."""
    help_text = (
        "🛠 *Comandi disponibili:*\n\n"
        "/start    - Mostra il messaggio di benvenuto\n"
        "/help     - Mostra questo messaggio di aiuto\n"
        "/status   - Richiedi l'ultimo stato noto dei sensori\n"
        "/register - Registra questo dispositivo per ricevere gli allarmi\n"
        "/chatid   - Mostra l'ID di questa chat"
    )
    await _reply(update, help_text)


async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /status command."""
    status_text = (
        "📊 *Stato Attuale*\n\n"
        "Sto recuperando gli ultimi dati dal Digital Twin...\n"
        "_(Nota: qui inseriremo i dati reali recuperati da MongoDB)_"
    )
    await _reply(update, status_text)


async def chatid_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /chatid command — mostra il chat ID senza registrare."""
    chat_id = update.effective_chat.id if update.effective_chat else "unknown"
    await _reply(update, f"Il tuo Chat ID è: `{chat_id}`\n\nUsa /register per registrarti alla ricezione degli allarmi.")


async def register_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle the /register command.

    Salva il chat_id dell'utente in MongoDB tramite il NotificationService
    iniettato in bot_data da app.py.
    """
    chat_id = str(update.effective_chat.id if update.effective_chat else "unknown")
    notification_service = context.application.bot_data.get("notification_service")

    if not notification_service:
        await _reply(update, "⚠️ Servizio notifiche non disponibile. Riprova più tardi.")
        return

    registered = notification_service.register_user(chat_id)

    if registered:
        await _reply(update, "✅ *Registrazione completata!*\n\nRiceverai notifiche automatiche in caso di allarmi sismici, termici o di qualità dell'aria rilevati dai sensori sull'Etna.")
    else:
        await _reply(update, "ℹ️ Sei già registrato per la ricezione degli allarmi.")


async def unknown_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle unrecognized text."""
    await _reply(update, "⚠️ Questo bot accetta solo comandi specifici. Usa /help per la lista.")


async def send_push_notification(application, chat_id: str, message: str) -> None:
    """
    Utility che il server Flask può chiamare per inviare allarmi asincroni.
    """
    await application.bot.send_message(
        chat_id=chat_id, text=message, parse_mode="Markdown"
    )