from __future__ import annotations

from telegram import BotCommand
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from app.bot import commands
from app.config import Settings
from app.database import Database


ITALIAN_COMMANDS = [
    BotCommand("start", "Avvia il bot e mostra gli annunci recenti"),
    BotCommand("login", "Accedi con un codice di attivazione"),
    BotCommand("logout", "Revoca il tuo accesso"),
    BotCommand("profile", "Mostra il tuo profilo"),
    BotCommand("status", "Stato del monitoraggio e delle fonti"),
    BotCommand("latest", "Mostra gli ultimi annunci rilevati"),
    BotCommand("history", "Consulta lo storico degli annunci"),
    BotCommand("stats", "Statistiche su fonti e annunci"),
    BotCommand("sources", "Stato dettagliato delle fonti"),
    BotCommand("settings", "Visualizza o modifica le preferenze"),
    BotCommand("pause", "Metti in pausa il monitoraggio (admin)"),
    BotCommand("resume", "Riavvia il monitoraggio (admin)"),
    BotCommand("admin", "Comandi amministratore"),
    BotCommand("generate_code", "Genera un codice di accesso (admin)"),
    BotCommand("revoke_user", "Revoca l'accesso a un utente (admin)"),
    BotCommand("help", "Mostra l'elenco dei comandi"),
]


def create_application(settings: Settings, db: Database) -> Application:
    application = Application.builder().token(settings.telegram_token).build()
    application.bot_data["db"] = db
    application.bot_data["admin_ids"] = settings.telegram_admin_ids
    application.add_handler(CommandHandler("start", commands.start))
    application.add_handler(CommandHandler("login", commands.login))
    application.add_handler(CommandHandler("logout", commands.logout))
    application.add_handler(CommandHandler("profile", commands.profile))
    application.add_handler(CommandHandler("status", commands.status))
    application.add_handler(CommandHandler("latest", commands.latest))
    application.add_handler(CommandHandler("history", commands.history))
    application.add_handler(CommandHandler("stats", commands.stats))
    application.add_handler(CommandHandler("sources", commands.sources))
    application.add_handler(CommandHandler("settings", commands.settings_command))
    application.add_handler(CommandHandler("pause", commands.pause))
    application.add_handler(CommandHandler("resume", commands.resume))
    application.add_handler(CommandHandler("admin", commands.admin))
    application.add_handler(CommandHandler("generate_code", commands.generate_code))
    application.add_handler(CommandHandler("revoke_user", commands.revoke_user))
    application.add_handler(CommandHandler("help", commands.help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, commands.menu_text))
    application.add_handler(CallbackQueryHandler(commands.callback_handler))
    return application
