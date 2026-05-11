# ABOUTME: Central log utility — writes timestamped human-readable entries to a per-run .log file.
# ABOUTME: Uses ContextVar for per-run sink isolation; Lock ensures atomic multi-line entries.

import json
import threading
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import IO

import cache as _cache

_sink: ContextVar[IO | None] = ContextVar("_log_sink", default=None)
_sink_path: ContextVar[str | None] = ContextVar("_log_sink_path", default=None)
_lock = threading.Lock()


def set_log_sink(path: str) -> None:
    """Open path for writing and register it as the active log sink."""
    f = open(path, "w", buffering=1)  # line-buffered
    _sink.set(f)
    _sink_path.set(path)


def close_log_sink() -> None:
    """Close the active log sink and clear the context vars."""
    f = _sink.get()
    if f is not None:
        try:
            f.close()
        except OSError:
            pass
    _sink.set(None)
    _sink_path.set(None)


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


def log_run_header(url: str, started_at: str) -> None:
    """Write the log file header block."""
    _write(
        "=" * 80 + "\n"
        f"WikiWriter Run: {url}\n"
        f"Started: {started_at}\n"
        + "=" * 80 + "\n\n"
    )


def log_stage_event(stage: str, kind: str, message: str = "") -> None:
    """Write a stage lifecycle line: STAGE_START, STAGE_DONE, THINK, SUMMARY, ERROR."""
    parts = [kind, stage]
    if message:
        parts.append(message)
    _write(f"[{_ts()}] {' '.join(parts)}\n\n")


def log_llm_call(worker: str, model: str, prompt: str) -> None:
    header = f"[{_ts()}] LLM_CALL worker={worker} model={model}\n\n"
    prompt_block = _format_block("PROMPT", prompt)
    _write(header + prompt_block)
    _cache.append_llm_call(worker, model, prompt)


def log_llm_response(worker: str, response_text: str, tokens_in: int, tokens_out: int) -> None:
    suffix = f"tokens_in={tokens_in} tokens_out={tokens_out}"
    header = f"LLM_RESPONSE worker={worker}"
    _write(_format_block(header, response_text, suffix))
    _cache.append_llm_response(worker, response_text, tokens_in, tokens_out)


def log_tool_call(tool: str, args: dict | None = None) -> None:
    args_str = f" args={json.dumps(args)}" if args else ""
    _write(f"[{_ts()}] TOOL {tool}{args_str}\n\n")
