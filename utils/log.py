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
