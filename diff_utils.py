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

def paragraph_diff_text(old_para: str, new_para: str) -> tuple[str, str]:
    """
    Return (old_line, new_line) with [-deleted-] and {+inserted+} markers for terminal display.
    """
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


def section_diff_text(original: str, revised: str, width: int = 68) -> list[str]:
    """
    Return lines for terminal display: paragraph by paragraph, original above revised.
    Unchanged paragraphs are shown once with no markers. Changed paragraphs show
    [-deleted-] and {+inserted+} word markers, word-wrapped to `width`.
    """
    orig_paras = split_paragraphs(original)
    rev_paras = split_paragraphs(revised)
    lines = []

    def _wrap(text: str, prefix: str = "  ") -> list[str]:
        """Word-wrap `text` to `width`, indenting continuation lines to match prefix."""
        if not text:
            return []
        indent = " " * len(prefix)
        out, current = [], prefix
        for word in text.split():
            if current != prefix and len(current) + 1 + len(word) > width:
                out.append(current)
                current = indent + word
            else:
                current = current + (" " if current != prefix else "") + word
        if current.strip():
            out.append(current)
        return out

    if not orig_paras and not rev_paras:
        return ["  (empty)"]

    matcher = difflib.SequenceMatcher(None, orig_paras, rev_paras, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for p in orig_paras[i1:i2]:
                lines.extend(_wrap(p, "  "))
                lines.append("")
        elif tag == "replace":
            old_ps = orig_paras[i1:i2]
            new_ps = rev_paras[j1:j2]
            for i in range(max(len(old_ps), len(new_ps))):
                op = old_ps[i] if i < len(old_ps) else ""
                np = new_ps[i] if i < len(new_ps) else ""
                old_marked, new_marked = paragraph_diff_text(op, np)
                if old_marked:
                    lines.extend(_wrap(old_marked, "  ← "))
                if new_marked:
                    lines.extend(_wrap(new_marked, "  → "))
                lines.append("")
        elif tag == "delete":
            for p in orig_paras[i1:i2]:
                lines.extend(_wrap(p, "  ← "))
                lines.append("")
        elif tag == "insert":
            for p in rev_paras[j1:j2]:
                lines.extend(_wrap(p, "  → "))
                lines.append("")
    return lines
