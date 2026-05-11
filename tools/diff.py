# ABOUTME: Section diff tool — sentence-level Heckel alignment with citation awareness.
# ABOUTME: Outputs HTML (for the UI) or plaintext (for the CLI); logs telemetry via record_tool_call.

import html as _html
import re
from typing import Literal

from cache import record_tool_call
from utils.log import log_tool_call
from utils.diff import (
    Token, heckel_diff_ops, word_diff_ops,
    section_diff_html, section_diff_text,
    _HAS_MDIFF, _HAS_SPACY, _THEME_STYLE,
)


# ── Shared rendering helpers ───────────────────────────────────────────────────

_SENT_BASE = (
    "margin-bottom:6px;font-size:14px;line-height:1.7;"
    "padding:8px 14px;border-radius:0 4px 4px 0"
)


def _sent_div(body: str, bg: str, border: str, extra: str = "") -> str:
    style = f"{_SENT_BASE};background:{bg};border-left:4px solid {border};{extra}"
    return f"<div style='{style}'>{body}</div>"


def _word_diff_inline(old_text: str, new_text: str) -> str:
    parts = []
    for tag, text in word_diff_ops(old_text, new_text):
        escaped = _html.escape(text)
        if tag == "equal":
            parts.append(escaped)
        elif tag == "delete":
            parts.append(
                f"<span style='background:var(--word-del-bg);text-decoration:line-through;"
                f"border-radius:2px;padding:0 2px'>{escaped}</span>"
            )
        elif tag == "insert":
            parts.append(
                f"<span style='background:var(--word-ins-bg);border-radius:2px;"
                f"padding:0 2px'>{escaped}</span>"
            )
    return " ".join(parts)


# ── Citation number assignment ─────────────────────────────────────────────────

def _assign_citation_numbers(ops: list[tuple]) -> dict[int, int]:
    nums: dict[int, int] = {}
    counter = 0
    for i, entry in enumerate(ops):
        tag, _, new_tok = entry
        if new_tok and new_tok.kind == "citation" and tag in ("equal", "replace", "insert", "moved"):
            counter += 1
            nums[i] = counter
    for i, entry in enumerate(ops):
        tag, old_tok, _ = entry
        if old_tok and old_tok.kind == "citation" and tag == "delete":
            counter += 1
            nums[i] = counter
    return nums


# ── HTML rendering (Mode A: superscript citations) ─────────────────────────────

_CITE_COLORS = {
    "equal":   ("#94a3b8", "color:#94a3b8"),
    "replace": ("#f59e0b", "color:#b45309"),
    "insert":  ("#22c55e", "color:#15803d"),
    "delete":  ("#ef4444", "color:#991b1b"),
    "move":    ("#3b82f6", "color:#1d4ed8"),
    "moved":   ("#3b82f6", "color:#1d4ed8"),
}


def _sup_html(num: int, op: str) -> str:
    border_color, text_color = _CITE_COLORS.get(op, ("#94a3b8", "color:#94a3b8"))
    strike = "text-decoration:line-through;" if op == "delete" else ""
    style = (
        f"font-size:0.7em;vertical-align:super;font-weight:600;"
        f"border:1px solid {border_color};border-radius:3px;"
        f"padding:0 3px;margin-left:2px;{text_color};{strike}"
    )
    return f"<span style='{style}'>[{num}]</span>"


def _footnote_html(num: int, op: str, text: str, paired_text: str | None = None) -> str:
    border_color, text_color = _CITE_COLORS.get(op, ("#94a3b8", "color:#94a3b8"))
    if op == "replace" and paired_text:
        body = _word_diff_inline(paired_text, text)
    else:
        body = _html.escape(text)
    strike = "text-decoration:line-through;opacity:.7;" if op == "delete" else ""
    return (
        f"<div style='margin-bottom:4px;font-size:12px;font-family:monospace;"
        f"border-left:3px solid {border_color};padding:3px 8px;{strike}"
        f"color:var(--diff-fg-equal)'>"
        f"<span style='font-weight:700;{text_color}'>[{num}]</span> {body}</div>"
    )


def _render_html(ops: list[tuple]) -> str:
    cite_nums = _assign_citation_numbers(ops)
    blocks: list[str] = []
    footnotes: list[str] = []
    last_para = -1
    pending_inline: list[str] = []

    def flush():
        nonlocal pending_inline
        if pending_inline:
            blocks.append(
                "<div style='margin-bottom:6px;font-size:14px;line-height:1.7;"
                "padding:8px 14px;background:var(--diff-bg-equal);color:var(--diff-fg-equal)'>"
                + "".join(pending_inline) + "</div>"
            )
            pending_inline = []

    def maybe_para(np: int):
        nonlocal last_para
        if np >= 0 and np != last_para:
            flush()
            blocks.append(
                f"<div style='font-size:11px;color:var(--diff-meta);margin:10px 0 4px;"
                f"text-transform:uppercase;letter-spacing:.06em'>"
                f"¶ paragraph {np + 1}</div>"
            )
            last_para = np

    for i, entry in enumerate(ops):
        tag, old_tok, new_tok = entry
        display: Token = new_tok if new_tok else old_tok

        if display.kind == "sentence":
            maybe_para(display.para_idx)
            if tag == "equal":
                pending_inline.append(_html.escape(display.text) + " ")
            elif tag == "replace":
                flush()
                blocks.append(_sent_div(_word_diff_inline(old_tok.text, new_tok.text),
                                        "var(--diff-bg-replace)", "var(--diff-meta)"))
            elif tag == "insert":
                flush()
                blocks.append(_sent_div(
                    f"<span style='color:var(--diff-fg-insert)'>{_html.escape(display.text)}</span>",
                    "var(--diff-bg-insert)", "#66bb6a"))
            elif tag == "delete":
                flush()
                blocks.append(_sent_div(
                    f"<span style='color:var(--diff-fg-delete)'>{_html.escape(display.text)}</span>",
                    "var(--diff-bg-delete)", "#e57373",
                    "text-decoration:line-through"))
            elif tag in ("move", "moved"):
                flush()
                label = (
                    "<span style='font-size:11px;font-weight:600;color:var(--diff-fg-move);"
                    "text-transform:uppercase;letter-spacing:.05em'>↕ moved</span> "
                )
                blocks.append(_sent_div(
                    label + f"<span style='color:var(--diff-fg-move)'>{_html.escape(display.text)}</span>",
                    "var(--diff-bg-move)", "#3b82f6"))
        else:  # citation
            num = cite_nums.get(i, "?")
            flush()
            sup = _sup_html(num, tag)
            if blocks and blocks[-1].endswith("</div>"):
                blocks[-1] = blocks[-1][:-6] + sup + "</div>"
            else:
                blocks.append(f"<span>{sup}</span>")

            if tag == "replace":
                footnotes.append(_footnote_html(num, "replace", new_tok.text, old_tok.text))
            elif tag == "delete":
                footnotes.append(_footnote_html(num, "delete", old_tok.text))
            elif tag == "insert":
                footnotes.append(_footnote_html(num, "insert", new_tok.text))
            elif tag == "equal":
                footnotes.append(_footnote_html(num, "equal", display.text))
            elif tag in ("move", "moved"):
                footnotes.append(_footnote_html(num, "moved", display.text))

    flush()
    inner = "\n".join(blocks)
    if footnotes:
        inner += (
            "<div style='margin-top:20px;border-top:1px solid var(--diff-border);padding-top:12px'>"
            "<div style='font-size:11px;font-weight:700;color:var(--diff-cite-label);"
            "text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px'>Citations</div>"
            + "\n".join(footnotes)
            + "</div>"
        )
    return _THEME_STYLE + f"<div class='diff-root'>{inner}</div>"


# ── Plaintext rendering ────────────────────────────────────────────────────────

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")
_RED = "\033[31m"
_GREEN = "\033[32m"
_AMBER = "\033[33m"
_BLUE = "\033[34m"
_GRAY = "\033[2m"
_STRIKE = "\033[9m"
_RESET = "\033[0m"


def _word_diff_sides(old_text: str, new_text: str, color: bool) -> tuple[str, str]:
    """Return (old_marked, new_marked) with deletions on old side, insertions on new side."""
    old_parts, new_parts = [], []
    for tag, text in word_diff_ops(old_text, new_text):
        if tag == "equal":
            old_parts.append(text)
            new_parts.append(text)
        elif tag == "delete":
            old_parts.append(f"{_RED}{_STRIKE}[-{text}-]{_RESET}" if color else f"[-{text}-]")
        elif tag == "insert":
            new_parts.append(f"{_GREEN}{{+{text}+}}{_RESET}" if color else "{+" + text + "+}")
    return " ".join(old_parts), " ".join(new_parts)


def _render_text(ops: list[tuple], width: int = 80, color: bool = False) -> list[str]:
    cite_nums = _assign_citation_numbers(ops)
    lines: list[str] = []
    footnotes: list[str] = []

    def _wrap(text: str, prefix: str) -> list[str]:
        indent = " " * len(prefix)
        out, current = [], prefix
        for word in _ANSI_RE.sub("", text).split():
            if current != prefix and len(current) + 1 + len(word) > width:
                out.append(current)
                current = indent + word
            else:
                current += ("" if current == prefix else " ") + word
        if current.strip():
            out.append(current)
        return out

    for i, entry in enumerate(ops):
        tag, old_tok, new_tok = entry
        display: Token = new_tok if new_tok else old_tok

        if display.kind == "sentence":
            if tag == "equal":
                txt = f"{_GRAY}{display.text}{_RESET}" if color else display.text
                lines.extend(_wrap(txt, "  "))
                lines.append("")
            elif tag == "replace":
                pfx_old = f"  {_RED}←{_RESET} " if color else "  ← "
                pfx_new = f"  {_GREEN}→{_RESET} " if color else "  → "
                old_marked, new_marked = _word_diff_sides(old_tok.text, new_tok.text, color)
                lines.extend(_wrap(old_marked, pfx_old))
                lines.extend(_wrap(new_marked, pfx_new))
                lines.append("")
            elif tag == "insert":
                pfx = f"  {_GREEN}+{_RESET} " if color else "  + "
                txt = f"{_GREEN}{display.text}{_RESET}" if color else display.text
                lines.extend(_wrap(txt, pfx))
                lines.append("")
            elif tag == "delete":
                pfx = f"  {_RED}-{_RESET} " if color else "  - "
                txt = f"{_RED}{_STRIKE}{display.text}{_RESET}" if color else f"[-{display.text}-]"
                lines.extend(_wrap(txt, pfx))
                lines.append("")
            elif tag in ("move", "moved"):
                pfx = f"  {_BLUE}↕{_RESET} " if color else "  ↕ "
                txt = f"{_BLUE}{display.text}{_RESET}" if color else display.text
                lines.extend(_wrap(txt, pfx))
                lines.append("")
        else:  # citation
            num = cite_nums.get(i, "?")
            label = f"[{num}]"
            if tag == "equal":
                marker = f"{_GRAY}{label}{_RESET}" if color else label
            elif tag == "replace":
                marker = f"{_AMBER}{label}*{_RESET}" if color else f"{label}*"
            elif tag == "insert":
                marker = f"{_GREEN}{label}+{_RESET}" if color else f"{label}+"
            elif tag == "delete":
                marker = f"{_RED}{label}-{_RESET}" if color else f"{label}-"
            else:
                marker = f"{_BLUE}{label}↕{_RESET}" if color else f"{label}↕"
            # Append citation marker to last non-empty line
            if lines and lines[-1].strip():
                lines[-1] = lines[-1].rstrip() + " " + marker
            elif lines:
                lines[-2] = lines[-2].rstrip() + " " + marker if len(lines) > 1 else lines[-1] + marker
            else:
                lines.append("  " + marker)

            # Build footnote
            if tag == "replace":
                old_marked, new_marked = _word_diff_sides(old_tok.text, new_tok.text, color)
                footnotes.append(f"  {marker} {old_marked} → {new_marked}")
            elif tag in ("insert", "delete", "equal", "move", "moved"):
                txt = f"{_GRAY}{display.text}{_RESET}" if (color and tag == "equal") else display.text
                footnotes.append(f"  {marker} {txt}")

    if footnotes:
        lines.append("")
        lines.append("  Citations:")
        lines.extend(footnotes)

    return lines


# ── Public tool interface ──────────────────────────────────────────────────────

def section_diff(
    original: str,
    revised: str,
    output: Literal["html", "text"] = "html",
    color: bool = True,
    width: int = 80,
) -> str | list[str]:
    """
    Diff two wikitext section strings using sentence-level Heckel alignment.

    output='html'  → HTML string (for st.html())
    output='text'  → list[str] of display lines (for print())

    Falls back to the paragraph-level SequenceMatcher if spaCy/mdiff are unavailable.
    """
    record_tool_call("diff")
    log_tool_call("diff")

    if not _HAS_MDIFF or not _HAS_SPACY:
        if output == "html":
            return section_diff_html(original, revised)
        return section_diff_text(original, revised, width=width, color=color)

    ops = heckel_diff_ops(original, revised)
    if not ops:
        return "<p><em>(no changes)</em></p>" if output == "html" else ["  (no changes)"]

    if output == "html":
        return _render_html(ops)
    return _render_text(ops, width=width, color=color)
