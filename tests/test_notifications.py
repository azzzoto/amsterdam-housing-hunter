import asyncio
from dataclasses import replace

from app.bot.notifications import TelegramNotifier, listing_keyboard, notification_text, score_details_text
from app.models import Listing
from app.scoring import score_listing


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return type("Sent", (), {"message_id": len(self.sent)})()


def test_notification_contains_score_breakdown_and_original_url(scoring_config):
    listing = Listing(source_id="pararius", source_name="Pararius", url="https://www.pararius.com/exact/listing/", title="Private studio", base_rent_eur=900, cost_status="BASE_ONLY", property_type="studio", surface_sqm=28)
    score = score_listing(listing, scoring_config)
    text = notification_text(listing, score)
    keyboard = listing_keyboard({**listing.asdict(), "id": "listing-id"})
    assert "DETTAGLIO PUNTEGGIO" in text
    assert "Costo mensile" in text
    assert "utenze e spese non specificate" in text
    assert "Superficie: 28 m²" in text
    assert "ATTENDIBILITÀ" in text
    assert keyboard.inline_keyboard[0][0].url == listing.url
    assert any(button.text == "DETTAGLI PUNTEGGIO" and button.callback_data == "score:listing-id" for row in keyboard.inline_keyboard for button in row if button.callback_data)
    assert keyboard.inline_keyboard[0][0].text == "APRI L'ANNUNCIO ORIGINALE"


def test_score_details_are_in_italian(scoring_config):
    listing = Listing(source_id="pararius", source_name="Pararius", url="https://example.test/a", title="Studio", base_rent_eur=900, cost_status="BASE_ONLY", property_type="studio")
    score = score_listing(listing, scoring_config).asdict()
    text = score_details_text(score)
    assert "DETTAGLIO PUNTEGGIO" in text
    assert "Attendibilità dei dati" in text
    assert "DA VERIFICARE" in text


def test_latest_keyboard_uses_a_retained_original_source_url():
    keyboard = listing_keyboard({
        "id": "listing-id",
        "sources": [
            {"name": "Pararius", "original_url": "https://www.pararius.com/listing/1"},
            {"name": "IamExpat", "original_url": "https://www.iamexpat.nl/listing/2"},
        ],
    })
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    assert buttons[0].url == "https://www.pararius.com/listing/1"
    assert any(button.url == "https://www.iamexpat.nl/listing/2" for button in buttons if button.url)


def test_notifier_skips_rejected_and_proven_out_of_budget_rows(db, scoring_config):
    db.ensure_source({"source_id": "pararius", "name": "Pararius", "base_url": "https://pararius.com", "adapter_type": "html", "status": "ACTIVE", "polling_interval_seconds": 120})
    db.add_user_if_missing(2001, "viewer", authorized=True)
    low = Listing(source_id="pararius", source_name="Pararius", url="https://example.test/too-high", title="Apartment", base_rent_eur=1200, cost_status="BASE_ONLY", property_type="independent_apartment")
    saved = db.upsert_listing(low, score_listing(low, scoring_config))
    bot = FakeBot()
    notifier = TelegramNotifier(bot, db, scoring_config)
    asyncio.run(notifier(saved["id"], low, score_listing(low, scoring_config)))
    assert bot.sent == []

    suitable = replace(low, url="https://example.test/possible", title="Studio", base_rent_eur=950, property_type="studio")
    saved = db.upsert_listing(suitable, score_listing(suitable, scoring_config))
    asyncio.run(notifier(saved["id"], suitable, score_listing(suitable, scoring_config)))
    assert len(bot.sent) == 1
    assert "DA VERIFICARE" in bot.sent[0]["text"]


def test_user_monthly_maximum_filters_alerts_and_keeps_uncertain_under_limit(db, scoring_config):
    db.ensure_source({"source_id": "pararius", "name": "Pararius", "base_url": "https://pararius.com", "adapter_type": "html", "status": "ACTIVE", "polling_interval_seconds": 120})
    db.add_user_if_missing(2002, "viewer", authorized=True)
    db.set_preferences(2002, {"max_monthly": 900})
    bot = FakeBot()
    notifier = TelegramNotifier(bot, db, scoring_config)

    above = Listing(source_id="pararius", source_name="Pararius", url="https://example.test/above", title="Studio sopra il limite", base_rent_eur=901, cost_status="BASE_ONLY", property_type="studio")
    saved = db.upsert_listing(above, score_listing(above, scoring_config))
    asyncio.run(notifier(saved["id"], above, score_listing(above, scoring_config)))
    assert bot.sent == []

    uncertain = replace(above, url="https://example.test/uncertain", title="Studio da verificare", base_rent_eur=850)
    saved = db.upsert_listing(uncertain, score_listing(uncertain, scoring_config))
    asyncio.run(notifier(saved["id"], uncertain, score_listing(uncertain, scoring_config)))
    assert len(bot.sent) == 1
    assert "da verificare" in bot.sent[0]["text"].lower()


def test_same_listing_initial_alert_is_only_sent_once_per_user(db, scoring_config):
    db.ensure_source({"source_id": "pararius", "name": "Pararius", "base_url": "https://pararius.com", "adapter_type": "html", "status": "ACTIVE", "polling_interval_seconds": 120})
    db.add_user_if_missing(2003, "viewer", authorized=True)
    listing = Listing(source_id="pararius", source_name="Pararius", url="https://example.test/once", title="Studio da notificare", base_rent_eur=900, property_type="studio")
    saved = db.upsert_listing(listing, score_listing(listing, scoring_config))
    bot = FakeBot()
    notifier = TelegramNotifier(bot, db, scoring_config)

    asyncio.run(notifier(saved["id"], listing, score_listing(listing, scoring_config)))
    asyncio.run(notifier(saved["id"], listing, score_listing(listing, scoring_config)))

    assert len(bot.sent) == 1
