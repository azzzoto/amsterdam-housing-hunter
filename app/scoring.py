from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models import Listing


@dataclass(frozen=True, slots=True)
class ScoreResult:
    total_score: int
    category: str
    match_status: str
    data_confidence: float
    breakdown: dict[str, dict[str, Any]]
    reasons: list[str]
    missing_information: list[str]
    hard_exclusions: list[str]

    def asdict(self) -> dict[str, Any]:
        return {
            "total_score": self.total_score,
            "category": self.category,
            "match_status": self.match_status,
            "data_confidence": self.data_confidence,
            "breakdown": self.breakdown,
            "reasons": self.reasons,
            "missing_information": self.missing_information,
            "hard_exclusions": self.hard_exclusions,
        }


def score_listing(
    listing: Listing,
    config: dict,
    preferences: dict | None = None,
) -> ScoreResult:
    """Deterministic suitability score. No model output participates in scoring."""
    preferences = preferences or {}
    budget_cfg = config.get("budget", {})
    cycling_cfg = config.get("cycling", {})
    weights = config.get("weights", config.get("points", {}))
    contribution = config.get("contributions", {})
    categories = config.get("categories", {})
    ideal = float(preferences.get("ideal_monthly", budget_cfg.get("ideal_eur", 950)))
    maximum = float(preferences.get("max_monthly", budget_cfg.get("maximum_eur", 1000)))
    max_cycling = float(preferences.get("max_cycling_minutes", cycling_cfg.get("maximum_minutes", 25)))

    breakdown: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []
    missing: list[str] = []
    exclusions: list[str] = []
    base_rent_over_budget = listing.base_rent_eur is not None and listing.base_rent_eur > maximum and listing.cost_status.upper() != "CONFIRMED"

    if (listing.availability_status or "").lower() in {"rented", "unavailable", "not_available", "already_rented", "removed"}:
        exclusions.append("Listing is explicitly unavailable or already rented.")

    # Price: only confirmed all-in totals can trigger the hard maximum exclusion.
    amount = listing.monthly_total_eur
    price_status = listing.cost_status.upper()
    if amount is None and listing.base_rent_eur is not None:
        amount = listing.base_rent_eur
        price_status = "BASE_ONLY"
    if amount is None:
        price_score, price_state = 0, "UNKNOWN"
        price_reason = "Total monthly cost and base rent are unavailable."
        missing.append("monthly rent and utilities")
    else:
        if amount <= float(budget_cfg.get("full_points_through_eur", 850)):
            price_score = round(weights.get("monthly_cost", 30) * contribution.get("cost_full", 1.0))
        elif amount <= ideal:
            price_score = round(weights.get("monthly_cost", 30) * contribution.get("cost_ideal", 25 / 30))
        elif amount <= maximum:
            price_score = round(weights.get("monthly_cost", 30) * contribution.get("cost_maximum", 15 / 30))
        else:
            price_score = 0
        if price_status == "CONFIRMED":
            price_state = "CONFIRMED"
            price_reason = f"€{amount:,.0f}/month all-inclusive."
            reasons.append(f"Confirmed monthly cost is within the €{maximum:,.0f} maximum." if amount <= maximum else "")
            if amount > maximum:
                exclusions.append(f"Confirmed all-inclusive monthly cost €{amount:,.0f} exceeds €{maximum:,.0f}.")
        elif price_status == "ESTIMATED":
            price_state = "ESTIMATED"
            price_reason = f"Estimated total €{amount:,.0f}/month; estimate is not confirmed."
            missing.append("confirmed all-inclusive monthly cost")
        elif listing.base_rent_eur is not None:
            price_state = "UNCONFIRMED"
            price_reason = f"€{listing.base_rent_eur:,.0f}/month base rent; utilities/fees are unknown."
            missing.append("utilities and mandatory monthly fees")
        else:
            price_state = "UNKNOWN"
            price_reason = "Monthly cost is unavailable."
            missing.append("monthly rent and utilities")
    if listing.base_rent_eur is not None and price_status != "CONFIRMED":
        reasons.append("Base rent is visible, but all-in budget fit needs verification.")
    if base_rent_over_budget:
        reasons.append(f"Base rent alone exceeds €{maximum:,.0f}; all-in cost cannot fit the configured budget.")
    breakdown["monthly_cost"] = {
        "score": price_score,
        "maximum": int(weights.get("monthly_cost", 30)),
        "reason": price_reason,
        "status": price_state,
        "base_rent_eur": listing.base_rent_eur,
        "utilities_eur": listing.utilities_eur,
        "mandatory_fees_eur": listing.mandatory_fees_eur,
        "total_monthly_cost_eur": listing.monthly_total_eur,
        "ideal_budget_eur": ideal,
        "maximum_budget_eur": maximum,
    }

    # Actual routed time only; approximate routes score but cannot cause a hard rejection.
    if listing.cycling_minutes is None or listing.cycling_status == "UNVERIFIED":
        route_score, route_state = 0, "UNVERIFIED"
        route_reason = "No reliable bicycle route has been calculated."
        missing.append("cycling travel time")
    else:
        minutes = float(listing.cycling_minutes)
        if minutes <= float(cycling_cfg.get("full_points_through_minutes", 15)):
            route_score = round(weights.get("cycling_time", 25) * contribution.get("cycling_full", 1.0))
        elif minutes <= float(cycling_cfg.get("middle_points_through_minutes", 20)):
            route_score = round(weights.get("cycling_time", 25) * contribution.get("cycling_16_20", 22 / 25))
        elif minutes <= max_cycling:
            route_score = round(weights.get("cycling_time", 25) * contribution.get("cycling_21_25", 17 / 25))
        else:
            route_score = 0
        route_state = "APPROXIMATE" if listing.cycling_status == "APPROXIMATE" else "CONFIRMED"
        route_reason = f"{minutes:.0f} minutes by bicycle" + (" (approximate location)." if route_state == "APPROXIMATE" else ".")
        if route_state == "CONFIRMED" and minutes > max_cycling:
            exclusions.append(f"Reliable cycling route is {minutes:.0f} minutes, over the {max_cycling:.0f}-minute limit.")
        elif minutes <= max_cycling:
            reasons.append("Cycling route is within the configured travel-time limit.")
    breakdown["cycling_time"] = {
        "score": route_score,
        "maximum": int(weights.get("cycling_time", 25)),
        "reason": route_reason,
        "status": route_state,
        "minutes": listing.cycling_minutes,
        "distance_m": listing.cycling_distance_m,
        "provider": listing.route_provider,
        "calculated_at": listing.route_calculated_at,
    }

    kind = (listing.property_type or "unknown").lower()
    if kind in {"studio", "independent_apartment"}:
        type_score, type_state = round(weights.get("accommodation_type", 20) * contribution.get("studio_or_apartment", 1.0)), "CONFIRMED"
        type_reason = "Independent studio/apartment."
        reasons.append("Independent accommodation.")
    elif kind == "private_room":
        if listing.housemates is None:
            type_score, type_state = round(weights.get("accommodation_type", 20) * contribution.get("private_room", 17 / 20)), "UNVERIFIED"
            type_reason = "Private room; housemate count is unknown."
            missing.append("number of other housemates")
        elif listing.housemates <= 1:
            type_score, type_state = round(weights.get("accommodation_type", 20) * contribution.get("private_room", 17 / 20)), "CONFIRMED"
            type_reason = f"Private room with {listing.housemates} other housemate(s)."
            reasons.append("Private room meets the maximum-one-housemate requirement.")
        else:
            type_score, type_state = 0, "CONFIRMED"
            type_reason = f"Private room with {listing.housemates} other housemates."
            exclusions.append("More than one other housemate is stated.")
    elif kind == "shared_bedroom":
        type_score, type_state = 0, "CONFIRMED"
        type_reason = "Shared bedroom."
        exclusions.append("A shared bedroom does not meet the private-room requirement.")
    else:
        type_score, type_state = 0, "UNVERIFIED"
        type_reason = "Accommodation type could not be established."
        missing.append("accommodation type")
    breakdown["accommodation_type"] = {
        "score": type_score,
        "maximum": int(weights.get("accommodation_type", 20)),
        "reason": type_reason,
        "status": type_state,
        "property_type": kind,
        "housemates": listing.housemates,
    }

    furniture = (listing.furnishing or "unknown").lower()
    furniture_factors = {
        "furnished": contribution.get("furnished", 1.0),
        "semi-furnished": contribution.get("semi_furnished", 0.7),
        "unfurnished": contribution.get("unfurnished", 0.4),
        "unknown": contribution.get("unknown_furnishing", 0.4),
    }
    furniture_score = round(weights.get("furnishing", 10) * furniture_factors.get(furniture, 0.4))
    furniture_state = "CONFIRMED" if furniture != "unknown" else "UNVERIFIED"
    furniture_reason = {
        "furnished": "Furnished.", "semi-furnished": "Semi-furnished.",
        "unfurnished": "Unfurnished.", "unknown": f"Furnishing status unknown; provisional {furniture_score} points.",
    }.get(furniture, "Furnishing status unknown; provisional 4 points.")
    if furniture == "unknown":
        missing.append("furnishing status")
    breakdown["furnishing"] = {"score": furniture_score, "maximum": int(weights.get("furnishing", 10)), "reason": furniture_reason, "status": furniture_state}

    availability = listing.availability_date
    if availability == "immediately":
        availability_score, availability_reason, availability_state = round(weights.get("availability", 5) * contribution.get("available_immediately", 1.0)), "Available immediately.", "CONFIRMED"
        reasons.append("Available immediately.")
    elif availability:
        from datetime import date, datetime
        try:
            reference_day = datetime.fromisoformat(listing.detected_at).date()
            days = (date.fromisoformat(availability) - reference_day).days
        except ValueError:
            try:
                days = (date.fromisoformat(availability) - date.today()).days
            except ValueError:
                days = 9999
        if days <= 7:
            availability_score, availability_reason = round(weights.get("availability", 5) * contribution.get("available_within_7_days", 0.8)), f"Available within {max(0, days)} days."
        elif days <= 30:
            availability_score, availability_reason = round(weights.get("availability", 5) * contribution.get("available_within_30_days", 0.4)), f"Available in {days} days."
        else:
            availability_score, availability_reason = 0, f"Available in {days} days."
        availability_state = "CONFIRMED"
    else:
        availability_score, availability_reason, availability_state = 0, "Availability date unknown.", "UNVERIFIED"
        missing.append("availability date")
    breakdown["availability"] = {"score": availability_score, "maximum": int(weights.get("availability", 5)), "reason": availability_reason, "status": availability_state}

    registration = (listing.registration or "unknown").lower()
    reg_score = round(weights.get("registration", 5) * (contribution.get("registration_allowed", 1.0) if registration == "allowed" else contribution.get("registration_unknown", 0.4) if registration == "unknown" else 0.0))
    reg_state = "CONFIRMED" if registration in {"allowed", "prohibited"} else "UNVERIFIED"
    reg_reason = {"allowed": "BRP registration explicitly allowed.", "prohibited": "BRP registration explicitly prohibited.", "unknown": f"BRP status unknown; provisional {reg_score} points."}.get(registration, f"BRP status unknown; provisional {reg_score} points.")
    if registration == "allowed":
        reasons.append("BRP registration is explicitly allowed.")
    elif registration == "unknown":
        missing.append("BRP registration permission")
    breakdown["registration"] = {"score": reg_score, "maximum": int(weights.get("registration", 5)), "reason": reg_reason, "status": reg_state}

    complete = [
        listing.base_rent_eur is not None and price_state == "CONFIRMED",
        bool(listing.address or listing.neighborhood or listing.city),
        kind != "unknown",
        kind != "private_room" or listing.housemates is not None,
        bool(listing.availability_date),
    ]
    completeness_weight = int(weights.get("information_completeness", 5))
    completeness_score = round(completeness_weight * sum(bool(item) for item in complete) / len(complete))
    completeness_state = "CONFIRMED" if all(bool(item) for item in complete) else "PARTIAL"
    breakdown["information_completeness"] = {
        "score": completeness_score,
        "maximum": completeness_weight,
        "reason": f"{sum(bool(item) for item in complete)}/5 required information dimensions documented.",
        "status": completeness_state,
        "dimensions": {"rent_and_utilities": bool(complete[0]), "location": bool(complete[1]), "accommodation_type": bool(complete[2]), "housemates": bool(complete[3]), "availability": bool(complete[4])},
    }

    raw_total = price_score + route_score + type_score + furniture_score + availability_score + reg_score + completeness_score
    total_weight = sum(int(value) for value in weights.values())
    total = min(100, max(0, int(round(raw_total * 100 / total_weight)))) if total_weight else 0
    if total >= int(categories.get("excellent", 90)):
        category = "EXCELLENT MATCH"
    elif total >= int(categories.get("very_good", 80)):
        category = "VERY GOOD MATCH"
    elif total >= int(categories.get("good", 70)):
        category = "GOOD MATCH"
    elif total >= int(categories.get("possible", 60)):
        category = "POSSIBLE MATCH"
    else:
        category = "LOW MATCH"

    confidence_fields = [
        listing.base_rent_eur is not None,
        price_state == "CONFIRMED",
        bool(listing.address or listing.neighborhood),
        kind != "unknown",
        kind != "private_room" or listing.housemates is not None,
        listing.cycling_status == "CONFIRMED",
        bool(listing.availability_date),
        registration != "unknown",
    ]
    confidence = round(sum(confidence_fields) / len(confidence_fields), 2)
    if exclusions:
        match_status = "REJECTED"
    elif base_rent_over_budget:
        match_status = "LOW MATCH"
    elif missing or confidence < 0.75:
        match_status = "PENDING VERIFICATION"
    elif total >= 60:
        match_status = "HIGH MATCH" if total >= 80 else "POSSIBLE MATCH"
    else:
        match_status = "LOW MATCH"
    reasons = [reason for reason in reasons if reason]
    return ScoreResult(total, category, match_status, confidence, breakdown, reasons, sorted(set(missing)), exclusions)
