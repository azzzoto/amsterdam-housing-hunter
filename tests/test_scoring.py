from dataclasses import replace

import pytest

from app.models import Listing
from app.scoring import score_listing


def listing(**changes):
    base = Listing(
        source_id="pararius", source_name="Pararius", url="https://example.test/one", title="Furnished studio",
        city="Amsterdam", neighborhood="Centrum", address="Singel 460, 1017 AW Amsterdam",
        base_rent_eur=850, monthly_total_eur=850, cost_status="CONFIRMED", utilities_included=True,
        property_type="studio", housemates=0, furnishing="furnished", availability_date="immediately",
        registration="allowed", cycling_minutes=15, cycling_status="CONFIRMED",
    )
    return replace(base, **changes)


@pytest.mark.parametrize(("amount", "expected"), [(850, 30), (850.01, 25), (950, 25), (950.01, 15), (1000, 15), (1000.01, 0)])
def test_cost_boundaries(amount, expected, scoring_config):
    scored = score_listing(listing(base_rent_eur=amount, monthly_total_eur=amount), scoring_config)
    assert scored.breakdown["monthly_cost"]["score"] == expected


@pytest.mark.parametrize(("minutes", "expected", "rejected"), [(15, 25, False), (15.01, 22, False), (20, 22, False), (20.01, 17, False), (25, 17, False), (25.01, 0, True)])
def test_cycling_thresholds_and_hard_rejection(minutes, expected, rejected, scoring_config):
    scored = score_listing(listing(cycling_minutes=minutes), scoring_config)
    assert scored.breakdown["cycling_time"]["score"] == expected
    assert bool(scored.hard_exclusions) is rejected


@pytest.mark.parametrize(("kind", "housemates", "expected", "rejected"), [
    ("studio", 0, 20, False), ("independent_apartment", 0, 20, False),
    ("private_room", 0, 17, False), ("private_room", 1, 17, False),
    ("private_room", 2, 0, True), ("shared_bedroom", None, 0, True),
    ("private_room", None, 17, False),
])
def test_accommodation_rules(kind, housemates, expected, rejected, scoring_config):
    scored = score_listing(listing(property_type=kind, housemates=housemates), scoring_config)
    assert scored.breakdown["accommodation_type"]["score"] == expected
    assert bool(scored.hard_exclusions) is rejected
    if kind == "private_room" and housemates is None:
        assert scored.match_status == "PENDING VERIFICATION"


def test_unknown_utilities_use_base_rent_provisionally_and_do_not_reject(scoring_config):
    scored = score_listing(listing(base_rent_eur=900, monthly_total_eur=None, cost_status="BASE_ONLY", utilities_included=None), scoring_config)
    assert scored.breakdown["monthly_cost"]["score"] == 25
    assert scored.breakdown["monthly_cost"]["status"] == "UNCONFIRMED"
    assert not scored.hard_exclusions
    assert "utilities and mandatory monthly fees" in scored.missing_information


def test_estimated_cost_is_not_a_confirmed_hard_rejection(scoring_config):
    scored = score_listing(listing(monthly_total_eur=1200, cost_status="ESTIMATED"), scoring_config)
    assert not scored.hard_exclusions
    assert scored.breakdown["monthly_cost"]["status"] == "ESTIMATED"


def test_approximate_route_above_limit_is_not_hard_rejection(scoring_config):
    scored = score_listing(listing(cycling_minutes=30, cycling_status="APPROXIMATE"), scoring_config)
    assert not scored.hard_exclusions
    assert scored.breakdown["cycling_time"]["status"] == "APPROXIMATE"


def test_unknown_data_is_pending_not_rejected_and_score_is_reproducible(scoring_config):
    item = listing(monthly_total_eur=None, cost_status="BASE_ONLY", housemates=None, cycling_minutes=None, cycling_status="UNVERIFIED", registration="unknown")
    first = score_listing(item, scoring_config).asdict()
    second = score_listing(item, scoring_config).asdict()
    assert first == second
    assert first["match_status"] == "PENDING VERIFICATION"
    assert first["total_score"] <= 100
    assert not first["hard_exclusions"]


def test_date_based_score_uses_recorded_observation_date(scoring_config):
    scored = score_listing(listing(availability_date="2026-11-30", detected_at="2026-11-25T12:00:00+00:00"), scoring_config)
    assert scored.breakdown["availability"]["score"] == 4
    assert scored.breakdown["availability"]["reason"] == "Available within 5 days."


def test_confirmed_hard_exclusions(scoring_config):
    over_budget = score_listing(listing(monthly_total_eur=1001, base_rent_eur=1001), scoring_config)
    unavailable = score_listing(listing(availability_status="rented"), scoring_config)
    assert over_budget.match_status == "REJECTED"
    assert unavailable.match_status == "REJECTED"


def test_base_rent_over_max_is_low_and_stored_without_being_a_confirmed_hard_exclusion(scoring_config):
    scored = score_listing(listing(base_rent_eur=1050, monthly_total_eur=None, cost_status="BASE_ONLY"), scoring_config)
    assert scored.match_status == "LOW MATCH"
    assert not scored.hard_exclusions
    assert any("Base rent alone exceeds" in reason for reason in scored.reasons)


def test_component_maxima_sum_to_100(scoring_config):
    scored = score_listing(listing(), scoring_config)
    assert sum(part["maximum"] for part in scored.breakdown.values()) == 100
    assert scored.total_score == 100
    assert scored.data_confidence == 1


def test_configurable_weights_scale_contributions(scoring_config):
    config = {**scoring_config, "weights": {**scoring_config["weights"], "furnishing": 20, "information_completeness": 0}}
    scored = score_listing(listing(furnishing="semi-furnished"), config)
    assert scored.breakdown["furnishing"]["score"] == 14
    assert scored.breakdown["furnishing"]["maximum"] == 20
