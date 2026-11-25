from __future__ import annotations

import json
import re
from datetime import date
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from app.models import Listing

MONEY_RE = re.compile(r"(?:€|EUR\s*)(\s*[\d.,]+)", re.IGNORECASE)
ROOMMATE_WORDS = r"(?:housemates?|roommates?|flatmates?|huisgenoot(?:en)?|medebewoners?|bewoners?|personen|people|persons?|others)"
MONTHS = {
    "januari": 1, "january": 1, "februari": 2, "february": 2, "maart": 3, "march": 3,
    "april": 4, "mei": 5, "may": 5, "juni": 6, "june": 6, "juli": 7, "july": 7,
    "augustus": 8, "august": 8, "september": 9, "oktober": 10, "october": 10,
    "november": 11, "december": 12,
}


def parse_money(value: str | None) -> float | None:
    if not value:
        return None
    match = MONEY_RE.search(value)
    if match:
        raw = match.group(1).strip()
    else:
        # Accept a bare amount only when it is unambiguous (a standalone value
        # or explicitly tied to a monthly-rent label). Never concatenate every
        # number in a card such as "Amsterdam 1017 AW, 2 bedrooms".
        monthly = re.search(
            r"(?<![\w])([\d][\d.,]*)\s*(?:/\s*(?:month|maand)|per\s+(?:month|maand)|p\s*/\s*m(?:onth)?|(?:eur|euro)\s*(?:per\s+month|per\s+maand))\b",
            value,
            re.IGNORECASE,
        )
        if monthly:
            raw = monthly.group(1).strip()
        elif re.fullmatch(r"\s*[\d][\d.,]*\s*", value):
            raw = value.strip()
        else:
            return None
    raw = re.sub(r"[^\d.,]", "", raw)
    if not raw:
        return None
    if "," in raw and "." in raw:
        # Dutch display convention: 1.234,56
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        tail = raw.rsplit(",", 1)[-1]
        raw = raw.replace(",", ".") if len(tail) == 2 else raw.replace(",", "")
    elif "." in raw:
        tail = raw.rsplit(".", 1)[-1]
        if len(tail) == 3:
            raw = raw.replace(".", "")
    try:
        return float(raw)
    except ValueError:
        return None


def parse_count(value: str | None) -> int | None:
    if not value:
        return None
    return int(value) if value.isdigit() else None


def parse_bedrooms(text: str | None) -> int | None:
    if not text:
        return None
    low = unescape(text).lower()
    words = {"one": 1, "een": 1, "two": 2, "twee": 2, "three": 3, "drie": 3, "four": 4, "vier": 4, "five": 5, "vijf": 5}
    match = re.search(r"\b(\d+|one|two|three|four|five|een|twee|drie|vier|vijf)\s*(?:bedrooms?|slaapkamers?)\b", low)
    if not match:
        return 0 if re.search(r"\bstudio\b", low) else None
    return int(match.group(1)) if match.group(1).isdigit() else words[match.group(1)]


def parse_surface_area(text: str | None) -> float | None:
    if not text:
        return None
    match = re.search(r"\b(\d+(?:[.,]\d+)?)\s*(?:m²|m2|sqm)(?=\s|$|[,;·)])", unescape(text), re.I)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def parse_bathrooms(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"\b(\d+)\s*(?:bathrooms?|badkamers?)\b", unescape(text), re.I)
    return int(match.group(1)) if match else None


def parse_deposit(text: str | None) -> float | None:
    if not text:
        return None
    match = re.search(r"(?:deposit|security deposit|borg|waarborgsom)\s*[:\-]?\s*(?:€|EUR)?\s*([\d.,]+)", text, re.I)
    return parse_money(match.group(1)) if match else None


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query_parts = [p for p in parts.query.split("&") if p and not p.lower().startswith(("utm_", "fbclid=", "gclid="))]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", "&".join(query_parts), ""))


def _number(word: str) -> int | None:
    if word.isdigit():
        return int(word)
    return {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "een": 1, "twee": 2, "drie": 3, "vier": 4, "vijf": 5}.get(word.lower())


def detect_housemates(text: str) -> tuple[int | None, str | None]:
    text = unescape(text or "").lower()
    if re.search(r"\b(shared|sharing|gedeelde?)\s+(?:a\s+)?bed(?:room|den|den)?\b|\bbedspace\b|\bbunk\s*bed\b|\bbed op kamer\b", text):
        return None, "shared_bedroom"
    if re.search(r"\b(?:no|zero)\s+(?:other\s+)?(?:housemates?|roommates?|flatmates?|huisgenoot(?:en)?|medebewoners|bewoners?|people|persons?)\b|\bgeen\s+(?:(?:other|andere)\s+)?(?:housemates?|roommates?|flatmates?|huisgenoot(?:en)?|medebewoners|bewoners?|people|persons?|personen)\b|\blive alone\b|\bzelfstandig wonen\b", text):
        return 0, None
    # A total household count includes the renter: two people sharing means one other person.
    match = re.search(r"\b(two|three|four|twee|drie|vier|\d+)\s+(?:people|persons|personen)\s+(?:sharing|share|delen|delen samen)\b", text)
    if match:
        total_people = _number(match.group(1))
        return max(0, total_people - 1) if total_people is not None else None, None
    # Explicit count of other household members.
    pattern = rf"\b(one|two|three|four|five|een|twee|drie|vier|vijf|\d+)\s+(?:other\s+)?{ROOMMATE_WORDS}\b"
    match = re.search(pattern, text)
    if match:
        return _number(match.group(1)), None
    patterns = [
        r"\b(?:share|sharing|shared|living|live|living together|samenwonen|delen|gedeeld)\s+(?:(?:an?|the)\s+)?(?:apartment|flat|house|woning|appartement|huis)\s+(?:with|met)\s+(one|two|three|four|five|een|twee|drie|vier|vijf|\d+)\s+(?:other\s+)?(?:people|persons?|professional(?:s)?|students?|adults?|tenants?|occupants|residents|housemates?|roommates?|flatmates?|huisgenoot(?:en)?)\b",
        r"\b(?:share|sharing|living|live|delen|samenwonen)\s+(?:with|met)\s+(one|two|three|four|five|een|twee|drie|vier|vijf|\d+)\s+(?:other\s+)?(?:people|persons?|professional(?:s)?|students?|adults?|tenants?|occupants|residents|housemates?|roommates?|flatmates?|huisgenoot(?:en)?)\b",
    ]
    for pat in patterns:
        match = re.search(pat, text)
        if match:
            return _number(match.group(1)), None
    # A stated maximum occupancy is useful only when the advertisement says it is a shared home.
    match = re.search(r"\b(?:max(?:imum)?|up to|maximaal)\s+(\d+)\s+(?:occupants?|bewoners|personen)\b", text)
    if match and re.search(r"\b(shared|sharing|gedeeld|delen|room|kamer)\b", text):
        return max(0, int(match.group(1)) - 1), None
    return None, None


def classify_property(text: str) -> tuple[str, int | None, int | None]:
    low = unescape(text or "").lower()
    housemates, issue = detect_housemates(low)
    if issue == "shared_bedroom":
        return "shared_bedroom", housemates, None
    bedroom_count = parse_bedrooms(low)
    if re.search(r"\b(studio|studio apartment|studio-appartement|zelfstandige studio)\b", low):
        return "studio", housemates, 0
    if re.search(r"\b(private room|room for rent|room available|kamer te huur|privékamer|eigen kamer|room in shared|room in a shared)\b", low):
        return "private_room", housemates, bedroom_count
    if re.search(r"\b(apartment|appartement|flat|woning|independent apartment|zelfstandige woonruimte)\b", low):
        return "independent_apartment", housemates, bedroom_count
    return "unknown", housemates, None


def parse_availability(text: str) -> str | None:
    low = (text or "").lower()
    if re.search(r"\b(immediately|available now|per direct|direct beschikbaar|direct te huur|immediate availability)\b", low):
        return "immediately"
    month_names = "|".join(sorted(MONTHS, key=len, reverse=True))
    patterns = (
        rf"\b(?:available|beschikbaar|vanaf|per)\s+(?:from\s+)?(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({month_names})(?:\s*,?\s*(\d{{4}}))?\b",
        rf"\b(?:available|beschikbaar|from|vanaf)\s+(?:from\s+)?({month_names})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s*(\d{{4}}))?\b",
    )
    for index, pattern in enumerate(patterns):
        match = re.search(pattern, low)
        if not match:
            continue
        if index == 0:
            day, month_word, year_word = match.groups()
        else:
            month_word, day, year_word = match.groups()
        month = MONTHS.get(month_word)
        if month:
            day_number = int(day)
            today = date.today()
            year = int(year_word) if year_word else today.year
            if not year_word and (month, day_number) < (today.month, today.day):
                year += 1
            try:
                return date(year, month, day_number).isoformat()
            except ValueError:
                return None
    iso_match = re.search(r"\b(?:available|beschikbaar)\s+(?:from\s+)?(20\d{2}-\d{2}-\d{2})", low)
    return iso_match.group(1) if iso_match else None


def parse_registration(text: str) -> str:
    low = (text or "").lower()
    if re.search(r"\b(no registration|registration not possible|registration not allowed|geen inschrijving|inschrijving niet mogelijk|geen brp)\b", low):
        return "prohibited"
    if re.search(r"\b(registration possible|registration allowed|brp registration|register(?:ing)? possible|inschrijving mogelijk|inschrijven mogelijk|gemeentelijke inschrijving toegestaan)\b", low):
        return "allowed"
    return "unknown"


def parse_furnishing(text: str) -> str:
    low = (text or "").lower()
    if re.search(r"\b(semi[- ]?furnished|partly furnished|gestoffeerd)\b", low):
        return "semi-furnished"
    if re.search(r"\b(furnished|fully furnished|gemeubileerd|volledig ingericht)\b", low):
        return "furnished"
    if re.search(r"\b(unfurnished|kaal|ongemeubileerd)\b", low):
        return "unfurnished"
    return "unknown"


def _jsonld(soup: BeautifulSoup) -> dict[str, Any]:
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(node.string or node.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = value if isinstance(value, list) else value.get("@graph", [value]) if isinstance(value, dict) else []
        for item in candidates:
            if isinstance(item, dict):
                object_type = item.get("@type")
                types = object_type if isinstance(object_type, list) else [object_type]
                if any(value in {"Apartment", "House", "Residence", "Accommodation", "Product", "RealEstateListing"} for value in types):
                    return item
    return {}


def parse_public_listing_cards(html: str, base_url: str, source_id: str, source_name: str) -> list[Listing]:
    """Parse visible, public search cards; missing fields stay null/unknown."""
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, Listing] = {}
    patterns = ("apartment-for-rent", "studio-for-rent", "room-for-rent", "appartement-te-huur", "studio-te-huur", "kamer-te-huur")
    for anchor in soup.find_all("a", href=True):
        href = urljoin(base_url, anchor.get("href", ""))
        path = urlsplit(href).path.lower()
        iamexpat_listing = source_id == "iamexpat" and re.search(r"/housing/rental-properties/amsterdam/(?:apartment|room|house)/[a-z0-9]{10,}/?$", path)
        if not any(part in path for part in patterns) and not iamexpat_listing:
            continue
        if not iamexpat_listing and len(path.strip("/").split("/")) < 4:
            continue
        url = normalize_url(href)
        if url in found:
            continue
        card = anchor
        for parent in anchor.parents:
            text = " ".join(parent.stripped_strings)
            if 40 <= len(text) <= 1800 and ("€" in text or "per month" in text.lower() or "per maand" in text.lower()):
                card = parent
                break
        card_text = " ".join(card.stripped_strings)
        title = " ".join(anchor.stripped_strings).strip() or card_text[:140]
        if len(title) < 4:
            continue
        rent = parse_money(card_text)
        prop_type, roommates, bedrooms = classify_property(f"{title} {card_text}")
        all_inclusive = bool(re.search(r"\b(?:all[- ]inclusive|all costs included|including (?:all )?utilities and (?:service )?charges)\b", card_text, re.I))
        included = all_inclusive or bool(re.search(r"\b(?:utilities|gas,?\s*(?:water|electricity)|g/w/e)\s+(?:are\s+)?included\b|\bincl(?:usive)?\.?\s*(?:g\s*/\s*w\s*/\s*e|utilities|gas|water|electricity)\b", card_text, re.I))
        fees = None
        fee_match = re.search(r"(?:service charges?|service costs?|servicekosten|voorschot)\s*[:\-]?\s*(?:€|EUR)?\s*([\d.,]+)", card_text, re.I)
        if fee_match:
            fees = parse_money(fee_match.group(1))
        total = rent + (fees or 0) if rent is not None and all_inclusive else None
        cost_status = "CONFIRMED" if total is not None else "BASE_ONLY" if rent is not None else "UNKNOWN"
        if rent is not None and included and fees is not None:
            total = rent + fees
            cost_status = "CONFIRMED"
        if "utilities not included" in card_text.lower() or "excl. utilities" in card_text.lower() or "exclusief g/w/e" in card_text.lower():
            included = False
            total = None
            cost_status = "BASE_ONLY"
        imgs = [urljoin(base_url, img.get("src") or img.get("data-src")) for img in card.find_all("img") if img.get("src") or img.get("data-src")]
        loc_match = re.search(r"([A-Za-zÀ-ÿ' -]+(?:,\s*Amsterdam|\s+Amsterdam))", card_text)
        neighborhood = loc_match.group(1).strip() if loc_match else None
        listing = Listing(
            source_id=source_id,
            source_name=source_name,
            external_id=path.rstrip("/"),
            url=url,
            title=title[:240],
            description=card_text[:3000] or None,
            city="Amsterdam" if "amsterdam" in (path + " " + card_text).lower() else None,
            neighborhood=neighborhood,
            base_rent_eur=rent,
            mandatory_fees_eur=fees,
            monthly_total_eur=total,
            deposit_eur=parse_deposit(card_text),
            cost_status=cost_status,
            utilities_included=True if included else None,
            property_type=prop_type,
            bedrooms=bedrooms,
            bathrooms=parse_bathrooms(card_text),
            surface_sqm=parse_surface_area(card_text),
            housemates=roommates,
            furnishing=parse_furnishing(card_text),
            availability_date=parse_availability(card_text),
            registration=parse_registration(card_text),
            availability_status="unavailable" if re.search(r"\b(?:rented|unavailable|not available|verhuurd|onder optie|under option)\b", card_text, re.I) else "available",
            image_urls=imgs[:8],
            raw_data={"card_text": card_text},
        )
        found[url] = listing
    return list(found.values())


def enrich_detail_html(listing: Listing, html: str, page_url: str) -> Listing:
    soup = BeautifulSoup(html, "html.parser")
    data = _jsonld(soup)
    visible = "\n".join(s.strip() for s in soup.stripped_strings)
    listing.description = visible[:8000] or listing.description
    listing.deposit_eur = parse_deposit(visible) or listing.deposit_eur
    listing.bathrooms = parse_bathrooms(visible) or listing.bathrooms
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "").strip()
        if href.lower().startswith("mailto:") and listing.contact_email is None:
            listing.contact_email = href[7:].split("?", 1)[0].strip() or None
        elif href.lower().startswith("tel:") and listing.contact_phone is None:
            listing.contact_phone = href[4:].split("?", 1)[0].strip() or None
        elif listing.contact_url is None and re.search(r"\b(?:contact|apply|application|viewing|bezichtiging|reageren)\b", anchor.get_text(" ", strip=True), re.I):
            target = normalize_url(urljoin(page_url, href))
            if target != normalize_url(page_url):
                listing.contact_url = target
    if data:
        listing.title = str(data.get("name") or listing.title)[:240]
        offers = data.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        if isinstance(offers, dict):
            listing.base_rent_eur = parse_money(str(offers.get("price") or "")) or listing.base_rent_eur
        addr = data.get("address") or {}
        if isinstance(addr, dict):
            listing.address = ", ".join(str(addr.get(k)) for k in ("streetAddress", "postalCode", "addressLocality") if addr.get(k)) or listing.address
        geo = data.get("geo") or {}
        if isinstance(geo, dict):
            listing.latitude = _float(geo.get("latitude")) or listing.latitude
            listing.longitude = _float(geo.get("longitude")) or listing.longitude
        listing.published_at = data.get("datePosted") or listing.published_at
        listing.updated_at = data.get("dateModified") or listing.updated_at
        area = data.get("floorSize") or {}
        listing.surface_sqm = _float(area.get("value")) if isinstance(area, dict) else listing.surface_sqm
    all_text = f"{listing.title}\n{visible}"
    detected_type, roommates, bedrooms = classify_property(all_text)
    if detected_type != "unknown":
        listing.property_type = detected_type
    if roommates is not None:
        listing.housemates = roommates
    if bedrooms is not None:
        listing.bedrooms = bedrooms
    listing.surface_sqm = parse_surface_area(visible) or listing.surface_sqm
    listing.deposit_eur = parse_deposit(visible) or listing.deposit_eur
    furnishing = parse_furnishing(all_text)
    if furnishing != "unknown":
        listing.furnishing = furnishing
    registration = parse_registration(all_text)
    if registration != "unknown":
        listing.registration = registration
    availability = parse_availability(all_text)
    if availability:
        listing.availability_date = availability
    listing.url = normalize_url(page_url)
    listing.raw_data["detail_text"] = visible[:8000]
    return listing


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
