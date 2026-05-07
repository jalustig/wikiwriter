# ABOUTME: Tests for Critic pure logic — no LLM calls.
# ABOUTME: Tests verdict derivation from dimension results.

from models import DimensionCritique
from workers.critic import _derive_verdict


def _pass_dim(notes=""):
    return DimensionCritique(verdict="PASS", notes=notes)


def _fail_dim(notes="needs work"):
    return DimensionCritique(verdict="FAIL", notes=notes)


# --- _derive_verdict ---

def test_all_pass_returns_pass():
    dims = {d: _pass_dim() for d in ["citation_coverage", "npov", "prose_quality"]}
    verdict, reason = _derive_verdict(dims)
    assert verdict == "PASS"
    assert reason is None


def test_one_fail_returns_revise():
    dims = {
        "citation_coverage": _pass_dim(),
        "npov": _fail_dim("slightly biased"),
        "prose_quality": _pass_dim(),
    }
    verdict, reason = _derive_verdict(dims)
    assert verdict == "REVISE"
    assert reason is None


def test_multiple_core_fails_returns_discard():
    # If 3+ core dimensions fail, it's not salvageable
    core_dims = ["citation_coverage", "npov", "structural_completeness"]
    dims = {d: _fail_dim("major issue") for d in core_dims}
    dims["prose_quality"] = _pass_dim()
    verdict, reason = _derive_verdict(dims)
    assert verdict == "DISCARD"
    assert reason is not None


def test_two_core_fails_returns_revise():
    dims = {
        "citation_coverage": _fail_dim("missing refs"),
        "npov": _fail_dim("biased"),
        "prose_quality": _pass_dim(),
        "structural_completeness": _pass_dim(),
    }
    verdict, reason = _derive_verdict(dims)
    assert verdict == "REVISE"
    assert reason is None


def test_empty_dims_returns_pass():
    verdict, reason = _derive_verdict({})
    assert verdict == "PASS"
    assert reason is None
