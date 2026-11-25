from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utcnow().isoformat(timespec="seconds")


@dataclass(slots=True)
class Listing:
    source_id: str
    source_name: str
    url: str
    title: str
    external_id: str | None = None
    description: str | None = None
    city: str | None = None
    neighborhood: str | None = None
    address: str | None = None
    address_is_approximate: bool = False
    base_rent_eur: float | None = None
    utilities_eur: float | None = None
    mandatory_fees_eur: float | None = None
    monthly_total_eur: float | None = None
    cost_status: str = "UNKNOWN"
    utilities_included: bool | None = None
    deposit_eur: float | None = None
    property_type: str = "unknown"
    bedrooms: int | None = None
    bathrooms: int | None = None
    surface_sqm: float | None = None
    housemates: int | None = None
    maximum_occupancy: int | None = None
    furnishing: str = "unknown"
    availability_date: str | None = None
    registration: str = "unknown"
    minimum_duration: str | None = None
    maximum_duration: str | None = None
    income_requirements: str | None = None
    student_eligibility: str | None = None
    contract_type: str | None = None
    agency_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    contact_url: str | None = None
    application_instructions: str | None = None
    image_urls: list[str] = field(default_factory=list)
    latitude: float | None = None
    longitude: float | None = None
    cycling_minutes: float | None = None
    cycling_distance_m: float | None = None
    cycling_status: str = "UNVERIFIED"
    route_provider: str | None = None
    route_calculated_at: str | None = None
    published_at: str | None = None
    updated_at: str | None = None
    availability_status: str = "available"
    detected_at: str = field(default_factory=iso_now)
    raw_data: dict[str, Any] = field(default_factory=dict)

    def asdict(self) -> dict[str, Any]:
        return asdict(self)
