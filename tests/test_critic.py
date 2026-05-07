# ABOUTME: Tests for Critic pure logic — no LLM calls.
# ABOUTME: Tests verdict derivation from dimension results.

from models import DimensionCritique
from workers.critic import _derive_verdict

_CORE = ["citation_coverage", "npov", "structural_completeness"]
_NONCORE = ["citation_quality", "prose_quality", "freshness", "lead_quality"]


def _pass_dim(notes=""):
    return DimensionCritique(verdict="PASS", notes=notes)


def _fail_dim(notes="needs work"):
    return DimensionCritique(verdict="FAIL", notes=notes)


def test_all_pass_returns_pass():
    dims = {d: _pass_dim() for d in _CORE}
    verdict, reason = _derive_verdict(dims)
    assert verdict == "PASS"
    assert reason is None


def test_one_noncore_fail_returns_pass():
    # A single minor non-core failure should not block an incremental edit
    dims = {d: _pass_dim() for d in _CORE}
    dims["prose_quality"] = _fail_dim("slightly awkward")
    verdict, reason = _derive_verdict(dims)
    assert verdict == "PASS"
    assert reason is None


def test_one_core_fail_returns_revise():
    dims = {d: _pass_dim() for d in _NONCORE}
    dims["citation_coverage"] = _fail_dim("missing refs")
    dims["npov"] = _pass_dim()
    dims["structural_completeness"] = _pass_dim()
    verdict, reason = _derive_verdict(dims)
    assert verdict == "REVISE"
    assert reason is None


def test_two_noncore_fails_returns_revise():
    dims = {d: _pass_dim() for d in _CORE}
    dims["prose_quality"] = _fail_dim("awkward")
    dims["freshness"] = _fail_dim("stale stats")
    verdict, reason = _derive_verdict(dims)
    assert verdict == "REVISE"
    assert reason is None


def test_all_core_fails_returns_discard():
    dims = {d: _fail_dim("major issue") for d in _CORE}
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
