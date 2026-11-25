from __future__ import annotations

import asyncio
import email
import email.policy
import imaplib
import logging
import re
from collections.abc import AsyncIterator
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from app.config import Settings
from app.extraction import classify_property, detect_housemates, normalize_url, parse_availability, parse_furnishing, parse_money, parse_registration
from app.models import Listing
from app.scrapers.base import SourceAdapter

log = logging.getLogger(__name__)

SOURCE_MAP = {
    "pararius.com": ("pararius_email", "Pararius alert email"),
    "pararius.nl": ("pararius_email", "Pararius alert email"),
    "kamernet.nl": ("kamernet_email", "Kamernet alert email"),
    "funda.nl": ("funda_email", "Funda alert email"),
    "huurexpert.nl": ("huurexpert_email", "HuurExpert alert email"),
    "iamexpat.nl": ("iamexpat_email", "IamExpat alert email"),
    "renthunter.nl": ("renthunter_email", "RentHunter alert email"),
    "rentwebs.nl": ("rentwebs_email", "Rentwebs alert email"),
    "verhuurtbeter.nl": ("verhuurtbeter_email", "VerhuurtBeter alert email"),
    "vanderlinden.nl": ("vanderlinden_email", "Van der Linden alert email"),
    "huure.nl": ("huure_email", "Huure alert email"),
    "facebook.com": ("facebook_email", "Facebook Marketplace / groups alert email"),
    "facebookmail.com": ("facebook_email", "Facebook Marketplace / groups alert email"),
}


def source_for_domain(domain: str) -> tuple[str, str] | None:
    domain = domain.lower().strip().split(":")[-1]
    for suffix, source in SOURCE_MAP.items():
        if domain == suffix or domain.endswith("." + suffix):
            return source
    return None


def _body(message: email.message.Message) -> str:
    parts: list[str] = []
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() not in {"text/plain", "text/html"} or part.get_content_disposition() == "attachment":
                continue
            try:
                content = part.get_content()
            except Exception:
                continue
            if isinstance(content, str):
                parts.append(content)
    else:
        try:
            content = message.get_content()
            if isinstance(content, str):
                parts.append(content)
        except Exception:
            pass
    return "\n".join(parts)


def _looks_like_listing_url(source_id: str, path: str) -> bool:
    path = path.lower()
    known = {
        "pararius": r"/(?:apartment|studio|room)-for-rent/|/(?:appartement|studio|kamer)-te-huur/",
        "funda": r"/detail/huur/|/huur/[^/]+/[^/]+",
        "kamernet": r"/huren/(?:huurwoning|kamer|studio)|/kamer-te-huur/",
        "iamexpat": r"/housing/rental-properties/[^/]+/(?:apartment|room|house)/[^/]+",
        "verhuurtbeter": r"/apartment-for-rent/",
        "huurexpert": r"/(?:huurwoning|woning)/[^/]+",
        "rentwebs": r"/(?:huurwoning|woning)/[^/]+",
        "renthunter": r"/(?:listing|property|woning)/[^/]+",
        "vanderlinden": r"/(?:huurwoning|woning-huren|rental-property)/[^/]+",
        "huure": r"/(?:huurwoning|woning|aanbod)/[^/]+",
        "facebook": r"/marketplace/item/\d+|/groups/[^/]+/permalink/\d+",
    }
    platform = source_id.replace("_email", "")
    if platform in known and re.search(known[platform], path):
        return True
    parts = [part for part in path.strip("/").split("/") if part]
    return len(parts) >= 4 and any(word in path for word in ("rental", "rent", "huur", "apartment", "studio", "room", "kamer", "woning"))


def parse_alert_email(raw_email: bytes, received_at: str | None = None) -> list[Listing]:
    message = email.message_from_bytes(raw_email, policy=email.policy.default)
    sender = email.utils.parseaddr(str(message.get("From", "")))[1]
    domain = sender.rsplit("@", 1)[-1].lower() if "@" in sender else ""
    source = source_for_domain(domain)
    if source is None:
        # Some alert providers use a separate sender; derive source only from official listing links.
        body_html = _body(message)
        soup_probe = BeautifulSoup(body_html, "html.parser")
        domains = {urlsplit(a.get("href", "")).hostname or "" for a in soup_probe.find_all("a", href=True)}
        source = next((source_for_domain(d) for d in domains if source_for_domain(d)), None)
    if source is None:
        return []
    source_id, source_name = source
    body = _body(message)
    soup = BeautifulSoup(body, "html.parser")
    text = "\n".join(s.strip() for s in soup.stripped_strings) if soup.find() else unescape(body)
    detected_date = None
    if message.get("Date"):
        try:
            detected_date = parsedate_to_datetime(str(message.get("Date"))).isoformat()
        except (TypeError, ValueError, OverflowError):
            detected_date = None
    output: dict[str, Listing] = {}
    for anchor in soup.find_all("a", href=True):
        href = unescape(anchor.get("href", "")).strip()
        host = (urlsplit(href).hostname or "").lower()
        if not href.startswith(("http://", "https://")) or not host:
            continue
        matched_source = source_for_domain(host)
        if not matched_source:
            continue
        link_source = matched_source or source
        link_source_id, link_source_name = link_source
        if not _looks_like_listing_url(link_source_id, urlsplit(href).path):
            continue
        url = normalize_url(href)
        card = anchor
        for parent in anchor.parents:
            candidate_text = " ".join(parent.stripped_strings)
            if 25 <= len(candidate_text) <= 1200:
                card = parent
                break
        card_text = " ".join(card.stripped_strings) if card else text
        title = " ".join(anchor.stripped_strings).strip()
        if not title or len(title) < 4 or re.search(r"unsubscribe|uitschrijven|manage preferences|voorkeuren", title, re.I):
            title = card_text[:180]
        rent = parse_money(card_text)
        prop_type, housemates, _ = classify_property(f"{title} {card_text}")
        all_inclusive = bool(re.search(r"\b(?:all[- ]inclusive|all costs included|including (?:all )?utilities and (?:service )?charges)\b", card_text, re.I))
        includes = all_inclusive or bool(re.search(r"\b(?:utilities included|incl\.?(?:usive)?\s+(?:g/w/e|utilities|gas|water|electricity)|inclusief\s+(?:g/w/e|gas|water|elektra))\b", card_text, re.I))
        fee_match = re.search(r"(?:service charges?|service costs?|servicekosten|voorschot)\s*[:\-]?\s*(?:€|EUR)?\s*([\d.,]+)", card_text, re.I)
        fees = parse_money(fee_match.group(1)) if fee_match else None
        total = rent + fees if rent is not None and (all_inclusive or (includes and fees is not None)) else None
        cost_status = "CONFIRMED" if total is not None else "BASE_ONLY" if rent is not None else "UNKNOWN"
        listing = Listing(
            source_id=link_source_id,
            source_name=link_source_name,
            external_id=None,
            url=url,
            title=title[:240],
            description=card_text[:4000] or None,
            city="Amsterdam" if "amsterdam" in card_text.lower() or "amsterdam" in url.lower() else None,
            base_rent_eur=rent,
            monthly_total_eur=total,
            cost_status=cost_status,
            utilities_included=True if includes else None,
            property_type=prop_type,
            housemates=housemates,
            furnishing=parse_furnishing(card_text),
            availability_date=parse_availability(card_text),
            registration=parse_registration(card_text),
            published_at=None,  # Email date is not the source publication timestamp.
            raw_data={"email_received_at": received_at or detected_date, "sender_domain": domain},
        )
        output[url] = listing
    return list(output.values())


class EmailAlertsAdapter(SourceAdapter):
    source_id = "email_alerts"
    name = "User-authorized alert email inbox"
    base_url = "imap://configured-mailbox"
    adapter_type = "imap_readonly"

    def __init__(self, settings: Settings, client, semaphore):
        super().__init__(settings, client, semaphore)
        self.interval = settings.imap_poll_seconds
        self.initial_status = "ACTIVE" if settings.imap_host and settings.imap_username and settings.imap_password else "REQUIRES_AUTHENTICATION"
        self.status = self.initial_status

    async def search_listings(self) -> AsyncIterator[Listing]:
        if self.status == "REQUIRES_AUTHENTICATION":
            return
        try:
            batches = await asyncio.to_thread(self._fetch_messages)
        except Exception as exc:
            self.status = "DEGRADED"
            # Error text avoids usernames/passwords, which may be embedded in provider exceptions.
            self.last_error = f"IMAP error: {type(exc).__name__}"
            log.warning("Alert inbox poll failed (%s)", type(exc).__name__)
            return
        self.status = "ACTIVE"
        self.last_error = None
        for raw, uid in batches:
            for listing in parse_alert_email(raw):
                listing.raw_data["mail_uid"] = uid
                if hasattr(self, "_db"):
                    self._db.update_source(listing.source_id, "ACTIVE", success=True)
                yield listing

    def _fetch_messages(self) -> list[tuple[bytes, str]]:
        mailbox = imaplib.IMAP4_SSL(self.settings.imap_host, self.settings.imap_port, timeout=self.settings.http_timeout)
        messages: list[tuple[bytes, str]] = []
        try:
            mailbox.login(self.settings.imap_username, self.settings.imap_password)
            mailbox.select(self.settings.imap_folder, readonly=True)
            last_uid = int(self._db.get_adapter_state("imap_last_uid") or "0")
            typ, data = mailbox.uid("search", None, f"UID {last_uid + 1}:*")
            if typ != "OK":
                raise RuntimeError("IMAP UID search failed")
            uids = [uid.decode() for uid in (data[0] or b"").split()]
            allowed = self.settings.imap_allowed_domains
            newest_uid = last_uid
            for uid in uids:
                typ, payload = mailbox.uid("fetch", uid, "(RFC822)")
                if typ == "OK":
                    raw = next((part[1] for part in payload if isinstance(part, tuple) and isinstance(part[1], bytes)), None)
                    if raw:
                        msg = email.message_from_bytes(raw, policy=email.policy.default)
                        sender = email.utils.parseaddr(str(msg.get("From", "")))[1]
                        domain = sender.rsplit("@", 1)[-1].lower()
                        if (not allowed or any(domain == d or domain.endswith("." + d) for d in allowed)):
                            messages.append((raw, uid))
                newest_uid = max(newest_uid, int(uid))
            if newest_uid > last_uid:
                self._db.set_adapter_state("imap_last_uid", str(newest_uid))
            return messages
        finally:
            try:
                mailbox.logout()
            except Exception:
                pass

    def attach_database(self, db) -> None:
        self._db = db
