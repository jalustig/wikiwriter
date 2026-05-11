# Full Debug Log Tab — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `utils/log.py` logging util that captures all LLM calls, tool calls, and stage events to a human-readable `.log` file; add a live-polling "Log" tab to the Streamlit UI that tails it.

**Architecture:** A single `utils/log.py` module holds a `ContextVar` file sink and exposes atomic write functions. Workers and tools call into it at their LLM/tool call sites. The orchestrator opens the sink at run start and writes stage events. The UI adds a third tab that reads and displays the log file, polling every 1s (live) or 5s (background).

**Tech Stack:** Python `contextvars`, `threading.Lock`, `datetime`, `pathlib`; Streamlit `st.code`, `st.checkbox`, `st.download_button`; existing OpenAI async workers.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| **Create** | `utils/log.py` | Log sink, format, atomic writes |
| **Create** | `tests/test_log.py` | Unit tests for `utils/log.py` |
| **Modify** | `workers/stage_summarizer.py` | Add `log_llm_call` / `log_llm_response` |
| **Modify** | `workers/narrator.py` | Same — streaming variant |
| **Modify** | `workers/assess_article.py` | Same |
| **Modify** | `workers/aggregate_critique.py` | Same |
| **Modify** | `workers/article_grader.py` | Same |
| **Modify** | `workers/claim_extractor.py` | Same |
| **Modify** | `workers/critique_section.py` | Same |
| **Modify** | `workers/draft_writer.py` | Same (two call sites: `run` + `revise`) |
| **Modify** | `workers/edit_planner.py` | Same |
| **Modify** | `workers/editorial_context.py` | Same |
| **Modify** | `workers/output_grader.py` | Same |
| **Modify** | `workers/plan_validate.py` | Same |
| **Modify** | `workers/research_section.py` | Same |
| **Modify** | `workers/source_evaluator.py` | Same |
| **Modify** | `workers/summarize_article.py` | Same |
| **Modify** | `workers/summarize_edit.py` | Same |
| **Modify** | `workers/synthesis_writer.py` | Same |
| **Modify** | `tools/fetcher.py` | Add `log_tool_call` |
| **Modify** | `tools/search.py` | Same |
| **Modify** | `tools/wayback.py` | Same |
| **Modify** | `tools/wikipedia.py` | Same (3 call sites) |
| **Modify** | `tools/diff.py` | Same |
| **Modify** | `orchestrator.py` | Open sink, write stage events |
| **Modify** | `app.py` | Add Log tab, polling logic |

---

## Task 1: Create `utils/log.py` and its tests

**Files:**
- Create: `utils/log.py`
- Create: `tests/test_log.py`

- [ ] **Step 1.1: Write the failing tests**

Create `tests/test_log.py`:

```python
# ABOUTME: Tests for the utils/log.py logging utility.
# ABOUTME: Verifies atomic writes, format, and silent-failure when no sink is set.

import io
import threading
from datetime import timezone

import pytest

import utils.log as log_mod


def _make_sink():
    """Return a StringIO that acts as the log sink."""
    f = io.StringIO()
    f.flush = lambda: None  # StringIO has no real flush
    return f


def setup_function():
    log_mod._sink.set(None)
    log_mod._sink_path.set(None)


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
    log_mod._sink.get().close()
    log_mod._sink.set(None)
    log_mod._sink_path.set(None)
```

- [ ] **Step 1.2: Run tests to verify they fail**

```bash
cd /Users/jason/code/wikiwriter && source .venv/bin/activate && pytest tests/test_log.py -v 2>&1 | head -40
```

Expected: `ModuleNotFoundError` or similar — `utils/log.py` doesn't exist yet.

- [ ] **Step 1.3: Implement `utils/log.py`**

Create `utils/log.py`:

```python
# ABOUTME: Central log utility — writes timestamped human-readable entries to a per-run .log file.
# ABOUTME: All writes are atomic (threading.Lock). Silent no-op when no sink is configured.

import json
import threading
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import IO

_sink: ContextVar[IO | None] = ContextVar("_log_sink", default=None)
_sink_path: ContextVar[str | None] = ContextVar("_log_sink_path", default=None)
_lock = threading.Lock()


def set_log_sink(path: str) -> None:
    """Open path for writing and register it as the active log sink."""
    f = open(path, "w", buffering=1)  # line-buffered
    _sink.set(f)
    _sink_path.set(path)


def get_log_path() -> str | None:
    return _sink_path.get()


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%SZ")


def _write(text: str) -> None:
    f = _sink.get()
    if f is None:
        return
    with _lock:
        f.write(text)
        f.flush()


def _format_block(header: str, body: str | None, suffix: str = "") -> str:
    if body is None:
        return f"[{_ts()}] {header}\n\n"
    indented = "\n".join("    " + line for line in body.splitlines())
    close = f"<<<{' ' + suffix if suffix else ''}"
    return f"[{_ts()}] {header} >>>\n{indented}\n{close}\n\n"


def log_stage_event(stage: str, kind: str, message: str = "") -> None:
    """Write a stage lifecycle line: STAGE_START, STAGE_DONE, THINK, SUMMARY, ERROR."""
    parts = [kind, stage]
    if message:
        parts.append(message)
    _write(f"[{_ts()}] {' '.join(parts)}\n\n")


def log_llm_call(worker: str, model: str, prompt: str) -> None:
    header = f"LLM_CALL worker={worker} model={model}"
    _write(_format_block(header, None))
    _write(_format_block("PROMPT", prompt))


def log_llm_response(worker: str, response_text: str, tokens_in: int, tokens_out: int) -> None:
    suffix = f"tokens_in={tokens_in} tokens_out={tokens_out}"
    header = f"LLM_RESPONSE worker={worker}"
    _write(_format_block(header, response_text, suffix))


def log_tool_call(tool: str, args: dict | None = None) -> None:
    args_str = f" args={json.dumps(args)}" if args else ""
    _write(f"[{_ts()}] TOOL {tool}{args_str}\n\n")
```

- [ ] **Step 1.4: Run tests to verify they pass**

```bash
cd /Users/jason/code/wikiwriter && source .venv/bin/activate && pytest tests/test_log.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 1.5: Run flake8**

```bash
cd /Users/jason/code/wikiwriter && source .venv/bin/activate && flake8 utils/log.py tests/test_log.py --max-line-length=100
```

Expected: no output.

- [ ] **Step 1.6: Commit**

```bash
cd /Users/jason/code/wikiwriter && git add utils/log.py tests/test_log.py && git commit -m "$(cat <<'EOF'
Add utils/log.py: atomic human-readable run log utility

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Instrument workers — non-streaming LLM calls

Instrument the 16 workers that use non-streaming `await client.chat.completions.create(...)`. The pattern is identical for all of them: add `log_llm_call` before the API call and `log_llm_response` after.

**Files:**  
Modify: `workers/stage_summarizer.py`, `workers/assess_article.py`, `workers/aggregate_critique.py`, `workers/article_grader.py`, `workers/claim_extractor.py`, `workers/critique_section.py`, `workers/draft_writer.py` (2 sites), `workers/edit_planner.py`, `workers/editorial_context.py`, `workers/output_grader.py`, `workers/plan_validate.py`, `workers/research_section.py`, `workers/source_evaluator.py`, `workers/summarize_article.py`, `workers/summarize_edit.py`, `workers/synthesis_writer.py`

- [ ] **Step 2.1: Add import to each worker**

In each worker file listed above, add this import alongside the existing `cache` import:

```python
from utils.log import log_llm_call, log_llm_response
```

- [ ] **Step 2.2: Instrument `workers/stage_summarizer.py`**

The current call block (lines 22–30) looks like:
```python
        record_llm_start()
        response = await _client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=150,
            temperature=0.4,
        )
        record_llm_tokens(response.usage)
        return response.choices[0].message.content.strip()
```

Replace with:
```python
        log_llm_call("stage_summarizer", _MODEL, prompt)
        record_llm_start()
        response = await _client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=150,
            temperature=0.4,
        )
        record_llm_tokens(response.usage)
        result = response.choices[0].message.content.strip()
        log_llm_response("stage_summarizer", result,
                         getattr(response.usage, "prompt_tokens", 0),
                         getattr(response.usage, "completion_tokens", 0))
        return result
```

- [ ] **Step 2.3: Instrument `workers/assess_article.py`**

The call block (around lines 169–176):
```python
    record_llm_start()
    response = await _client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    record_llm_tokens(response.usage)

    raw = json.loads(response.choices[0].message.content)
```

Replace with:
```python
    log_llm_call("assess_article", _MODEL, prompt)
    record_llm_start()
    response = await _client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    record_llm_tokens(response.usage)
    raw_text = response.choices[0].message.content
    log_llm_response("assess_article", raw_text,
                     getattr(response.usage, "prompt_tokens", 0),
                     getattr(response.usage, "completion_tokens", 0))
    raw = json.loads(raw_text)
```

- [ ] **Step 2.4: Instrument `workers/aggregate_critique.py`**

Find the block (around lines 63–70):
```python
    record_llm_start()
    response = await _client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    record_llm_tokens(response.usage)
```

Replace with:
```python
    log_llm_call("aggregate_critique", _MODEL, prompt)
    record_llm_start()
    response = await _client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    record_llm_tokens(response.usage)
    log_llm_response("aggregate_critique", response.choices[0].message.content,
                     getattr(response.usage, "prompt_tokens", 0),
                     getattr(response.usage, "completion_tokens", 0))
```

- [ ] **Step 2.5: Instrument remaining workers with the same pattern**

Apply the identical before/after pattern to each remaining worker. For each one, the `worker=` name is the filename without `.py`. Use `getattr(response.usage, "prompt_tokens", 0)` and `getattr(response.usage, "completion_tokens", 0)` for token counts in all cases.

Workers and their `_MODEL` variable names (look these up in each file — they vary):

| Worker file | worker= name | model variable |
|---|---|---|
| `workers/article_grader.py` | `"article_grader"` | `self.model` (instance var) |
| `workers/claim_extractor.py` | `"claim_extractor"` | `_MODEL` |
| `workers/critique_section.py` | `"critique_section"` | `_MODEL` |
| `workers/draft_writer.py` (run) | `"draft_writer"` | `_MODEL` |
| `workers/draft_writer.py` (revise) | `"draft_writer"` | `_MODEL` |
| `workers/edit_planner.py` | `"edit_planner"` | `_MODEL` |
| `workers/editorial_context.py` | `"editorial_context"` | `_MODEL` |
| `workers/output_grader.py` | `"output_grader"` | `_MODEL` |
| `workers/plan_validate.py` | `"plan_validate"` | `_MODEL` |
| `workers/research_section.py` | `"research_section"` | `_MODEL` |
| `workers/source_evaluator.py` | `"source_evaluator"` | `self.model` (instance var) |
| `workers/summarize_article.py` | `"summarize_article"` | `_MODEL` |
| `workers/summarize_edit.py` | `"summarize_edit"` | `_MODEL` |
| `workers/synthesis_writer.py` | `"synthesis_writer"` | `_MODEL` |

For the `log_llm_response` call: capture `response.choices[0].message.content` into a local variable `raw_text` before passing to `json.loads`, and pass `raw_text` to `log_llm_response`. This avoids calling `.content` twice.

- [ ] **Step 2.6: Instrument `workers/narrator.py` (streaming variant)**

The narrator streams chunks. The full assembled response text is available only at the end (in `buf` after the loop drains). Add logging around the stream:

Find the current block:
```python
        record_llm_start()
        stream = await _client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=400,
            temperature=0.85,
            stream=True,
            stream_options={"include_usage": True},
        )

        buf = ""
        usage = None
        async for chunk in stream:
            ...

        remainder = buf.strip()
        if remainder:
            yield remainder

        record_llm_tokens(usage)
```

Replace with:
```python
        log_llm_call("narrator", _MODEL, prompt)
        record_llm_start()
        stream = await _client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=400,
            temperature=0.85,
            stream=True,
            stream_options={"include_usage": True},
        )

        buf = ""
        full_response = ""
        usage = None
        async for chunk in stream:
            if chunk.usage is not None:
                usage = chunk.usage
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta is None:
                continue
            buf += delta
            full_response += delta
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if line:
                    yield line

        remainder = buf.strip()
        if remainder:
            full_response += remainder
            yield remainder

        record_llm_tokens(usage)
        log_llm_response("narrator", full_response,
                         getattr(usage, "prompt_tokens", 0) if usage else 0,
                         getattr(usage, "completion_tokens", 0) if usage else 0)
```

- [ ] **Step 2.7: Run existing tests to verify no regressions**

```bash
cd /Users/jason/code/wikiwriter && source .venv/bin/activate && pytest tests/ -v --ignore=tests/test_log.py -x 2>&1 | tail -30
```

Expected: all previously passing tests still PASS.

- [ ] **Step 2.8: Run flake8 on modified workers**

```bash
cd /Users/jason/code/wikiwriter && source .venv/bin/activate && flake8 workers/ --max-line-length=100
```

Expected: no output.

- [ ] **Step 2.9: Commit**

```bash
cd /Users/jason/code/wikiwriter && git add workers/ && git commit -m "$(cat <<'EOF'
Instrument all workers with log_llm_call / log_llm_response

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Instrument tools with `log_tool_call`

**Files:**  
Modify: `tools/fetcher.py`, `tools/search.py`, `tools/wayback.py`, `tools/wikipedia.py`, `tools/diff.py`

- [ ] **Step 3.1: Add import to each tool file**

In each tool file, add alongside existing imports:
```python
from utils.log import log_tool_call
```

- [ ] **Step 3.2: Instrument `tools/fetcher.py`**

Find (around line 117):
```python
    record_tool_call("fetch")
```

Replace with:
```python
    record_tool_call("fetch")
    log_tool_call("fetch", {"url": url})
```

- [ ] **Step 3.3: Instrument `tools/search.py`**

Find (around line 19):
```python
    record_tool_call("search")
```

Replace with:
```python
    record_tool_call("search")
    log_tool_call("search", {"query": query, "max_results": max_results})
```

- [ ] **Step 3.4: Instrument `tools/wayback.py`**

Find:
```python
    record_tool_call("wayback")
```

Replace with:
```python
    record_tool_call("wayback")
    log_tool_call("wayback", {"url": url})
```

(Read `wayback.py` to confirm the parameter name — it may be `url` or `original_url`.)

- [ ] **Step 3.5: Instrument `tools/wikipedia.py`** (3 sites)

Each `record_tool_call("wikipedia")` call is at a different function. For each one, add `log_tool_call` immediately after with the relevant argument. Read the file to identify the local variable holding the URL or title at each site — pass that as the arg:

```python
    record_tool_call("wikipedia")
    log_tool_call("wikipedia", {"url": url})   # or {"title": title} depending on the function
```

- [ ] **Step 3.6: Instrument `tools/diff.py`**

Find:
```python
    record_tool_call("diff")
```

Replace with:
```python
    record_tool_call("diff")
    log_tool_call("diff")
```

(No meaningful args to log for diff — it operates on in-memory strings.)

- [ ] **Step 3.7: Run tests**

```bash
cd /Users/jason/code/wikiwriter && source .venv/bin/activate && pytest tests/ -v -x 2>&1 | tail -20
```

Expected: all tests PASS.

- [ ] **Step 3.8: Run flake8**

```bash
cd /Users/jason/code/wikiwriter && source .venv/bin/activate && flake8 tools/ --max-line-length=100
```

Expected: no output.

- [ ] **Step 3.9: Commit**

```bash
cd /Users/jason/code/wikiwriter && git add tools/ && git commit -m "$(cat <<'EOF'
Instrument tools with log_tool_call

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Wire up the orchestrator

**Files:**  
Modify: `orchestrator.py`

- [ ] **Step 4.1: Add imports**

At the top of `orchestrator.py`, add:
```python
from utils.log import set_log_sink, log_stage_event, get_log_path
```

- [ ] **Step 4.2: Open the log sink in `run()`**

In `WikiWriterOrchestrator.run()`, find the block that opens the JSONL file:

```python
        with open(f"logs/{ts}_{slug}.jsonl", "w") as log:
```

Before that line, add:
```python
        log_path = f"logs/{ts}_{slug}.log"
        set_log_sink(log_path)

        from datetime import datetime as _dt
        from utils.log import _write, _ts as _log_ts
        _write(
            "=" * 80 + "\n"
            f"WikiWriter Run: {url}\n"
            f"Started: {start.isoformat()}\n"
            + "=" * 80 + "\n\n"
        )
```

Wait — importing private `_write` and `_ts` is not clean. Instead, add a `log_run_header(url, started_at)` function to `utils/log.py`:

```python
def log_run_header(url: str, started_at: str) -> None:
    _write(
        "=" * 80 + "\n"
        f"WikiWriter Run: {url}\n"
        f"Started: {started_at}\n"
        + "=" * 80 + "\n\n"
    )
```

Then in `orchestrator.py`:
```python
from utils.log import set_log_sink, log_stage_event, log_run_header
```

And in `run()`, before the JSONL `with open(...)`:
```python
        log_path = f"logs/{ts}_{slug}.log"
        set_log_sink(log_path)
        log_run_header(url, start.isoformat())
```

- [ ] **Step 4.3: Add `log_run_header` to `utils/log.py`**

Open `utils/log.py` and add:
```python
def log_run_header(url: str, started_at: str) -> None:
    """Write the log file header block."""
    _write(
        "=" * 80 + "\n"
        f"WikiWriter Run: {url}\n"
        f"Started: {started_at}\n"
        + "=" * 80 + "\n\n"
    )
```

- [ ] **Step 4.4: Write stage events from the orchestrator's event loop**

In `run()`, the current event loop looks like:

```python
            async for event in self._run(url):
                elapsed = round((datetime.now(timezone.utc) - start).total_seconds(), 2)
                entry: dict = {
                    "type": "event",
                    "t": elapsed,
                    "stage": event.stage,
                    "status": event.status,
                    "message": event.message,
                    "cache": get_cache_stats(),
                }
                _write(entry)
                yield event
```

Replace with:
```python
            seen_stages: set[str] = set()
            async for event in self._run(url):
                elapsed = round((datetime.now(timezone.utc) - start).total_seconds(), 2)
                entry: dict = {
                    "type": "event",
                    "t": elapsed,
                    "stage": event.stage,
                    "status": event.status,
                    "message": event.message,
                    "cache": get_cache_stats(),
                }
                _write(entry)

                # Write stage events to the human-readable log
                stage_key = f"{event.stage}:{event.status}"
                if event.status == "running" and event.stage not in seen_stages:
                    seen_stages.add(event.stage)
                    log_stage_event(event.stage, "STAGE_START")
                elif event.status == "done" and event.stage in seen_stages:
                    log_stage_event(event.stage, "STAGE_DONE", event.message or "")
                elif event.status == "thinking":
                    log_stage_event(event.stage, "THINK", event.message or "")
                elif event.status == "summary":
                    log_stage_event(event.stage, "SUMMARY", event.message or "")
                elif event.status == "error":
                    log_stage_event(event.stage, "ERROR", event.message or "")

                yield event
```

Note: `_write` in the orchestrator refers to the local JSONL writer lambda, not `utils.log._write`. The naming collision is fine — they are in different scopes.

- [ ] **Step 4.5: Run tests**

```bash
cd /Users/jason/code/wikiwriter && source .venv/bin/activate && pytest tests/ -v -x 2>&1 | tail -20
```

Expected: all tests PASS.

- [ ] **Step 4.6: Run flake8**

```bash
cd /Users/jason/code/wikiwriter && source .venv/bin/activate && flake8 orchestrator.py utils/log.py --max-line-length=100
```

Expected: no output.

- [ ] **Step 4.7: Commit**

```bash
cd /Users/jason/code/wikiwriter && git add orchestrator.py utils/log.py && git commit -m "$(cat <<'EOF'
Wire orchestrator to open log sink and write stage events

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Add the Log tab to the UI

**Files:**  
Modify: `app.py`

- [ ] **Step 5.1: Add `get_log_path` import**

At the top of `app.py`, add:
```python
from utils.log import get_log_path
```

- [ ] **Step 5.2: Add the third tab**

Find the current tab line in `run_and_render()`:
```python
    tab_run, tab_debug = st.tabs(["▶ Run", "🔬 Debug"])
```

Replace with:
```python
    tab_run, tab_debug, tab_log = st.tabs(["▶ Run", "🔬 Debug", "📋 Log"])
```

- [ ] **Step 5.3: Add log tab placeholder and session state**

After the existing `with tab_debug:` block, add:

```python
    with tab_log:
        st.checkbox("🔴 Live tail (1s refresh)", key="log_live")
        log_ph = st.empty()
        log_dl_ph = st.empty()
        log_ph.info("No run started yet. Start a run to see the log.")
```

Also initialise session state for polling before the `_stream()` definition:
```python
    if "log_last_refresh" not in st.session_state:
        st.session_state["log_last_refresh"] = 0.0
```

- [ ] **Step 5.4: Add `_refresh_log()` helper**

Add this function inside `run_and_render()`, alongside the other `_refresh_*` helpers:

```python
    def _refresh_log():
        path = get_log_path()
        if not path:
            return
        try:
            contents = open(path).read()
        except OSError:
            return
        with log_ph.container():
            st.code(contents, language=None)
        st.session_state["log_last_refresh"] = time.monotonic()
```

- [ ] **Step 5.5: Call `_refresh_log()` from `_stream()` with interval logic**

Inside `_stream()`, in each branch of the event handler (after `_refresh_telemetry()` calls), add a polling check. The cleanest place is a single call at the end of each loop iteration. Add this just before `yield event` becomes `async for event in ...`:

After all the existing `if/elif` status blocks inside `async for event in WikiWriterOrchestrator().run(url):`, add:

```python
                # Refresh log tab at appropriate polling interval
                now = time.monotonic()
                interval = 1.0 if st.session_state.get("log_live") else 5.0
                if now - st.session_state.get("log_last_refresh", 0.0) >= interval:
                    _refresh_log()
```

- [ ] **Step 5.6: Show download button after run**

After `asyncio.run(_stream())` completes (at the end of `run_and_render()`), add:

```python
    # Show log download button
    path = get_log_path()
    if path:
        try:
            log_contents = open(path).read()
            with log_dl_ph.container():
                st.download_button(
                    label="⬇ Download .log file",
                    data=log_contents,
                    file_name=path.split("/")[-1],
                    mime="text/plain",
                )
        except OSError:
            pass
    _refresh_log()
```

- [ ] **Step 5.7: Run the UI smoke test**

```bash
cd /Users/jason/code/wikiwriter && source .venv/bin/activate && pytest tests/test_ui_smoke.py -v
```

Expected: PASS.

- [ ] **Step 5.8: Run all tests**

```bash
cd /Users/jason/code/wikiwriter && source .venv/bin/activate && pytest tests/ -v 2>&1 | tail -20
```

Expected: all tests PASS.

- [ ] **Step 5.9: Run flake8**

```bash
cd /Users/jason/code/wikiwriter && source .venv/bin/activate && flake8 app.py --max-line-length=100
```

Expected: no output.

- [ ] **Step 5.10: Commit**

```bash
cd /Users/jason/code/wikiwriter && git add app.py && git commit -m "$(cat <<'EOF'
Add Log tab to UI with live polling and download button

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Add test for `log_run_header`

The `log_run_header` function was added in Task 4 but not covered by the tests written in Task 1 (which was done first). Add the missing test now.

**Files:**  
Modify: `tests/test_log.py`

- [ ] **Step 6.1: Add the test**

Append to `tests/test_log.py`:

```python
def test_log_run_header(tmp_path):
    p = str(tmp_path / "header.log")
    log_mod.set_log_sink(p)
    log_mod.log_run_header("https://en.wikipedia.org/wiki/Test", "2026-05-11T14:00:00Z")
    with open(p) as fh:
        contents = fh.read()
    assert "WikiWriter Run: https://en.wikipedia.org/wiki/Test" in contents
    assert "Started: 2026-05-11T14:00:00Z" in contents
    assert "=" * 80 in contents
    log_mod._sink.get().close()
    log_mod._sink.set(None)
    log_mod._sink_path.set(None)
```

- [ ] **Step 6.2: Run the test**

```bash
cd /Users/jason/code/wikiwriter && source .venv/bin/activate && pytest tests/test_log.py -v
```

Expected: all tests PASS including the new one.

- [ ] **Step 6.3: Commit**

```bash
cd /Users/jason/code/wikiwriter && git add tests/test_log.py && git commit -m "$(cat <<'EOF'
Add test for log_run_header

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| `utils/log.py` with ContextVar sink and Lock | Task 1 |
| `log_llm_call`, `log_llm_response`, `log_tool_call`, `log_stage_event` | Task 1 |
| Indented prompt/response bodies | Task 1 (format verified in tests) |
| Blank line after each entry | Task 1 |
| All workers instrumented | Task 2 |
| Narrator streaming variant | Task 2, Step 2.6 |
| All tools instrumented | Task 3 |
| Orchestrator opens sink, writes header | Task 4 |
| Orchestrator writes STAGE_START/DONE/THINK/SUMMARY/ERROR | Task 4 |
| JSONL unchanged | Task 4 (`.log` written alongside it) |
| Log tab in UI | Task 5 |
| `st.checkbox` for 1s vs 5s polling | Task 5 |
| `st.code` display | Task 5 |
| Download button | Task 5 |
| Silent no-op when no sink | Task 1, test `test_silent_when_no_sink` |
| `get_log_path()` for UI | Task 1, Task 5 |

**Placeholder scan:** No TBDs or "similar to Task N" references found. All code blocks are complete.

**Type consistency:** `log_llm_call(worker: str, model: str, prompt: str)` — used consistently. `log_llm_response(worker: str, response_text: str, tokens_in: int, tokens_out: int)` — used consistently. `log_tool_call(tool: str, args: dict | None)` — used consistently. `log_stage_event(stage: str, kind: str, message: str = "")` — used consistently. `log_run_header(url: str, started_at: str)` — used in Task 4 and tested in Task 6. ✓
