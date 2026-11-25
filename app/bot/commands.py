from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.bot.i18n import source_error_it, source_status_it
from app.bot.notifications import listing_keyboard, notification_text, score_details_text


def _db(context: ContextTypes.DEFAULT_TYPE):
    return context.application.bot_data["db"]


def _score_from_listing(item: dict) -> dict:
    return {
        "total_score": item["suitability_score"], "category": item["score_category"], "match_status": item["match_status"],
        "data_confidence": item["data_confidence"], "breakdown": item["score_breakdown"], "reasons": item["score_reasons"],
        "missing_information": item["missing_information"], "hard_exclusions": item["hard_exclusions"],
    }


async def _send_history(update: Update, db, days: int = 3, limit: int = 5) -> None:
    total = db.history_count(days)
    if not total:
        await update.effective_message.reply_text(f"Nessun annuncio rilevato negli ultimi {days} giorni.")
        return
    count_label = "1 annuncio rilevato" if total == 1 else f"{total} annunci rilevati"
    await update.effective_message.reply_text(
        f"Storico: {count_label} negli ultimi {days} giorni. Te ne mostro {min(total, limit)}."
    )
    for item in db.history_listings(days, limit):
        item["source_name"] = item["sources"][0]["name"] if item["sources"] else "unknown"
        item["detected_at"] = item["first_detected_at"]
        item["notification_kind"] = "HISTORY"
        await update.effective_message.reply_text(
            notification_text(item, _score_from_listing(item)),
            reply_markup=listing_keyboard(item),
            disable_web_page_preview=True,
        )


def _is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user:
        return False
    db = _db(context)
    if user.id in context.application.bot_data["admin_ids"]:
        db.add_user_if_missing(user.id, user.username, role="admin", authorized=True)
    saved = db.get_user(user.id)
    return bool(saved and saved["authorized"] and saved["role"] == "admin")


async def _require_auth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user:
        return False
    if user.id in context.application.bot_data["admin_ids"]:
        _db(context).add_user_if_missing(user.id, user.username, role="admin", authorized=True)
    saved = _db(context).get_user(user.id)
    if saved and saved["authorized"]:
        return True
    if update.effective_message:
        await update.effective_message.reply_text("Per usare il bot devi essere autorizzato. Chiedi all'amministratore un codice monouso e invia /login CODICE.")
    return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    db = _db(context)
    previous = db.get_user(user.id)
    was_authorized = bool(previous and previous["authorized"])
    admin = user.id in context.application.bot_data["admin_ids"]
    db.add_user_if_missing(user.id, user.username, role="admin" if admin else "user", authorized=admin)
    saved = db.get_user(user.id)
    if saved and saved["authorized"]:
        stats = db.stats()
        monitoring = "PAUSED" if db.is_paused() else "RUNNING"
        await update.effective_message.reply_text(
            f"Amsterdam Housing Hunter è pronto.\nMonitoraggio: {'IN PAUSA' if monitoring == 'PAUSED' else 'ATTIVO'}\nFonti funzionanti: {stats['functioning_sources']}/{stats['sources']}\nUsa /latest o /history per vedere gli annunci; /status mostra lo stato delle fonti."
        )
        if not was_authorized:
            await _send_history(update, db)
    else:
        await update.effective_message.reply_text("Benvenuto! Questo bot è privato. Chiedi all'amministratore un codice di attivazione e invia /login CODICE.")


async def login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    if not context.args:
        await update.effective_message.reply_text("Uso: /login CODICE_MONOUSO")
        return
    db = _db(context)
    previous = db.get_user(user.id)
    was_authorized = bool(previous and previous["authorized"])
    role = db.redeem_activation_code(context.args[0], user.id, user.username)
    if not role:
        await update.effective_message.reply_text("Il codice non è valido, è scaduto oppure è già stato usato.")
        return
    await update.effective_message.reply_text(f"Accesso autorizzato come {'amministratore' if role == 'admin' else 'utente'}. Usa /status per vedere lo stato del monitoraggio.")
    if not was_authorized:
        await _send_history(update, db)


async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    _db(context).revoke_user(user.id)
    await update.effective_message.reply_text("Il tuo accesso al bot è stato revocato. Per rientrare, usa /login con un nuovo codice.")


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_auth(update, context):
        return
    user = _db(context).get_user(update.effective_user.id)
    role = "amministratore" if user["role"] == "admin" else "utente"
    lines = [f"ID Telegram: {user['telegram_id']}", f"Ruolo: {role}", f"Autorizzato: {'sì' if user['authorized'] else 'no'}", f"Registrato il: {user['registered_at']}"]
    await update.effective_message.reply_text("\n".join(lines))


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_auth(update, context):
        return
    db = _db(context)
    stats = db.stats()
    rows = db.source_rows()
    monitoring = "IN PAUSA" if db.is_paused() else "ATTIVO"
    lines = [f"Monitoraggio: {monitoring}", f"Fonti funzionanti: {stats['functioning_sources']}/{stats['sources']}", f"Annunci rilevati oggi: {stats['listings_today']}", f"Avvisi inviati oggi: {stats['alerts_today']}"]
    lines += ["", "Controllo delle fonti:"]
    for row in rows:
        lines.append(f"• {row['name']}: {source_status_it(row['status'])} · ultimo controllo riuscito: {row['last_success_at'] or 'mai'}")
    await update.effective_message.reply_text("\n".join(lines))


async def latest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_auth(update, context):
        return
    rows = _db(context).latest_listings(5)
    if not rows:
        await update.effective_message.reply_text("Non è ancora stato rilevato nessun annuncio.")
        return
    for item in rows:
        item["source_name"] = item["sources"][0]["name"] if item["sources"] else "unknown"
        item["detected_at"] = item["first_detected_at"]
        item["notification_kind"] = "HISTORY"
        await update.effective_message.reply_text(notification_text(item, _score_from_listing(item)), reply_markup=listing_keyboard(item), disable_web_page_preview=True)


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_auth(update, context):
        return
    days = 3
    if context.args:
        try:
            days = int(context.args[0])
        except ValueError:
            await update.effective_message.reply_text("Uso: /history [giorni], da 1 a 30.")
            return
    if not 1 <= days <= 30:
        await update.effective_message.reply_text("Scegli un periodo da 1 a 30 giorni.")
        return
    await _send_history(update, _db(context), days=days, limit=10)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_auth(update, context):
        return
    data = _db(context).stats()
    lines = [f"Fonti monitorate: {data['sources']}", f"Fonti funzionanti: {data['functioning_sources']}", f"Annunci archiviati: {data['total_listings']}", f"Rilevati oggi: {data['listings_today']}", f"Avvisi inviati oggi: {data['alerts_today']}", "", "Stato delle fonti:"]
    lines += [f"• {source_status_it(status)}: {count}" for status, count in sorted(data["sources_by_status"].items())]
    await update.effective_message.reply_text("\n".join(lines))


async def sources(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_auth(update, context):
        return
    rows = _db(context).source_rows()
    lines = ["Stato delle fonti:"]
    for row in rows:
        detail = f"ultimo controllo riuscito: {row['last_success_at']}" if row["last_success_at"] else "nessun controllo riuscito"
        if row["last_error"]:
            detail += f" · dettaglio: {source_error_it(row['last_error'])}"
        lines.append(f"• {row['name']} — {source_status_it(row['status'])} (ogni {row['polling_interval_seconds']} s): {detail}")
    await update.effective_message.reply_text("\n".join(lines)[:4000])


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_auth(update, context):
        return
    db = _db(context)
    user = db.get_user(update.effective_user.id)
    prefs = user["preferences"]
    if len(context.args) == 2:
        key = context.args[0].lower()
        aliases = {"budget": "max_monthly", "max_monthly": "max_monthly", "ideal_monthly": "ideal_monthly", "cycling": "max_cycling_minutes", "max_cycling_minutes": "max_cycling_minutes"}
        key = aliases.get(key)
        if key is None:
            await update.effective_message.reply_text("Impostazioni: /settings max_monthly 1000, /settings ideal_monthly 950 oppure /settings max_cycling_minutes 25")
            return
        try:
            value = float(context.args[1])
            if value <= 0:
                raise ValueError
        except ValueError:
            await update.effective_message.reply_text("Inserisci un numero maggiore di zero.")
            return
        prefs[key] = value
        db.set_preferences(update.effective_user.id, prefs)
    max_monthly = prefs.get("max_monthly", 1000)
    ideal = prefs.get("ideal_monthly", 950)
    cycling = prefs.get("max_cycling_minutes", 25)
    await update.effective_message.reply_text(
        f"Preferenze di ricerca\nCittà: Amsterdam\nAlloggi accettati: monolocale/appartamento indipendente o stanza privata con al massimo un altro coinquilino\nBudget ideale tutto incluso: €{ideal:,.0f}/mese\nBudget massimo confermato tutto incluso: €{max_monthly:,.0f}/mese\nTempo massimo preferito in bici: {cycling:g} minuti\nArredamento: qualsiasi (preferito arredato)\nRegistrazione BRP: mostrata, non è un criterio di esclusione\n\nModifica: /settings max_monthly 1000 | /settings ideal_monthly 950 | /settings max_cycling_minutes 25"
    )


async def pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_auth(update, context):
        return
    if not _is_admin(update, context):
        await update.effective_message.reply_text("Solo un amministratore può mettere in pausa il monitoraggio.")
        return
    _db(context).set_paused(True)
    await update.effective_message.reply_text("Monitoraggio in pausa.")


async def resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_auth(update, context):
        return
    if not _is_admin(update, context):
        await update.effective_message.reply_text("Solo un amministratore può riavviare il monitoraggio.")
        return
    _db(context).set_paused(False)
    await update.effective_message.reply_text("Monitoraggio riavviato.")


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_auth(update, context):
        return
    if not _is_admin(update, context):
        await update.effective_message.reply_text("Comando riservato agli amministratori.")
        return
    users = _db(context).authorized_users()
    await update.effective_message.reply_text(f"Comandi amministratore\nUtenti autorizzati: {len(users)}\n/generate_code [user|admin]\n/revoke_user ID_TELEGRAM")


async def generate_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_auth(update, context):
        return
    if not _is_admin(update, context):
        await update.effective_message.reply_text("Comando riservato agli amministratori.")
        return
    role = context.args[0].lower() if context.args else "user"
    if role not in {"user", "admin"}:
        await update.effective_message.reply_text("Uso: /generate_code [user|admin]")
        return
    code = _db(context).issue_activation_code(update.effective_user.id, role=role)
    await update.effective_message.reply_text(f"Codice monouso per {'amministratore' if role == 'admin' else 'utente'} (valido 24 ore):\n{code}\nInvialo in privato. Non viene scritto nei log.")


async def revoke_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_auth(update, context):
        return
    if not _is_admin(update, context):
        await update.effective_message.reply_text("Comando riservato agli amministratori.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("Uso: /revoke_user ID_TELEGRAM")
        return
    target = int(context.args[0])
    if target == update.effective_user.id:
        await update.effective_message.reply_text("Non puoi revocare qui il tuo stesso accesso amministratore.")
        return
    removed = _db(context).revoke_user(target)
    await update.effective_message.reply_text("Accesso revocato." if removed else "Nessun utente corrispondente trovato.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Comandi disponibili\n/start — messaggio iniziale e stato del monitoraggio\n/login CODICE — attiva un account\n/logout — revoca il tuo accesso\n/profile — mostra il tuo profilo\n/status — stato del monitoraggio e delle fonti\n/latest — ultimi annunci rilevati\n/history [giorni] — storico recente (predefinito: 3 giorni)\n/stats — statistiche su fonti e annunci\n/sources — stato di ogni fonte\n/settings — visualizza o modifica le tue preferenze\n/pause, /resume — comandi admin per il monitoraggio\n/admin — comandi amministratore\n/generate_code [user|admin] — solo admin\n/revoke_user ID — solo admin\n/help — mostra questo aiuto\n\nOgni annuncio include il link originale e il pulsante per i dettagli del punteggio."
    )
    await update.effective_message.reply_text(text)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user:
        return
    db = _db(context)
    user = db.get_user(query.from_user.id)
    if not user or not user["authorized"]:
        await query.answer("Devi essere autorizzato per usare questo pulsante.", show_alert=True)
        return
    try:
        action, listing_id = query.data.split(":", 1)
    except (AttributeError, ValueError):
        await query.answer("Questo pulsante non è più valido.", show_alert=True)
        return
    listing = db.get_listing(listing_id)
    if not listing:
        await query.answer("Annuncio non trovato.", show_alert=True)
        return
    if action == "score":
        snapshot = db.notification_score(listing_id, query.from_user.id)
        if not snapshot:
            snapshot = {"total_score": listing["suitability_score"], "category": listing["score_category"], "match_status": listing["match_status"], "data_confidence": listing["data_confidence"], "breakdown": listing["score_breakdown"], "missing_information": listing["missing_information"], "hard_exclusions": listing["hard_exclusions"]}
        await query.answer()
        await query.message.reply_text(score_details_text(snapshot))
        return
    if action in {"interested", "reject"}:
        interaction = "interested" if action == "interested" else "not_suitable"
        db.record_interaction(listing_id, query.from_user.id, interaction)
        await query.answer("Salvato tra gli annunci che ti interessano." if action == "interested" else "Annuncio segnato come non adatto.")
        return
    await query.answer("Azione non riconosciuta.", show_alert=True)
