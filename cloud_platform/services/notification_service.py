"""
Notification Service
====================
Gestisce la registrazione degli utenti Telegram e l'invio di notifiche
di allarme a tutti gli utenti registrati (operatori ed escursionisti).

Flusso:
    1. Un utente manda /chatid al bot → viene salvato in MongoDB (users_collection).
    2. Quando data_ingestion rileva severity="critical", chiama send_alarm().
    3. send_alarm() carica tutti i chat_id registrati e invia il messaggio
       via il loop asincrono del bot Telegram già in esecuzione.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

USERS_COLLECTION = "users_collection"


class NotificationService:
    """
    Servizio di notifica Telegram per allarmi vulcanici.

    Args:
        db_service:    DatabaseService già connesso a MongoDB.
        telegram_app:  Istanza dell'Application Telegram (da app.py).
                       Se None, le notifiche vengono silenziate (utile nei test).
    """

    def __init__(self, db_service, telegram_app=None):
        self.db_service   = db_service
        self.telegram_app = telegram_app

    # ── Registrazione utenti ─────────────────────────────────────────

    def register_user(self, chat_id: str) -> bool:
        """
        Registra un chat_id per la ricezione degli allarmi.

        Returns:
            True se l'utente è stato registrato, False se era già presente.
        """
        try:
            collection = self.db_service.db[USERS_COLLECTION]
            if collection.find_one({"chat_id": str(chat_id)}):
                return False  # già registrato
            collection.insert_one({
                "chat_id":       str(chat_id),
                "registered_at": datetime.now(timezone.utc).isoformat(),
            })
            logger.info("Utente registrato per notifiche: chat_id=%s", chat_id)
            return True
        except Exception as e:
            logger.error("Errore registrazione utente %s: %s", chat_id, e)
            return False

    def get_registered_users(self) -> list[str]:
        """
        Ritorna la lista di tutti i chat_id registrati.
        """
        try:
            collection = self.db_service.db[USERS_COLLECTION]
            return [doc["chat_id"] for doc in collection.find({})]
        except Exception as e:
            logger.error("Errore lettura utenti registrati: %s", e)
            return []

    # ── Invio allarmi ────────────────────────────────────────────────

    def send_alarm(
        self,
        message:    str,
    ) -> None:
        """
        Invia un messaggio di allarme a tutti gli utenti registrati.

        Args:
            message:    Messaggio descrittivo dal gateway (es. "CRITICAL: Seismic anomaly...").
        """
        if not self.telegram_app:
            logger.warning("Telegram non configurato — allarme non inviato per %s", sensor_id)
            return

        loop = self.telegram_app.bot_data.get("loop")
        if not loop:
            logger.error("Event loop Telegram non disponibile")
            return

        chat_ids = self.get_registered_users()
        if not chat_ids:
            logger.warning("Nessun utente registrato — allarme non inviato")
            return

        alarm_text = self._build_alarm_message(message)

        for chat_id in chat_ids:
            try:
                asyncio.run_coroutine_threadsafe(
                    self.telegram_app.bot.send_message(
                        chat_id=chat_id,
                        text=alarm_text,
                        parse_mode="Markdown",
                    ),
                    loop,
                ).result(timeout=10)
                logger.info("Allarme inviato a chat_id=%s", chat_id)
            except Exception as e:
                logger.error("Errore invio allarme a chat_id=%s: %s", chat_id, e)

    @staticmethod
    def _build_alarm_message(
        message:    str,
    ) -> str:
        """
        Costruisce il testo del messaggio di allarme.
        """
        ts    = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return (
            "🚨 *ALLARME — Vulcano Etna*\n\n"
            f"🔴 *{message}*\n\n"
            f"🕐 Orario:   `{ts}`\n\n"
            "_Questo è un messaggio automatico del sistema di monitoraggio._"
        )
