# ABOUTME: Paragraph-aware diff utilities shared between the CLI and Streamlit renderers.
# ABOUTME: Uses SequenceMatcher on word tokens — the best choice for human-readable prose diffs.

import difflib
import html
import re


def split_paragraphs(text: str) -> list[str]:
    """Split text into non-empty paragraphs (double-newline delimited)."""
    paras = re.split(r"\n\n+", text.strip())
    return [p.strip() for p in paras if p.strip()]


def word_diff_ops(old: str, new: str) -> list[tuple[str, str]]:
    """
    Word-level diff using SequenceMatcher (Ratcliff-Obershelp).

    Returns a list of (tag, text) pairs where tag is 'equal', 'delete', or 'insert'.
    'replace' is expanded into a delete immediately followed by an insert.
    autojunk=False because Wikipedia paragraphs are too short for heuristic junk detection.
    """
    old_words = old.split()
    new_words = new.split()
    matcher = difflib.SequenceMatcher(None, old_words, new_words, autojunk=False)
    ops = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            ops.append(("equal", " ".join(old_words[i1:i2])))
        elif tag == "replace":
            ops.append(("delete", " ".join(old_words[i1:i2])))
            ops.append(("insert", " ".join(new_words[j1:j2])))
        elif tag == "delete":
            ops.append(("delete", " ".join(old_words[i1:i2])))
        elif tag == "insert":
            ops.append(("insert", " ".join(new_words[j1:j2])))
    return ops


def paragraph_diff_html(old_para: str, new_para: str) -> str:
    """
    Render one paragraph pair as HTML: original on top, revised below.
    Word-level highlights: red strikethrough for deletions, green for insertions.
    """
    if not old_para:
        escaped = html.escape(new_para)
        return (
            "<div style='margin-bottom:14px;font-size:14px;line-height:1.7'>"
            f"<div style='background:#f5fff5;padding:10px 14px;"
            f"border-left:4px solid #66bb6a'>{escaped}</div>"
            "</div>"
        )
    if not new_para:
        escaped = html.escape(old_para)
        return (
            "<div style='margin-bottom:14px;font-size:14px;line-height:1.7'>"
            f"<div style='background:#fff5f5;padding:10px 14px;"
            f"border-left:4px solid #e57373;text-decoration:line-through'>{escaped}</div>"
            "</div>"
        )

    ops = word_diff_ops(old_para, new_para)
    old_parts, new_parts = [], []
    for tag, text in ops:
        escaped = html.escape(text)
        if tag == "equal":
            old_parts.append(escaped)
            new_parts.append(escaped)
        elif tag == "delete":
            old_parts.append(
                f"<span style='background:#ffd7d5;text-decoration:line-through;"
                f"border-radius:2px;padding:0 2px'>{escaped}</span>"
            )
        elif tag == "insert":
            new_parts.append(
                f"<span style='background:#d4edda;border-radius:2px;"
                f"padding:0 2px'>{escaped}</span>"
            )

    old_html = " ".join(old_parts)
    new_html = " ".join(new_parts)
    return (
        "<div style='margin-bottom:14px;font-size:14px;line-height:1.7'>"
        f"<div style='background:#fff5f5;padding:10px 14px;"
        f"border-left:4px solid #e57373;margin-bottom:3px'>{old_html}</div>"
        f"<div style='background:#f5fff5;padding:10px 14px;"
        f"border-left:4px solid #66bb6a'>{new_html}</div>"
        "</div>"
    )


def section_diff_html(original: str, revised: str) -> str:
    """
    Full section diff: match paragraphs with SequenceMatcher, then word-diff each pair.
    Returns an HTML string suitable for st.html().
    """
    orig_paras = split_paragraphs(original)
    rev_paras = split_paragraphs(revised)

    if not orig_paras and not rev_paras:
        return "<p><em>(empty)</em></p>"
    if not orig_paras:
        return "".join(paragraph_diff_html("", p) for p in rev_paras)
    if not rev_paras:
        return "".join(paragraph_diff_html(p, "") for p in orig_paras)

    matcher = difflib.SequenceMatcher(None, orig_paras, rev_paras, autojunk=False)
    blocks = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for p in orig_paras[i1:i2]:
                escaped = html.escape(p)
                blocks.append(
                    "<div style='margin-bottom:14px;font-size:14px;line-height:1.7;"
                    f"padding:10px 14px;background:#fafafa;border-left:4px solid #ccc'>"
                    f"{escaped}</div>"
                )
        elif tag == "replace":
            old_ps = orig_paras[i1:i2]
            new_ps = rev_paras[j1:j2]
            pairs = max(len(old_ps), len(new_ps))
            for i in range(pairs):
                op = old_ps[i] if i < len(old_ps) else ""
                np = new_ps[i] if i < len(new_ps) else ""
                blocks.append(paragraph_diff_html(op, np))
        elif tag == "delete":
            for p in orig_paras[i1:i2]:
                blocks.append(paragraph_diff_html(p, ""))
        elif tag == "insert":
            for p in rev_paras[j1:j2]:
                blocks.append(paragraph_diff_html("", p))
    return "\n".join(blocks)


# ── CLI text rendering ──────────────────────────────────────────────────────────

# ANSI color codes
_RED = "\033[31m"
_GREEN = "\033[32m"
_GRAY = "\033[2m"       # dim for unchanged context
_RESET = "\033[0m"
_STRIKE = "\033[9m"     # strikethrough (widely supported)


_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def _visible_len(s: str) -> int:
    """String length ignoring ANSI escape sequences."""
    return len(_ANSI_RE.sub("", s))


def _colorize_markers(text: str) -> str:
    """Replace [-...-] and {+...+} markers with ANSI color sequences."""
    text = re.sub(
        r'\[-(.+?)-\]',
        lambda m: f"{_RED}{_STRIKE}{m.group(1)}{_RESET}",
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r'\{\+(.+?)\+\}',
        lambda m: f"{_GREEN}{m.group(1)}{_RESET}",
        text,
        flags=re.DOTALL,
    )
    return text


def _paragraph_diff_markers(old_para: str, new_para: str) -> tuple[str, str]:
    """Return (old_marked, new_marked) with [-del-] / {+ins+} plain-text markers."""
    if not old_para:
        return "", "{+" + new_para + "+}"
    if not new_para:
        return "[-" + old_para + "-]", ""

    ops = word_diff_ops(old_para, new_para)
    old_parts, new_parts = [], []
    for tag, text in ops:
        if tag == "equal":
            old_parts.append(text)
            new_parts.append(text)
        elif tag == "delete":
            old_parts.append(f"[-{text}-]")
        elif tag == "insert":
            new_parts.append("{+" + text + "+}")
    return " ".join(old_parts), " ".join(new_parts)


def section_diff_text(original: str, revised: str, width: int = 68,
                      color: bool = False) -> list[str]:
    """
    Return lines for terminal display: paragraph by paragraph, original above revised.

    Unchanged paragraphs are shown once (dimmed when color=True).
    Changed paragraphs show [-deleted-] / {+inserted+} markers, word-wrapped to `width`.
    With color=True, markers are replaced by ANSI red-strikethrough / green highlights.
    Word-wrap is computed on plain text so column widths stay accurate.
    """
    orig_paras = split_paragraphs(original)
    rev_paras = split_paragraphs(revised)
    lines = []

    measure = _visible_len if color else len

    def _wrap(text: str, plain_prefix: str, display_prefix: str) -> list[str]:
        """
        Word-wrap `text` (which may contain ANSI codes) to `width`.
        plain_prefix is used for width accounting; display_prefix is what's printed.
        Continuation lines are indented to the same visible width as plain_prefix.
        """
        if not text:
            return []
        indent = " " * len(plain_prefix)
        out, current_plain, current_display = [], plain_prefix, display_prefix
        for word in text.split():
            word_vis = measure(word)
            if current_plain != plain_prefix and measure(current_plain) + 1 + word_vis > width:
                out.append(current_display)
                current_plain = indent + _ANSI_RE.sub("", word) if color else indent + word
                current_display = indent + word
            else:
                sep = "" if current_plain == plain_prefix else " "
                current_plain += sep + (_ANSI_RE.sub("", word) if color else word)
                current_display += sep + word
        if _visible_len(current_display.strip()):
            out.append(current_display)
        return out

    def _emit_equal(para: str) -> None:
        display = f"{_GRAY}{para}{_RESET}" if color else para
        wrapped = _wrap(display, "  ", "  ")
        lines.extend(wrapped)
        lines.append("")

    def _emit_pair(old_para: str, new_para: str) -> None:
        old_marked, new_marked = _paragraph_diff_markers(old_para, new_para)
        if old_marked:
            plain_pfx = "  ← "   # "  ← "
            if color:
                text = _colorize_markers(old_marked)
                disp_pfx = f"  {_RED}←{_RESET} "
            else:
                text = old_marked
                disp_pfx = plain_pfx
            lines.extend(_wrap(text, plain_pfx, disp_pfx))
        if new_marked:
            plain_pfx = "  → "   # "  → "
            if color:
                text = _colorize_markers(new_marked)
                disp_pfx = f"  {_GREEN}→{_RESET} "
            else:
                text = new_marked
                disp_pfx = plain_pfx
            lines.extend(_wrap(text, plain_pfx, disp_pfx))
        lines.append("")

    if not orig_paras and not rev_paras:
        return ["  (empty)"]

    matcher = difflib.SequenceMatcher(None, orig_paras, rev_paras, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for p in orig_paras[i1:i2]:
                _emit_equal(p)
        elif tag == "replace":
            old_ps, new_ps = orig_paras[i1:i2], rev_paras[j1:j2]
            for i in range(max(len(old_ps), len(new_ps))):
                _emit_pair(
                    old_ps[i] if i < len(old_ps) else "",
                    new_ps[i] if i < len(new_ps) else "",
                )
        elif tag == "delete":
            for p in orig_paras[i1:i2]:
                _emit_pair(p, "")
        elif tag == "insert":
            for p in rev_paras[j1:j2]:
                _emit_pair("", p)
    return lines
