# ABOUTME: Unit tests for the editorial context analyzer worker.
# ABOUTME: Tests deterministic metric computation in isolation from the LLM.

import pytest
from datetime import datetime, timezone, timedelta

from workers.editorial_context import (
    _compute_edit_metrics,
    _compute_risk_tier,
    _extract_section_name,
    _find_flip_flopped_sections,
)


def _days_ago(n: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=n)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# --- _extract_section_name ---

def test_extract_section_name_standard():
    assert _extract_section_name("/* History */ some edit") == "History"


def test_extract_section_name_whitespace():
    assert _extract_section_name("  /* Lead section */  ") == "Lead section"


def test_extract_section_name_none():
    assert _extract_section_name("Fixed typo") is None


def test_extract_section_name_empty_comment():
    assert _extract_section_name("") is None


# --- _compute_edit_metrics ---

def test_edit_metrics_empty():
    metrics = _compute_edit_metrics([])
    assert metrics["revert_rate_12mo"] == 0.0
    assert metrics["edit_velocity"] == 0
    assert metrics["dominant_editor"] is None


def test_edit_metrics_filters_old_edits():
    edits = [
        {"timestamp": _days_ago(400), "user": "Alice", "comment": "Fixed grammar", "tags": []},
        {"timestamp": _days_ago(10), "user": "Bob", "comment": "Updated stats", "tags": []},
    ]
    metrics = _compute_edit_metrics(edits)
    assert metrics["edit_velocity"] == 1  # only the recent one


def test_edit_metrics_revert_rate():
    edits = [
        {"timestamp": _days_ago(5), "user": "Alice", "comment": "Reverted edits by Bob", "tags": []},
        {"timestamp": _days_ago(6), "user": "Bob", "comment": "Added content", "tags": []},
        {"timestamp": _days_ago(7), "user": "Alice", "comment": "Fixed link", "tags": []},
        {"timestamp": _days_ago(8), "user": "Charlie", "comment": "revert vandalism", "tags": []},
    ]
    metrics = _compute_edit_metrics(edits)
    assert metrics["revert_rate_12mo"] == pytest.approx(0.5)  # 2 of 4


def test_edit_metrics_bot_edits_excluded_from_velocity():
    edits = [
        {"timestamp": _days_ago(5), "user": "CleanupBot", "comment": "bot: fixing links", "tags": []},
        {"timestamp": _days_ago(6), "user": "Alice", "comment": "Updated content", "tags": []},
        {"timestamp": _days_ago(7), "user": "Bob", "comment": "Reverted Alice", "tags": []},
    ]
    metrics = _compute_edit_metrics(edits)
    assert metrics["edit_velocity"] == 1  # bot and revert excluded


def test_edit_metrics_dominant_editor():
    edits = [
        {"timestamp": _days_ago(i), "user": "Alice", "comment": "edit", "tags": []}
        for i in range(1, 9)
    ] + [
        {"timestamp": _days_ago(10), "user": "Bob", "comment": "edit", "tags": []},
        {"timestamp": _days_ago(11), "user": "Charlie", "comment": "edit", "tags": []},
    ]
    metrics = _compute_edit_metrics(edits)
    assert metrics["dominant_editor"] == "Alice"


def test_edit_metrics_no_dominant_editor():
    edits = [
        {"timestamp": _days_ago(i * 3), "user": f"User{i}", "comment": "edit", "tags": []}
        for i in range(1, 7)
    ]
    metrics = _compute_edit_metrics(edits)
    assert metrics["dominant_editor"] is None


# --- _find_flip_flopped_sections ---

def test_flip_flopped_basic():
    edits = [
        {"timestamp": _days_ago(10), "user": "Alice", "comment": "/* History */ added content", "tags": []},
        {"timestamp": _days_ago(20), "user": "Bob", "comment": "/* History */ reverted Alice", "tags": []},
        {"timestamp": _days_ago(30), "user": "Alice", "comment": "/* History */ re-added", "tags": []},
        {"timestamp": _days_ago(40), "user": "Bob", "comment": "/* History */ removed again", "tags": []},
    ]
    sections = _find_flip_flopped_sections(edits)
    assert "History" in sections


def test_flip_flopped_requires_two_users():
    edits = [
        {"timestamp": _days_ago(10), "user": "Alice", "comment": "/* References */ edit1", "tags": []},
        {"timestamp": _days_ago(20), "user": "Alice", "comment": "/* References */ edit2", "tags": []},
        {"timestamp": _days_ago(30), "user": "Alice", "comment": "/* References */ edit3", "tags": []},
        {"timestamp": _days_ago(40), "user": "Alice", "comment": "/* References */ edit4", "tags": []},
    ]
    sections = _find_flip_flopped_sections(edits)
    assert "References" not in sections


def test_flip_flopped_requires_four_edits():
    edits = [
        {"timestamp": _days_ago(10), "user": "Alice", "comment": "/* See also */ edit1", "tags": []},
        {"timestamp": _days_ago(20), "user": "Bob", "comment": "/* See also */ edit2", "tags": []},
        {"timestamp": _days_ago(30), "user": "Alice", "comment": "/* See also */ edit3", "tags": []},
    ]
    sections = _find_flip_flopped_sections(edits)
    assert "See also" not in sections


def test_flip_flopped_only_last_6_months():
    edits = [
        {"timestamp": _days_ago(200), "user": "Alice", "comment": "/* Background */ edit1", "tags": []},
        {"timestamp": _days_ago(210), "user": "Bob", "comment": "/* Background */ edit2", "tags": []},
        {"timestamp": _days_ago(220), "user": "Alice", "comment": "/* Background */ edit3", "tags": []},
        {"timestamp": _days_ago(230), "user": "Bob", "comment": "/* Background */ edit4", "tags": []},
    ]
    sections = _find_flip_flopped_sections(edits)
    assert "Background" not in sections


# --- _compute_risk_tier ---

def test_risk_tier_critical():
    assert _compute_risk_tier(0.35, ["Section A"], [], None, 50) == "CRITICAL"


def test_risk_tier_critical_boundary():
    # exactly at boundary: > 0.30 and flip_flopped
    assert _compute_risk_tier(0.31, ["X"], [], None, 10) == "CRITICAL"


def test_risk_tier_high_flip_flopped():
    assert _compute_risk_tier(0.10, ["Intro"], [], None, 20) == "HIGH"


def test_risk_tier_high_dominant_and_revert():
    assert _compute_risk_tier(0.20, [], [], "Alice", 30) == "HIGH"


def test_risk_tier_high_multiple_disputes():
    assert _compute_risk_tier(0.05, [], [{"topic": "A"}, {"topic": "B"}], None, 10) == "HIGH"


def test_risk_tier_moderate_revert():
    assert _compute_risk_tier(0.20, [], [], None, 30) == "MODERATE"


def test_risk_tier_moderate_one_dispute():
    assert _compute_risk_tier(0.05, [], [{"topic": "A"}], None, 10) == "MODERATE"


def test_risk_tier_moderate_dominant_no_revert():
    assert _compute_risk_tier(0.10, [], [], "Alice", 20) == "MODERATE"


def test_risk_tier_low():
    assert _compute_risk_tier(0.05, [], [], None, 20) == "LOW"
