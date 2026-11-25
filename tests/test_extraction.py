from email.message import EmailMessage

from app.extraction import classify_property, detect_housemates, normalize_url, parse_availability, parse_bedrooms, parse_money, parse_public_listing_cards, parse_surface_area
from app.scrapers.email_alerts import parse_alert_email


def test_parse_dutch_and_english_money():
    assert parse_money("€ 1.234,56 per maand") == 1234.56
    assert parse_money("€950/month") == 950
    assert parse_money("EUR 1,000 per month") == 1000
    assert parse_money("price on request") is None
    assert parse_money("Amsterdam 1017 AW, 2 bedrooms and 1200 per month") == 1200
    assert parse_money("Amsterdam 1017 AW, 2 bedrooms") is None


def test_bedroom_area_and_availability_extraction():
    assert parse_bedrooms("2 bedroom apartment · 68 m²") == 2
    assert parse_surface_area("2 bedroom apartment · 68,5 m²") == 68.5
    assert parse_availability("Available from December 1st, 2026") == "2026-12-01"
    assert parse_availability("Beschikbaar vanaf 1 december 2026") == "2026-12-01"


def test_housemate_phrases_do_not_confuse_bedrooms_with_residents():
    assert detect_housemates("Private room with one other flatmate") == (1, None)
    assert detect_housemates("Share the apartment with one other professional") == (1, None)
    assert detect_housemates("Sharing with one huisgenoot") == (1, None)
    assert detect_housemates("We delen een appartement met twee personen") == (2, None)
    assert detect_housemates("Geen andere bewoners") == (0, None)
    assert detect_housemates("Two people sharing an apartment") == (1, None)
    assert detect_housemates("Three housemates") == (3, None)
    assert detect_housemates("2 bedroom apartment") == (None, None)
    assert detect_housemates("Shared bedroom in a student dorm") == (None, "shared_bedroom")


def test_type_and_housemates():
    assert classify_property("Furnished studio apartment") == ("studio", None, 0)
    assert classify_property("Private room in a shared apartment with two roommates")[0:2] == ("private_room", 2)
    assert classify_property("2 bedroom apartment")[0] == "independent_apartment"


def test_public_cards_preserve_unknown_utilities_and_original_url():
    html = '''<div class="listing"><a href="/apartment-for-rent/amsterdam/abc/singel-460">Studio Singel 460</a><p>€ 950 per month · 28 m²</p></div>'''
    results = parse_public_listing_cards(html, "https://www.pararius.com", "pararius", "Pararius")
    assert len(results) == 1
    assert results[0].url == "https://www.pararius.com/apartment-for-rent/amsterdam/abc/singel-460"
    assert results[0].base_rent_eur == 950
    assert results[0].monthly_total_eur is None
    assert results[0].cost_status == "BASE_ONLY"
    assert results[0].published_at is None
    assert results[0].surface_sqm == 28


def test_url_normalization_removes_tracking_not_listing_path():
    assert normalize_url("HTTPS://EXAMPLE.COM/path/?utm_source=mail&foo=x#top") == "https://example.com/path/?foo=x"


def test_email_alert_does_not_treat_mail_date_as_publication_date():
    message = EmailMessage()
    message["From"] = "alerts@pararius.com"
    message["Subject"] = "New listing"
    message["Date"] = "Tue, 25 Nov 2026 10:00:00 +0100"
    message.set_content('<html><body><a href="https://www.pararius.com/studio-for-rent/amsterdam/x/detail/studio-address">Studio Amsterdam</a><p>€900 per month</p></body></html>', subtype="html")
    listings = parse_alert_email(message.as_bytes())
    assert len(listings) == 1
    assert listings[0].source_id == "pararius_email"
    assert listings[0].published_at is None
    assert listings[0].raw_data["email_received_at"]


def test_authorized_facebook_listing_email_uses_official_marketplace_link():
    message = EmailMessage()
    message["From"] = "notification@facebookmail.com"
    message["Subject"] = "Marketplace listing"
    message.set_content('<html><body><a href="https://www.facebook.com/marketplace/item/123456789/">Studio in Amsterdam</a><p>€900/month</p></body></html>', subtype="html")
    listings = parse_alert_email(message.as_bytes())
    assert len(listings) == 1
    assert listings[0].source_id == "facebook_email"
