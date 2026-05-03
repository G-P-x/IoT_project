from telegram import Update
from telegram.ext import ContextTypes

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    welcome_text = (
        "👋 *Benvenuto nel sistema di monitoraggio sicurezza escursionisti.*\n\n"
        "Questo bot ti permette di visualizzare lo stato di sicurezza in tempo reale. "
        "Inoltre, il sistema ti invierà notifiche automatiche in caso di allarmi o anomalie rilevate dai sensori.\n\n"
        "Usa /help per vedere i comandi disponibili."
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /help command."""
    help_text = (
        "🛠 *Comandi disponibili:*\n\n"
        "/start - Mostra il messaggio di benvenuto\n"
        "/help - Mostra questo messaggio di aiuto\n"
        "/status - Richiedi l'ultimo stato noto del gemello fisico (sensori)\n"
        "/chatid - Mostra l'ID di questa chat (necessario per abilitare le notifiche dal server)"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /status command."""
    # TODO: In futuro, questa funzione dovrà interrogare il DatabaseService o il DTFactory 
    # per recuperare gli ultimi valori letti tramite l'HTTP polling.
    status_text = (
        "📊 *Stato Attuale*\n\n"
        "Sto recuperando gli ultimi dati dal Digital Twin...\n"
        "_(Nota per lo sviluppo: Qui inseriremo i dati reali recuperati da MongoDB/Flask)_"
    )
    await update.message.reply_text(status_text, parse_mode='Markdown')

async def chatid_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /chatid command."""
    await update.message.reply_text(
        f"Il tuo Chat ID è: `{update.effective_chat.id}`\n\n"
        "Comunica questo ID all'operatore per registrare il tuo dispositivo alla ricezione degli allarmi.",
        parse_mode='Markdown'
    )

async def unknown_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle unrecognized text (Replaces echo_handler)."""
    warning_text = "⚠️ Questo bot accetta solo comandi specifici. Usa /help per la lista."
    await update.message.reply_text(warning_text)

# --- Funzione Utility per il Server Flask ---

async def send_push_notification(application, chat_id: str, message: str) -> None:
    """
    Utility che il server Flask può chiamare per inviare allarmi asincroni.
    """
    await application.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')