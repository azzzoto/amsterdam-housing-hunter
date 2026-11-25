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
