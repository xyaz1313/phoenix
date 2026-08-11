from datetime import datetime, timezone, timedelta
from phoenix_v7.memory.belief import (
    tier_for_confidence, is_archived, decayed_confidence, reinforce,
    CONFIDENCE_FACT_MIN, CONFIDENCE_BELIEF_MIN, CONFIDENCE_ARCHIVE_THRESHOLD,
    CONFIDENCE_FLOOR, REINFORCE_INCREMENT,
)


def test_tier_for_confidence_fact_boundary():
    assert tier_for_confidence(CONFIDENCE_FACT_MIN) == "fact"
    assert tier_for_confidence(CONFIDENCE_FACT_MIN - 0.01) != "fact"


def test_tier_for_confidence_belief_boundary():
    assert tier_for_confidence(CONFIDENCE_BELIEF_MIN) == "belief"
    assert tier_for_confidence(CONFIDENCE_BELIEF_MIN - 0.01) == "observation"


def test_tier_for_confidence_observation_low_value():
    assert tier_for_confidence(0.1) == "observation"


def test_is_archived_true_below_threshold():
    assert is_archived(CONFIDENCE_ARCHIVE_THRESHOLD - 0.01) is True


def test_is_archived_false_at_threshold():
    assert is_archived(CONFIDENCE_ARCHIVE_THRESHOLD) is False


def test_decayed_confidence_no_time_elapsed_unchanged():
    now = datetime(2026, 8, 11, tzinfo=timezone.utc)
    assert decayed_confidence(0.5, now, now) == 0.5


def test_decayed_confidence_decreases_after_days():
    now = datetime(2026, 8, 11, tzinfo=timezone.utc)
    last = now - timedelta(days=5)
    result = decayed_confidence(0.5, last, now)
    assert result < 0.5


def test_decayed_confidence_never_below_floor():
    now = datetime(2026, 8, 11, tzinfo=timezone.utc)
    last = now - timedelta(days=3650)
    result = decayed_confidence(0.9, last, now)
    assert result >= CONFIDENCE_FLOOR


def test_reinforce_increases_confidence():
    result = reinforce(0.5)
    assert result == 0.5 + REINFORCE_INCREMENT


def test_reinforce_caps_at_one():
    result = reinforce(0.95)
    assert result == 1.0
