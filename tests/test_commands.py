import asyncio
from types import SimpleNamespace

from app.bot.commands import history, start
from app.models import Listing
from app.scoring import score_listing


class FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))


def test_first_admin_start_shows_recent_listing_history(db, scoring_config):
    db.ensure_source({"source_id": "pararius", "name": "Pararius", "base_url": "https://pararius.com", "adapter_type": "html", "status": "ACTIVE", "polling_interval_seconds": 120})
    listing = Listing(
        source_id="pararius", source_name="Pararius", url="https://pararius.com/listing/123",
        title="Private studio", city="Amsterdam", base_rent_eur=900, cost_status="BASE_ONLY",
        property_type="studio",
    )
    db.upsert_listing(listing, score_listing(listing, scoring_config))
    message = FakeMessage()
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42, username="admin"), effective_message=message)
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": db, "admin_ids": (42,)}), args=[])

    asyncio.run(start(update, context))

    assert "Monitoraggio: ATTIVO" in message.replies[0][0]
    assert "1 annuncio rilevato negli ultimi 3 giorni" in message.replies[1][0]
    assert "ANNUNCI RECENTI" in message.replies[2][0]
    assert "Private studio" in message.replies[2][0]
    assert message.replies[2][1]["reply_markup"].inline_keyboard[0][0].url == listing.url
    assert db.get_user(42)["authorized"] == 1


def test_history_command_shows_recent_window(db, scoring_config):
    db.ensure_source({"source_id": "pararius", "name": "Pararius", "base_url": "https://pararius.com", "adapter_type": "html", "status": "ACTIVE", "polling_interval_seconds": 120})
    listing = Listing(
        source_id="pararius", source_name="Pararius", url="https://pararius.com/listing/456",
        title="Room in shared apartment", city="Amsterdam", base_rent_eur=800, cost_status="BASE_ONLY",
        property_type="private_room", housemates=None,
    )
    db.upsert_listing(listing, score_listing(listing, scoring_config))
    db.add_user_if_missing(84, "member", authorized=True)
    message = FakeMessage()
    update = SimpleNamespace(effective_user=SimpleNamespace(id=84, username="member"), effective_message=message)
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": db, "admin_ids": ()}), args=["7"])

    asyncio.run(history(update, context))

    assert "negli ultimi 7 giorni" in message.replies[0][0]
    assert "Room in shared apartment" in message.replies[1][0]
