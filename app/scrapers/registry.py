from __future__ import annotations

import asyncio

import httpx

from app.config import Settings
from app.scrapers.base import SourceAdapter
from app.scrapers.email_alerts import EmailAlertsAdapter
from app.scrapers.pararius import ParariusAdapter
from app.scrapers.public_sources import IamExpatAdapter, VanderlindenAdapter, VerhuurtBeterAdapter
from app.scrapers.restricted import RestrictedAdapter


def build_adapters(settings: Settings, client: httpx.AsyncClient, semaphore: asyncio.Semaphore, db) -> list[SourceAdapter]:
    pararius = ParariusAdapter(settings, client, semaphore)
    pararius.interval = settings.pararius_poll_seconds
    iamexpat = IamExpatAdapter(settings, client, semaphore)
    iamexpat.interval = settings.public_source_poll_seconds
    vanderlinden = VanderlindenAdapter(settings, client, semaphore)
    vanderlinden.interval = settings.public_source_poll_seconds
    verhuurtbeter = VerhuurtBeterAdapter(settings, client, semaphore)
    verhuurtbeter.interval = settings.public_source_poll_seconds
    adapters: list[SourceAdapter] = [
        pararius,
        iamexpat,
        vanderlinden,
        verhuurtbeter,
        RestrictedAdapter("huurexpert", "HuurExpert", "https://www.huurexpert.nl", "Public site describes itself as an aggregator and offers daily email alerts; automated reuse is not verified. Use its authorized email alert workflow.", "REQUIRES_AUTHENTICATION", 3600),
        RestrictedAdapter("kamernet", "Kamernet", "https://kamernet.nl", "Current terms prohibit automated access and systematic extraction; use its own alerts or authorized email forwarding.", "UNSUPPORTED", 3600),
        RestrictedAdapter("funda", "Funda", "https://www.funda.nl", "Current terms prohibit scraping/data mining without prior written permission; use Funda's own alerts or authorized email forwarding.", "UNSUPPORTED", 3600),
        RestrictedAdapter("renthunter", "RentHunter", "https://renthunter.nl", "No public API/feed found; listings are surfaced by its subscription service. Use user-authorized email alerts.", "REQUIRES_AUTHENTICATION", 3600),
        RestrictedAdapter("facebook", "Facebook Marketplace / groups", "https://www.facebook.com/marketplace/", "No general supported personal rental-listing API was found. Use notifications/forwarding configured by the account owner.", "REQUIRES_AUTHENTICATION", 3600),
        RestrictedAdapter("huure", "Huure", "https://huure.nl", "Terms and supported automated access could not be verified; adapter remains disabled pending permission review.", "DISABLED", 3600),
        RestrictedAdapter("rentwebs", "Rentwebs", "https://www.rentwebs.nl", "Full account access is required and no public API/feed was found; use the platform's own email alerts.", "REQUIRES_AUTHENTICATION", 3600),
    ]
    if settings.imap_host and settings.imap_username and settings.imap_password:
        inbox = EmailAlertsAdapter(settings, client, semaphore)
        inbox.attach_database(db)
        adapters.append(inbox)
    else:
        adapters.append(RestrictedAdapter("email_alerts", "User-authorized alert email inbox", "imap://configured-mailbox", "Configure read-only IMAP credentials to ingest platform alerts; credentials are never logged.", "REQUIRES_AUTHENTICATION", settings.imap_poll_seconds))
    email_sources = {
        "pararius_email": ("Pararius alert email", "https://www.pararius.com"),
        "kamernet_email": ("Kamernet alert email", "https://kamernet.nl"),
        "funda_email": ("Funda alert email", "https://www.funda.nl"),
        "huurexpert_email": ("HuurExpert alert email", "https://www.huurexpert.nl"),
        "iamexpat_email": ("IamExpat alert email", "https://www.iamexpat.nl"),
        "renthunter_email": ("RentHunter alert email", "https://renthunter.nl"),
        "rentwebs_email": ("Rentwebs alert email", "https://www.rentwebs.nl"),
        "verhuurtbeter_email": ("VerhuurtBeter alert email", "https://www.verhuurtbeter.nl"),
        "vanderlinden_email": ("Van der Linden alert email", "https://www.vanderlinden.nl"),
        "huure_email": ("Huure alert email", "https://huure.nl"),
        "facebook_email": ("Facebook Marketplace / groups alert email", "https://www.facebook.com/marketplace/"),
    }
    for source_id, (name, url) in email_sources.items():
        db.ensure_source({"source_id": source_id, "name": name, "base_url": url, "adapter_type": "user_authorized_email", "status": "REQUIRES_AUTHENTICATION", "polling_interval_seconds": settings.imap_poll_seconds})
    return adapters
