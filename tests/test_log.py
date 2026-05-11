# ABOUTME: Tests for the utils/log.py logging utility.
# ABOUTME: Verifies atomic writes, format, and silent-failure when no sink is set.

import io

import cache as cache_mod
import utils.log as log_mod


def _make_sink():
    """Return a StringIO that acts as the log sink."""
    return io.StringIO()


def setup_function():
    log_mod.close_log_sink()
    cache_mod.reset_llm_log()


def teardown_function():
    log_mod.close_log_sink()
    cache_mod.reset_llm_log()


def test_silent_when_no_sink():
    """All log functions must not raise when no sink is configured."""
    log_mod.log_llm_call("worker", "gpt-5.4", "prompt text")
    log_mod.log_llm_response("worker", "response text", 10, 5)
    log_mod.log_tool_call("search", {"query": "test"})
    log_mod.log_stage_event("FETCH", "STAGE_START")


def test_log_stage_event_single_line():
    f = _make_sink()
    log_mod._sink.set(f)
    log_mod.log_stage_event("FETCH", "STAGE_START")
    out = f.getvalue()
    assert "STAGE_START FETCH" in out
    assert out.endswith("\n\n")


def test_log_tool_call_with_args():
    f = _make_sink()
    log_mod._sink.set(f)
    log_mod.log_tool_call("search", {"query": "Super Bowl XXV"})
    out = f.getvalue()
    assert "TOOL search" in out
    assert '"query": "Super Bowl XXV"' in out


def test_log_llm_call_indents_prompt():
    f = _make_sink()
    log_mod._sink.set(f)
    log_mod.log_llm_call("assess_article", "gpt-5.4", "line one\nline two")
    out = f.getvalue()
    assert "LLM_CALL worker=assess_article model=gpt-5.4" in out
    assert "PROMPT >>>" in out
    assert "    line one" in out
    assert "    line two" in out
    assert "\n<<<\n" in out


def test_log_llm_response_includes_tokens():
    f = _make_sink()
    log_mod._sink.set(f)
    log_mod.log_llm_response("assess_article", '{"score": 7}', 100, 50)
    out = f.getvalue()
    assert "LLM_RESPONSE worker=assess_article" in out
    assert '    {"score": 7}' in out
    assert "tokens_in=100 tokens_out=50" in out


def test_get_log_path_returns_none_when_unset():
    assert log_mod.get_log_path() is None


def test_set_log_sink_sets_path(tmp_path):
    p = str(tmp_path / "test.log")
    log_mod.set_log_sink(p)
    assert log_mod.get_log_path() == p
    log_mod.log_stage_event("FETCH", "STAGE_START")
    with open(p) as fh:
        contents = fh.read()
    assert "STAGE_START FETCH" in contents


def test_llm_log_records_call_and_response():
    log_mod.log_llm_call("assess_article", "gpt-4", "tell me about X")
    entries = cache_mod.get_llm_log()
    assert len(entries) == 1
    assert entries[0]["worker"] == "assess_article"
    assert entries[0]["model"] == "gpt-4"
    assert entries[0]["prompt"] == "tell me about X"
    assert entries[0]["response"] is None

    log_mod.log_llm_response("assess_article", '{"result": "ok"}', 50, 20)
    entries = cache_mod.get_llm_log()
    assert len(entries) == 1
    assert entries[0]["response"] == '{"result": "ok"}'
    assert entries[0]["tokens_in"] == 50
    assert entries[0]["tokens_out"] == 20


def test_llm_log_multiple_calls():
    log_mod.log_llm_call("worker_a", "gpt-4", "prompt A")
    log_mod.log_llm_call("worker_b", "gpt-4", "prompt B")
    entries = cache_mod.get_llm_log()
    assert len(entries) == 2
    assert entries[0]["worker"] == "worker_a"
    assert entries[1]["worker"] == "worker_b"


def test_reset_llm_log():
    log_mod.log_llm_call("w", "m", "p")
    cache_mod.reset_llm_log()
    assert cache_mod.get_llm_log() == []


def test_log_run_header(tmp_path):
    p = str(tmp_path / "header.log")
    log_mod.set_log_sink(p)
    log_mod.log_run_header("https://en.wikipedia.org/wiki/Test", "2026-05-11T14:00:00Z")
    with open(p) as fh:
        contents = fh.read()
    assert "WikiWriter Run: https://en.wikipedia.org/wiki/Test" in contents
    assert "Started: 2026-05-11T14:00:00Z" in contents
    assert "=" * 80 in contents
