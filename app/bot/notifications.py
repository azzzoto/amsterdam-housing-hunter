from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.i18n import category_it, confidence_it, furnishing_it, match_status_it, reason_it
from app.database import Database
from app.models import Listing
from app.scoring import ScoreResult, score_listing

log = logging.getLogger(__name__)


def _eur(value: float | int | None) -> str:
    return "non specificato" if value is None else f"€{value:,.0f}"


def score_details_text(score: dict) -> str:
    lines = [f"DETTAGLIO PUNTEGGIO — {score.get('total_score', 0)}/100 · {category_it(score.get('category'))}"]
    labels = {
        "monthly_cost": "Costo mensile", "cycling_time": "Tragitto in bici", "accommodation_type": "Alloggio",
        "furnishing": "Arredamento", "availability": "Disponibilità", "registration": "Registrazione BRP",
        "information_completeness": "Completezza delle informazioni",
    }
    for key, label in labels.items():
        part = score.get("breakdown", {}).get(key, {})
        lines.append(f"• {label}: {part.get('score', 0)}/{part.get('maximum', 0)} — {reason_it(part.get('reason'))}")
    if score.get("hard_exclusions"):
        lines.extend(["", "ESCLUSIONI:", *[f"• {reason_it(value)}" for value in score["hard_exclusions"]]])
    if score.get("missing_information"):
        lines.extend(["", "DA VERIFICARE:", *[f"• {reason_it(value)}" for value in score["missing_information"]]])
    lines += ["", f"Attendibilità dei dati: {confidence_it(score.get('data_confidence', 0))}", f"Esito: {match_status_it(score.get('match_status'))}"]
    return "\n".join(lines)


def notification_text(listing: Listing | dict, score: ScoreResult | dict) -> str:
    item = listing.asdict() if isinstance(listing, Listing) else listing
    result = score.asdict() if isinstance(score, ScoreResult) else score
    breakdown = result.get("breakdown", {})
    route = breakdown.get("cycling_time", {})
    accommodation = breakdown.get("accommodation_type", {})
    notification_kind = item.get("notification_kind")
    heading = {
        "UPDATED": "🔄 ANNUNCIO AGGIORNATO",
        "HISTORY": "📚 ANNUNCI RECENTI",
    }.get(notification_kind, "🚨 NUOVO ANNUNCIO")
    lines = [
        f"{heading} — {category_it(result.get('category'))}",
        f"{result.get('total_score', 0)}/100 · {match_status_it(result.get('match_status'))} · ATTENDIBILITÀ {confidence_it(result.get('data_confidence', 0))}",
        "",
        f"🏠 {item.get('title') or 'Annuncio in affitto'}",
        f"📍 {item.get('neighborhood') or item.get('address') or item.get('city') or 'Località non specificata'}",
    ]
    changes = item.get("change_details") or {}
    if item.get("notification_kind") == "UPDATED" and changes:
        change_labels = {
            "title": "Titolo", "base_rent_eur": "Affitto base", "monthly_total_eur": "Costo totale",
            "availability_status": "Disponibilità", "address": "Indirizzo",
            "published_at": "Data di pubblicazione", "updated_at": "Data di aggiornamento",
        }
        lines += ["", "MODIFICHE ALL'ANNUNCIO"]
        for key, detail in changes.items():
            label = change_labels.get(key)
            if key in {"base_rent_eur", "monthly_total_eur"}:
                old_value, new_value = detail.get("from"), detail.get("to")
                lines.append(f"• {label}: {_eur(old_value)} → {_eur(new_value)}")
            elif label:
                lines.append(f"• {label} aggiornato")
            elif key == "source_url":
                lines.append(f"• Trovata un'altra fonte: {detail.get('source_id', 'fonte')}")
    if item.get("base_rent_eur") is not None:
        cost_text = f"{_eur(item.get('base_rent_eur'))}/mese di affitto base"
        if item.get("monthly_total_eur") is not None and item.get("cost_status") == "CONFIRMED":
            cost_text = f"{_eur(item.get('monthly_total_eur'))}/mese, tutto incluso"
        elif item.get("monthly_total_eur") is not None and item.get("cost_status") == "ESTIMATED":
            cost_text = f"{_eur(item.get('monthly_total_eur'))}/mese, totale stimato"
        else:
            cost_text += "; utenze e spese non specificate"
        lines.append(f"💰 {cost_text}")
    else:
        lines.append("💰 Costo mensile non specificato")
    lines.append(f"🚲 {reason_it(route.get('reason') or 'No reliable bicycle route has been calculated.')}")
    lines.append(f"🏘 {reason_it(accommodation.get('reason') or 'Accommodation type could not be established.')}")
    if item.get("furnishing") and item.get("furnishing") != "unknown":
        lines.append(f"🛋 {furnishing_it(item['furnishing'])}")
    else:
        lines.append("🛋 Arredamento non specificato")
    if item.get("housemates") is not None:
        number = item['housemates']
        housemates = "nessun altro coinquilino" if number == 0 else "1 altro coinquilino" if number == 1 else f"{number} altri coinquilini"
        lines.append(f"👥 {housemates}")
    elif item.get("property_type") == "studio" or item.get("property_type") == "independent_apartment":
        lines.append("👥 Alloggio indipendente")
    else:
        lines.append("👥 Numero di coinquilini non specificato")
    availability = item.get("availability_date")
    if availability == "immediately":
        availability = "Subito"
    lines.append(f"📅 Disponibilità: {availability or 'non specificata'}")
    brp = item.get("registration", "unknown")
    lines.append(f"📝 Registrazione BRP: {'consentita' if brp == 'allowed' else 'vietata' if brp == 'prohibited' else 'non specificata — da verificare'}")
    if item.get("deposit_eur") is not None:
        lines.append(f"💶 Deposito: {_eur(item['deposit_eur'])}")
    if item.get("surface_sqm") is not None:
        lines.append(f"📐 Superficie: {item['surface_sqm']:g} m²")
    if item.get("bedrooms") is not None:
        lines.append(f"🛏 Camere da letto: {item['bedrooms']}")
    if item.get("bathrooms") is not None:
        lines.append(f"🛁 Bagni: {item['bathrooms']}")
    lines += ["", "DETTAGLIO PUNTEGGIO"]
    for key, label, icon in (
        ("monthly_cost", "Costo mensile", "💰"), ("cycling_time", "Distanza in bici", "🚲"),
        ("accommodation_type", "Alloggio", "🏠"), ("furnishing", "Arredamento", "🛋"),
        ("availability", "Disponibilità", "📅"), ("registration", "Registrazione BRP", "📝"),
        ("information_completeness", "Completezza delle informazioni", "📋"),
    ):
        part = breakdown.get(key, {})
        lines.append(f"{icon} {label}: {part.get('score', 0)}/{part.get('maximum', 0)}")
    if result.get("hard_exclusions"):
        lines += ["", "⛔ ESCLUSIONE"] + [f"• {reason_it(reason)}" for reason in result["hard_exclusions"]]
    elif result.get("reasons"):
        lines += ["", "PERCHÉ È INTERESSANTE"] + [f"• {reason_it(reason)}" for reason in result["reasons"][:5]]
    missing = result.get("missing_information") or []
    if missing:
        lines += ["", "⚠️ DA VERIFICARE"] + [f"• {reason_it(value)}" for value in missing[:8]]
    if item.get("published_at"):
        lines += ["", f"Pubblicato: {item['published_at']}"]
    else:
        lines += ["", "Pubblicazione: data non disponibile"]
    lines.append(f"Rilevato: {item.get('detected_at') or item.get('first_detected_at') or 'ora'}")
    sources = item.get("sources") or []
    if sources:
        lines += ["", "FONTI E LINK ORIGINALI"]
        lines.extend(f"• {source['name']}: {source['original_url']}" for source in sources[:8])
    else:
        lines.append(f"Fonte: {item.get('source_name', 'non specificata')}")
    return "\n".join(lines)[:4000]


def listing_keyboard(listing: Listing | dict) -> InlineKeyboardMarkup:
    item = listing.asdict() if isinstance(listing, Listing) else listing
    listing_id = item.get("id") or item.get("listing_id")
    sources = item.get("sources") or []
    original_url = item.get("url") or (sources[0].get("original_url") if sources else None)
    rows = [[InlineKeyboardButton("APRI L'ANNUNCIO ORIGINALE", url=original_url)]] if original_url else []
    for source in sources:
        if source.get("original_url") and source["original_url"] != original_url:
            rows.append([InlineKeyboardButton(f"APRI {source.get('name', 'FONTE')[:40]}", url=source["original_url"])])
    contact = item.get("contact_url")
    if not contact and item.get("contact_email"):
        contact = f"mailto:{item['contact_email']}"
    if contact:
        rows.append([InlineKeyboardButton("CONTATTA LOCATORE", url=contact)])
    if listing_id:
        rows.append([
            InlineKeyboardButton("DETTAGLI PUNTEGGIO", callback_data=f"score:{listing_id}"),
            InlineKeyboardButton("MI INTERESSA", callback_data=f"interested:{listing_id}"),
        ])
        rows.append([InlineKeyboardButton("NON FA PER ME", callback_data=f"reject:{listing_id}")])
    return InlineKeyboardMarkup(rows)


class TelegramNotifier:
    def __init__(self, bot, db: Database, scoring_config: dict):
        self.bot = bot
        self.db = db
        self.scoring_config = scoring_config

    async def __call__(self, listing_id: str, listing: Listing, default_score: ScoreResult, event_key: str = "initial", change_details: dict | None = None) -> None:
        for user in self.db.authorized_users():
            personal_score = score_listing(listing, self.scoring_config, user.get("preferences"))
            maximum = float((user.get("preferences") or {}).get("max_monthly", self.scoring_config.get("budget", {}).get("maximum_eur", 1000)))
            if personal_score.match_status == "REJECTED" or (listing.base_rent_eur is not None and listing.base_rent_eur > maximum and listing.cost_status != "CONFIRMED"):
                continue
            score_data = personal_score.asdict()
            if not self.db.record_notification(listing_id, user["telegram_id"], score_data, event_key, change_details):
                continue
            payload = listing.asdict()
            persisted = self.db.get_listing(listing_id) or {}
            payload.update(persisted)
            payload["url"] = listing.url
            payload["id"] = listing_id
            payload["notification_kind"] = "UPDATED" if event_key != "initial" else "NEW"
            payload["change_details"] = change_details or {}
            try:
                sent = await self.bot.send_message(
                    chat_id=user["telegram_id"],
                    text=notification_text(payload, personal_score),
                    reply_markup=listing_keyboard(payload),
                    disable_web_page_preview=True,
                )
                self.db.finish_notification(listing_id, user["telegram_id"], sent.message_id, event_key=event_key)
            except Exception as exc:
                self.db.finish_notification(listing_id, user["telegram_id"], None, type(exc).__name__, event_key)
                log.warning("Telegram send failed (%s)", type(exc).__name__)
