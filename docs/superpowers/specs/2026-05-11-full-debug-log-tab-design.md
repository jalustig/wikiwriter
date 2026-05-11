# Full Debug Log Tab — Design Spec

**Date:** 2026-05-11  
**Status:** Approved

---

## Goal

Add a third "Log" tab to the WikiWriter UI that streams a complete, human-readable debug log of every run — including all narration thoughts, stage events, LLM prompts/responses, and tool calls with arguments. The log is written to a `.log` file on disk and the UI polls that file live.

---

## Architecture

### 1. `utils/log.py` — central logging util

A new module `utils/log.py` is the single place all log writes go through. It exposes:

```python
def set_log_sink(path: str) -> None: ...
    # Opens the file for writing and stores both the path and handle
    # in a module-level ContextVar. Called once by the orchestrator at run start.

def log_llm_call(worker: str, model: str, prompt: str) -> None: ...
    # Writes LLM_CALL + PROMPT block to the log file atomically.

def log_llm_response(worker: str, response_text: str, tokens_in: int, tokens_out: int) -> None: ...
    # Writes LLM_RESPONSE block to the log file atomically.

def log_tool_call(tool: str, args: dict | None = None) -> None: ...
    # Writes TOOL line to the log file atomically.

def log_stage_event(stage: str, kind: str, message: str = "") -> None: ...
    # Writes STAGE_START, STAGE_DONE, THINK, SUMMARY, ERROR lines atomically.

def get_log_path() -> str | None: ...
    # Returns the current log file path (for the UI to poll).
```

All functions fail silently if no sink is set (CLI runs, tests with no log configured).

**Atomicity:** each write acquires a `threading.Lock` before writing and flushing. This is sufficient because asyncio runs on a single thread — the lock guards against any future multi-threaded use.

**Format helper (internal):**

```python
def _format_entry(kind: str, message: str, body: str | None, suffix: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%SZ")
    header = f"[{ts}] {kind}"
    if message:
        header += f" {message}"
    if body is None:
        return header + "\n\n"
    indented = "\n".join("    " + line for line in body.splitlines())
    return f"{header} >>>\n{indented}\n<<<{(' ' + suffix) if suffix else ''}\n\n"
```

### 2. Worker changes

Workers call `log_llm_call()` and `log_llm_response()` instead of (or alongside) `record_llm_start()` / `record_llm_tokens()`. The existing `record_*` functions in `cache.py` are kept for telemetry — log calls are additive, not replacements.

Workers call `log_llm_call(worker=<name>, model=<model>, prompt=<full prompt string>)` immediately before the `await client.chat.completions.create(...)` call, and `log_llm_response(worker=<name>, response_text=<content>, tokens_in=..., tokens_out=...)` after.

Workers affected: `narrator`, `draft_writer`, `assess_article`, `aggregate_critique`, `article_grader`, `claim_extractor`, `critique_section`, `edit_planner`, `editorial_context`, `output_grader`, `plan_validate`, `research_section`, `source_evaluator`, `stage_summarizer`, `summarize_article`, `summarize_edit`, `synthesis_writer`.

Tools call `log_tool_call(tool=<name>, args={...})` with their relevant arguments. Tools affected: `fetcher`, `search`, `wayback`, `wikipedia`.

### 3. Orchestrator changes

The orchestrator's `run()` method:
1. Calls `set_log_sink(f"logs/{ts}_{slug}.log")` before starting `_run()`.
2. Writes a header block to the log at run start.
3. As events are yielded from `_run()`, calls `log_stage_event()` for each:
   - First `running` event for a stage → `STAGE_START`
   - `done` event → `STAGE_DONE`
   - `thinking` event → `THINK`
   - `summary` event → `SUMMARY`
   - `error` event → `ERROR`
4. The existing JSONL file is kept unchanged alongside the `.log` file.

Stage labels in log lines come only from the orchestrator — workers do not know or log their stage.

### 4. UI changes (`app.py`)

**New tab:** `📋 Log` added alongside `▶ Run` and `🔬 Debug`.

**Log file path** stored in `st.session_state["log_path"]` when `set_log_sink()` is called (retrieved via `get_log_path()`).

**Polling:**
- A `st.checkbox("🔴 Live tail (1s refresh)", key="log_live")` inside the Log tab lets the user opt into fast polling.
- The stream loop already re-renders on every orchestrator event; it also refreshes the log display each time.
- Polling interval is tracked via `st.session_state["log_last_refresh"]`. Within the stream loop, if `log_live` is set and >1s has elapsed, or if not set and >5s has elapsed, the log placeholder is refreshed.

**Log display:**
A `st.code(contents, language=None)` block inside a `st.container()` with `height=600`. The log file is read fresh on each refresh. If no run has started, a placeholder message is shown.

**Download button:** After the run completes, a `st.download_button` for the `.log` file appears in the Log tab.

---

## Log file format

```
================================================================================
WikiWriter Run: https://en.wikipedia.org/wiki/Super_Bowl_XXV
Started: 2026-05-11T14:22:58Z
================================================================================

[14:22:58Z] STAGE_START FETCH

[14:22:58Z] TOOL fetch args={"url": "https://en.wikipedia.org/wiki/Super_Bowl_XXV"}

[14:22:59Z] THINK FETCH Fetched 'Super Bowl XXV' — 12 sections, 84 citations

[14:23:00Z] SUMMARY FETCH Fetched 'Super Bowl XXV' (C-class) with 12 sections and 84 citations.

[14:23:00Z] STAGE_DONE FETCH

[14:23:01Z] STAGE_START GATHER

[14:23:01Z] LLM_CALL worker=article_grader model=gpt-5.4

[14:23:01Z] PROMPT >>>
    You are a Wikipedia article grader. Grade the following article...

    Title: Super Bowl XXV
    ...
<<<

[14:23:04Z] LLM_RESPONSE worker=article_grader >>>
    {
      "overall_score": 7.2,
      "letter_grade": "B",
      ...
    }
<<< tokens_in=1834 tokens_out=312

[14:23:04Z] TOOL search args={"query": "Super Bowl XXV sources"}

...
```

Time is shown as `HH:MM:SSZ` (UTC, no date — the date is in the header). Each entry is followed by a blank line for readability.

---

## Testing

- Unit test `_format_entry()`: single-line entries (no body), multi-line entries (indented body, suffix).
- Unit test `log_llm_call()` and `log_tool_call()` write correct content to a StringIO sink.
- Unit test that functions fail silently when no sink is set.
- Smoke test: run the orchestrator with a real log file and verify it contains at least one `STAGE_START`, one `LLM_CALL`, and one `TOOL` entry.
- UI smoke test: verify the Log tab renders without error when no run has started.

---

## Out of scope

- Structured/machine-parseable log format (`.log` is human-readable only; JSONL remains for that).
- Log rotation or size limits.
- Stage labels on worker-level LLM/tool log lines (only the orchestrator writes stage labels).
