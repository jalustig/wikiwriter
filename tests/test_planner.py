# ABOUTME: Unit tests for the planner worker hard rules.
# ABOUTME: Tests deterministic pre-LLM filtering logic in isolation.

from models import WikiArticle, EditorialRiskProfile
from workers.planner import _apply_hard_rules


def _make_article(sections=None):
    sections = sections or ["Lead", "History", "References"]
    return WikiArticle(
        title="Test Article",
        url="https://en.wikipedia.org/wiki/Test_Article",
        wikitext="",
        sections=sections,
        section_texts={s: f"Text for {s}" for s in sections},
        citations=[],
        assessment_class=None,
    )


def _make_risk(risk_tier="LOW", flip_flopped_sections=None):
    return EditorialRiskProfile(
        risk_tier=risk_tier,
        revert_rate_12mo=0.05,
        edit_velocity=10,
        dominant_editor=None,
        flip_flopped_sections=flip_flopped_sections or [],
        active_disputes=[],
        resolved_disputes=[],
        editor_imposed_norms=[],
        wikiproject_affiliations=[],
        risk_narrative="Stable article.",
    )


# --- Hard rule: CRITICAL risk tier ---

def test_critical_risk_returns_empty_sections_to_edit():
    article = _make_article(["Lead", "History", "See also"])
    risk = _make_risk(risk_tier="CRITICAL")

    excluded, reasons, remaining = _apply_hard_rules(article, risk)

    assert remaining == []
    assert set(excluded) == {"Lead", "History", "See also"}


def test_critical_risk_exclusion_reason():
    article = _make_article(["Lead", "History"])
    risk = _make_risk(risk_tier="CRITICAL")

    excluded, reasons, remaining = _apply_hard_rules(article, risk)

    for section in article.sections:
        assert section in reasons
        assert "CRITICAL" in reasons[section]


# --- Hard rule: flip-flopped sections ---

def test_flip_flopped_section_excluded():
    article = _make_article(["Lead", "History", "References"])
    risk = _make_risk(flip_flopped_sections=["History"])

    excluded, reasons, remaining = _apply_hard_rules(article, risk)

    assert "History" in excluded
    assert "History" not in remaining


def test_flip_flopped_exclusion_reason():
    article = _make_article(["Lead", "History"])
    risk = _make_risk(flip_flopped_sections=["History"])

    excluded, reasons, remaining = _apply_hard_rules(article, risk)

    assert "History" in reasons
    assert "flip-flop" in reasons["History"].lower()


def test_non_flip_flopped_not_auto_excluded():
    article = _make_article(["Lead", "History", "References"])
    risk = _make_risk(flip_flopped_sections=["History"])

    excluded, reasons, remaining = _apply_hard_rules(article, risk)

    assert "Lead" in remaining
    assert "References" in remaining


# --- Combined hard rules ---

def test_critical_risk_overrides_everything():
    """CRITICAL risk tier excludes all sections, even non-flip-flopped ones."""
    article = _make_article(["Lead", "History"])
    risk = _make_risk(risk_tier="CRITICAL", flip_flopped_sections=["History"])

    excluded, reasons, remaining = _apply_hard_rules(article, risk)

    assert remaining == []
    assert len(excluded) == 2


def test_multiple_flip_flopped_sections():
    article = _make_article(["Lead", "History", "Background", "References"])
    risk = _make_risk(flip_flopped_sections=["History", "Background"])

    excluded, reasons, remaining = _apply_hard_rules(article, risk)

    assert "History" in excluded
    assert "Background" in excluded
    assert "Lead" in remaining
    assert "References" in remaining
