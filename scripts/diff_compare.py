# ABOUTME: Diff algorithm comparison harness — renders side-by-side HTML for visual evaluation.
# ABOUTME: Compares current paragraph-level SequenceMatcher vs sentence-level Heckel with citation support.

import difflib
import html
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).parent.parent))

import openai
from dotenv import load_dotenv

load_dotenv()

from diff_utils import split_paragraphs, word_diff_ops

try:
    from mdiff import HeckelSequenceMatcher
    HAS_MDIFF = True
except ImportError:
    HAS_MDIFF = False
    print("mdiff not installed — only current algorithm will render")


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class Token:
    kind: Literal["sentence", "citation"]
    text: str       # prose text or raw wikitext of one <ref>…</ref> block
    para_idx: int   # paragraph index in the revised document (−1 for old-only)


# ── Sentence/citation splitting ────────────────────────────────────────────────

import spacy as _spacy
_nlp = _spacy.load("en_core_web_sm", disable=["ner", "lemmatizer"])

_REF_PAT = re.compile(r'<ref[^>]*>.*?</ref>|<ref[^>]*/>', re.DOTALL)


def _tokenize_paragraph(para: str, para_idx: int) -> list[Token]:
    """Split one paragraph into interleaved sentence and citation Tokens."""
    # Insert a space before every <ref> so citations don't fuse to preceding word.
    spaced = re.sub(r'(?<! )<ref', ' <ref', para)

    tokens: list[Token] = []
    cursor = 0
    for m in _REF_PAT.finditer(spaced):
        prose_run = spaced[cursor:m.start()]
        if prose_run.strip():
            for sent in _nlp(prose_run).sents:
                s = sent.text.strip()
                if s:
                    tokens.append(Token("sentence", s, para_idx))
        tokens.append(Token("citation", m.group(), para_idx))
        cursor = m.end()

    trailing = spaced[cursor:]
    if trailing.strip():
        for sent in _nlp(trailing).sents:
            s = sent.text.strip()
            if s:
                tokens.append(Token("sentence", s, para_idx))

    return tokens


def tokenize(text: str) -> list[Token]:
    """Produce flat Token list from wikitext (all paragraphs)."""
    tokens: list[Token] = []
    for i, para in enumerate(split_paragraphs(text)):
        tokens.extend(_tokenize_paragraph(para, i))
    return tokens


# ── Similarity ─────────────────────────────────────────────────────────────────

_MIN_SIMILARITY = 0.25          # prose sentences
_MIN_CITATION_SIMILARITY = 0.50  # citations

_URL_PAT = re.compile(r'(?:url|href)\s*=\s*([^\s|}]+)', re.IGNORECASE)


def _extract_url(wikitext: str) -> str | None:
    m = _URL_PAT.search(wikitext)
    return m.group(1).strip() if m else None


def _lexical_sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.split(), b.split(), autojunk=False).ratio()


def _token_similarity(a: Token, b: Token) -> float:
    if a.kind != b.kind:
        return 0.0
    if a.kind == "sentence":
        return _lexical_sim(a.text, b.text)
    # citation: URL-first
    url_a, url_b = _extract_url(a.text), _extract_url(b.text)
    if url_a and url_b:
        return 1.0 if url_a == url_b else _lexical_sim(a.text, b.text)
    return _lexical_sim(a.text, b.text)


def _threshold(kind: str) -> float:
    return _MIN_CITATION_SIMILARITY if kind == "citation" else _MIN_SIMILARITY


# ── Algorithm A: current (paragraph-level SequenceMatcher) ───────────────────

def diff_current(original: str, revised: str) -> str:
    """Existing paragraph-level diff — copied from diff_utils.section_diff_html."""
    from diff_utils import section_diff_html
    return section_diff_html(original, revised)


# ── Algorithm B: sentence-level Heckel with citation tokens ───────────────────

def _word_diff_inline(old_text: str, new_text: str) -> str:
    """Return HTML inline word diff (no wrapper div)."""
    parts = []
    for tag, text in word_diff_ops(old_text, new_text):
        escaped = html.escape(text)
        if tag == "equal":
            parts.append(escaped)
        elif tag == "delete":
            parts.append(
                f"<span style='background:#ffd7d5;text-decoration:line-through;"
                f"border-radius:2px;padding:0 2px'>{escaped}</span>"
            )
        elif tag == "insert":
            parts.append(
                f"<span style='background:#d4edda;border-radius:2px;"
                f"padding:0 2px'>{escaped}</span>"
            )
    return " ".join(parts)


def _citation_field_diff(old_text: str, new_text: str) -> str:
    """Return field-level diff for two citations (inline word diff on full wikitext)."""
    return _word_diff_inline(old_text, new_text)


# CSS helpers
_SENT_DIV = (
    "margin-bottom:6px;font-size:14px;line-height:1.7;"
    "padding:8px 14px;border-radius:0 4px 4px 0"
)


def _sent_div(body: str, bg: str, border: str, extra: str = "") -> str:
    style = f"{_SENT_DIV};background:{bg};border-left:4px solid {border};{extra}"
    return f"<div style='{style}'>{body}</div>"


# ── Superscript citation rendering helpers ─────────────────────────────────────

_CITE_COLORS = {
    "equal":  ("#94a3b8", "color:#94a3b8"),          # grey
    "replace": ("#f59e0b", "color:#b45309"),          # amber
    "insert":  ("#22c55e", "color:#15803d"),          # green
    "delete":  ("#ef4444", "color:#991b1b"),          # red
    "move":    ("#3b82f6", "color:#1d4ed8"),          # blue
    "moved":   ("#3b82f6", "color:#1d4ed8"),
}


def _sup_html(num: int, op: str, extra_style: str = "") -> str:
    border_color, text_color = _CITE_COLORS.get(op, ("#94a3b8", "color:#94a3b8"))
    strike = "text-decoration:line-through;" if op == "delete" else ""
    style = (
        f"font-size:0.7em;vertical-align:super;font-weight:600;"
        f"border:1px solid {border_color};border-radius:3px;"
        f"padding:0 3px;margin-left:2px;{text_color};{strike}{extra_style}"
    )
    return f"<span style='{style}'>[{num}]</span>"


def _footnote_html(num: int, op: str, text: str, paired_text: str | None = None) -> str:
    border_color, text_color = _CITE_COLORS.get(op, ("#94a3b8", "color:#94a3b8"))
    body = ""
    if op == "replace" and paired_text:
        body = _citation_field_diff(paired_text, text)
    else:
        body = html.escape(text)
    strike = "text-decoration:line-through;opacity:.7;" if op == "delete" else ""
    return (
        f"<div style='margin-bottom:4px;font-size:12px;font-family:monospace;"
        f"border-left:3px solid {border_color};padding:3px 8px;{strike}'>"
        f"<span style='font-weight:700;{text_color}'>[{num}]</span> {body}</div>"
    )


# ── Core Heckel diff pipeline ──────────────────────────────────────────────────

def _run_heckel(original: str, revised: str) -> list[tuple]:
    """
    Return raw op list: (tag, old_token|None, new_token|None).
    Tags: equal, replace, delete, insert, move, moved.
    """
    if not HAS_MDIFF:
        return []

    orig_tokens = tokenize(original)
    rev_tokens = tokenize(revised)

    old_texts = [t.text for t in orig_tokens]
    new_texts = [t.text for t in rev_tokens]

    sm = HeckelSequenceMatcher(old_texts, new_texts)

    raw: list[tuple | None] = []
    for op in sm.get_opcodes():
        tag, i1, i2, j1, j2 = op.tag, op.i1, op.i2, op.j1, op.j2
        if tag == "equal":
            for k in range(i2 - i1):
                raw.append(("equal", orig_tokens[i1 + k], rev_tokens[j1 + k]))
        elif tag == "replace":
            old_chunk = orig_tokens[i1:i2]
            new_chunk = rev_tokens[j1:j2]
            for k in range(max(len(old_chunk), len(new_chunk))):
                o = old_chunk[k] if k < len(old_chunk) else None
                n = new_chunk[k] if k < len(new_chunk) else None
                if o and n and _token_similarity(o, n) >= _threshold(o.kind):
                    raw.append(("replace", o, n))
                else:
                    if o:
                        raw.append(("delete", o, None))
                    if n:
                        raw.append(("insert", None, n))
        elif tag == "insert":
            for k in range(j2 - j1):
                raw.append(("insert", None, rev_tokens[j1 + k]))
        elif tag == "delete":
            for k in range(i2 - i1):
                raw.append(("delete", orig_tokens[i1 + k], None))
        elif tag == "move":
            for k in range(i2 - i1):
                raw.append(("move", orig_tokens[i1 + k], None))
        elif tag == "moved":
            for k in range(j2 - j1):
                raw.append(("moved", None, rev_tokens[j1 + k]))

    # Fuzzy orphan pairing (greedy, same kind only)
    orphan_del = [i for i, r in enumerate(raw) if r and r[0] == "delete"]
    orphan_ins = [i for i, r in enumerate(raw) if r and r[0] == "insert"]
    used_ins: set[int] = set()
    for di in orphan_del:
        old_tok = raw[di][1]
        best_sim, best_ii = 0.0, None
        for ii in orphan_ins:
            if ii in used_ins:
                continue
            new_tok = raw[ii][2]
            if new_tok.kind != old_tok.kind:
                continue
            sim = _token_similarity(old_tok, new_tok)
            if sim > best_sim:
                best_sim, best_ii = sim, ii
        if best_ii is not None and best_sim >= _threshold(old_tok.kind):
            raw[di] = ("replace", old_tok, raw[best_ii][2])
            raw[best_ii] = None
            used_ins.add(best_ii)

    return [r for r in raw if r is not None]


def _assign_citation_numbers(ops: list[tuple]) -> dict[int, int]:
    """
    Return mapping from ops index → display number for citation tokens that
    appear in the revised document (equal, replace-new, insert, moved).
    Old-only citations (delete) share a number with their paired new citation
    if one exists, otherwise get their own number from old-doc order.
    """
    nums: dict[int, int] = {}
    counter = 0
    # First pass: new-side citations
    for i, entry in enumerate(ops):
        tag = entry[0]
        new_tok: Token | None = entry[2]
        if new_tok and new_tok.kind == "citation" and tag in ("equal", "replace", "insert", "moved"):
            counter += 1
            nums[i] = counter
    # Second pass: old-only deletes get their own number
    for i, entry in enumerate(ops):
        tag = entry[0]
        old_tok: Token | None = entry[1]
        if old_tok and old_tok.kind == "citation" and tag == "delete":
            counter += 1
            nums[i] = counter
    return nums


# ── Mode A: superscript rendering ─────────────────────────────────────────────

def _render_mode_a(ops: list[tuple]) -> str:
    """Render with citations as colored superscript [N], footnotes at bottom."""
    cite_nums = _assign_citation_numbers(ops)
    blocks: list[str] = []
    footnotes: list[str] = []
    last_para = -1
    pending_inline: list[str] = []  # accumulated inline sentence content

    def flush_pending():
        nonlocal pending_inline
        if pending_inline:
            blocks.append(
                "<div style='margin-bottom:6px;font-size:14px;line-height:1.7;"
                "padding:8px 14px;background:#f8fafc'>"
                + "".join(pending_inline) + "</div>"
            )
            pending_inline = []

    def maybe_para(np: int):
        nonlocal last_para
        if np >= 0 and np != last_para:
            flush_pending()
            blocks.append(
                f"<div style='font-size:11px;color:#94a3b8;margin:10px 0 4px;"
                f"text-transform:uppercase;letter-spacing:.06em'>"
                f"¶ paragraph {np + 1}</div>"
            )
            last_para = np

    for i, entry in enumerate(ops):
        tag, old_tok, new_tok = entry[0], entry[1], entry[2]
        display_tok: Token = new_tok if new_tok else old_tok

        if display_tok.kind == "sentence":
            np = display_tok.para_idx
            maybe_para(np)
            if tag == "equal":
                pending_inline.append(html.escape(display_tok.text) + " ")
            elif tag == "replace":
                flush_pending()
                blocks.append(_sent_div(
                    _word_diff_inline(old_tok.text, new_tok.text),
                    "#f8fafc", "#94a3b8"
                ))
            elif tag == "insert":
                flush_pending()
                blocks.append(_sent_div(html.escape(display_tok.text), "#f5fff5", "#66bb6a"))
            elif tag == "delete":
                flush_pending()
                blocks.append(_sent_div(
                    html.escape(display_tok.text), "#fff5f5", "#e57373",
                    "text-decoration:line-through;color:#888"
                ))
            elif tag in ("move", "moved"):
                flush_pending()
                label = "<span style='font-size:11px;font-weight:600;color:#1d4ed8;text-transform:uppercase;letter-spacing:.05em'>↕ moved</span> "
                blocks.append(_sent_div(label + html.escape(display_tok.text), "#eff6ff", "#3b82f6"))

        else:  # citation
            num = cite_nums.get(i, "?")
            op_for_display = tag
            # Citations are rendered as superscripts appended to whatever came before
            flush_pending()
            sup = _sup_html(num, op_for_display)
            # Append the sup to the last sentence block if possible, else as its own span
            if blocks:
                # Inject sup before closing </div> of last block
                last = blocks[-1]
                if last.endswith("</div>"):
                    blocks[-1] = last[:-6] + sup + "</div>"
                else:
                    blocks.append(f"<span>{sup}</span>")
            else:
                blocks.append(f"<span>{sup}</span>")

            # Build footnote
            if tag == "replace":
                footnotes.append(_footnote_html(num, "replace", new_tok.text, old_tok.text))
            elif tag == "delete":
                footnotes.append(_footnote_html(num, "delete", old_tok.text))
            elif tag == "insert":
                footnotes.append(_footnote_html(num, "insert", new_tok.text))
            elif tag == "equal":
                footnotes.append(_footnote_html(num, "equal", display_tok.text))
            elif tag in ("move", "moved"):
                footnotes.append(_footnote_html(num, "moved", display_tok.text))

    flush_pending()

    result = "\n".join(blocks)
    if footnotes:
        result += (
            "<div style='margin-top:20px;border-top:1px solid #e2e8f0;padding-top:12px'>"
            "<div style='font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;"
            "letter-spacing:.06em;margin-bottom:8px'>Citations</div>"
            + "\n".join(footnotes)
            + "</div>"
        )
    return result


# ── Mode B: raw wikitext rendering ────────────────────────────────────────────

def _render_mode_b(ops: list[tuple]) -> str:
    """Render with citations shown inline as colored raw wikitext."""
    blocks: list[str] = []
    last_para = -1

    def maybe_para(np: int):
        nonlocal last_para
        if np >= 0 and np != last_para:
            blocks.append(
                f"<div style='font-size:11px;color:#94a3b8;margin:10px 0 4px;"
                f"text-transform:uppercase;letter-spacing:.06em'>"
                f"¶ paragraph {np + 1}</div>"
            )
            last_para = np

    def cite_block(text: str, bg: str, border: str, extra: str = "") -> str:
        escaped = html.escape(text)
        return (
            f"<code style='display:block;margin:2px 0 6px;font-size:11px;"
            f"white-space:pre-wrap;word-break:break-all;"
            f"background:{bg};border-left:3px solid {border};"
            f"padding:4px 8px;border-radius:0 3px 3px 0;{extra}'>"
            f"{escaped}</code>"
        )

    for entry in ops:
        tag, old_tok, new_tok = entry[0], entry[1], entry[2]
        display_tok: Token = new_tok if new_tok else old_tok
        np = display_tok.para_idx
        maybe_para(np if np >= 0 else last_para)

        if display_tok.kind == "sentence":
            if tag == "equal":
                blocks.append(_sent_div(html.escape(display_tok.text), "#fafafa", "#ccc", "color:#555"))
            elif tag == "replace":
                blocks.append(_sent_div(
                    _word_diff_inline(old_tok.text, new_tok.text),
                    "#f8fafc", "#94a3b8"
                ))
            elif tag == "insert":
                blocks.append(_sent_div(html.escape(display_tok.text), "#f5fff5", "#66bb6a"))
            elif tag == "delete":
                blocks.append(_sent_div(
                    html.escape(display_tok.text), "#fff5f5", "#e57373",
                    "text-decoration:line-through;color:#888"
                ))
            elif tag in ("move", "moved"):
                label = "<span style='font-size:11px;font-weight:600;color:#1d4ed8;text-transform:uppercase;letter-spacing:.05em'>↕ moved</span> "
                blocks.append(_sent_div(label + html.escape(display_tok.text), "#eff6ff", "#3b82f6"))
        else:  # citation
            if tag == "equal":
                blocks.append(cite_block(display_tok.text, "#f8fafc", "#94a3b8"))
            elif tag == "replace":
                diff_body = _citation_field_diff(old_tok.text, new_tok.text)
                blocks.append(
                    f"<code style='display:block;margin:2px 0 6px;font-size:11px;"
                    f"white-space:pre-wrap;word-break:break-all;"
                    f"background:#fffbeb;border-left:3px solid #f59e0b;"
                    f"padding:4px 8px;border-radius:0 3px 3px 0'>{diff_body}</code>"
                )
            elif tag == "insert":
                blocks.append(cite_block(display_tok.text, "#f5fff5", "#66bb6a"))
            elif tag == "delete":
                blocks.append(cite_block(display_tok.text, "#fff5f5", "#e57373",
                                         "text-decoration:line-through;color:#888"))
            elif tag in ("move", "moved"):
                blocks.append(cite_block(display_tok.text, "#eff6ff", "#3b82f6"))

    return "\n".join(blocks)


def diff_heckel(original: str, revised: str) -> tuple[str, str]:
    """Return (mode_a_html, mode_b_html) for sentence/citation-level Heckel diff."""
    if not HAS_MDIFF:
        err = "<p><em>mdiff not installed</em></p>"
        return err, err
    ops = _run_heckel(original, revised)
    return _render_mode_a(ops), _render_mode_b(ops)


# ── Algorithm C: LLM interpretation layer ─────────────────────────────────────

def _extract_ops_for_llm(original: str, revised: str) -> dict:
    """Extract structured sentence-level ops to feed to the LLM."""
    orig_tokens = tokenize(original)
    rev_tokens = tokenize(revised)
    old_texts = [t.text for t in orig_tokens]
    new_texts = [t.text for t in rev_tokens]

    sm = HeckelSequenceMatcher(old_texts, new_texts) if HAS_MDIFF else \
        difflib.SequenceMatcher(None, old_texts, new_texts, autojunk=False)

    ops = {"deleted": [], "inserted": [], "replaced": [], "moved": [], "unchanged": []}

    for op in sm.get_opcodes():
        tag, i1, i2, j1, j2 = op.tag, op.i1, op.i2, op.j1, op.j2
        if tag == "equal":
            for t in orig_tokens[i1:i2]:
                ops["unchanged"].append(t.text)
        elif tag == "replace":
            old_chunk = orig_tokens[i1:i2]
            new_chunk = rev_tokens[j1:j2]
            for k in range(max(len(old_chunk), len(new_chunk))):
                o = old_chunk[k] if k < len(old_chunk) else None
                n = new_chunk[k] if k < len(new_chunk) else None
                if o and n:
                    sim = _token_similarity(o, n)
                    thresh = _threshold(o.kind)
                    if sim >= thresh:
                        ops["replaced"].append({"from": o.text, "to": n.text, "similarity": round(sim, 2)})
                    else:
                        if o:
                            ops["deleted"].append(o.text)
                        if n:
                            ops["inserted"].append(n.text)
                elif o:
                    ops["deleted"].append(o.text)
                elif n:
                    ops["inserted"].append(n.text)
        elif tag == "insert":
            for t in rev_tokens[j1:j2]:
                ops["inserted"].append(t.text)
        elif tag == "delete":
            for t in orig_tokens[i1:i2]:
                ops["deleted"].append(t.text)
        elif tag == "move":
            for t in orig_tokens[i1:i2]:
                ops["moved"].append({"sentence": t.text, "direction": "source"})
        elif tag == "moved":
            for t in rev_tokens[j1:j2]:
                ops["moved"].append({"sentence": t.text, "direction": "destination"})

    return ops


_LLM_PROMPT = """\
You are a diff renderer for Wikipedia article edits. You will be given a \
structured diff — deleted sentences, inserted sentences, replaced sentences \
(with before/after), moved sentences, and unchanged sentences.

Your job is to render the FULL revised text as a visual diff that a human \
reviewer can read. Show every sentence — unchanged ones in plain text, \
changed ones highlighted.

Rendering rules (HTML only, no markdown):
- Unchanged sentence: plain text, no markup
- Deleted sentence (no replacement): wrap in <span style="background:#ffd7d5;text-decoration:line-through;padding:1px 3px;border-radius:2px">...</span>
- Inserted sentence (no original): wrap in <span style="background:#d4edda;padding:1px 3px;border-radius:2px">...</span>
- Replaced sentence: show the OLD version in <span style="background:#ffd7d5;text-decoration:line-through;padding:1px 3px;border-radius:2px">...</span> immediately followed by the NEW version in <span style="background:#d4edda;padding:1px 3px;border-radius:2px">...</span>
- Moved sentence: wrap in <span style="background:#fef3c7;padding:1px 3px;border-radius:2px">↕ ...</span>
- Separate paragraphs with <p> tags
- Do NOT add any prose explanation — only the rendered diff text
- Do NOT invent any text not present in the structured diff

Structured diff:
{ops_json}
"""


def diff_llm(original: str, revised: str) -> str:
    """Pass structured ops to the LLM and return an HTML interpretation."""
    ops = _extract_ops_for_llm(original, revised)

    if not ops["deleted"] and not ops["inserted"] and not ops["replaced"] and not ops["moved"]:
        return "<p><em>(no changes)</em></p>"

    ops_for_llm = {k: v for k, v in ops.items() if k != "unchanged"}

    client = openai.OpenAI()
    response = client.chat.completions.create(
        model=os.getenv("DRAFT_MODEL", "gpt-4o"),
        messages=[{
            "role": "user",
            "content": _LLM_PROMPT.format(ops_json=json.dumps(ops_for_llm, indent=2))
        }],
        temperature=0.2,
        max_completion_tokens=1500,
    )
    return response.choices[0].message.content.strip()


# ── HTML page builder ──────────────────────────────────────────────────────────

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Diff Algorithm Comparison</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          margin: 0; padding: 20px; background: #f8fafc; color: #1e293b; }}
  h1 {{ font-size: 1.4rem; font-weight: 700; margin-bottom: 4px; }}
  .subtitle {{ color: #64748b; font-size: 0.9rem; margin-bottom: 32px; }}
  .example {{ background: white; border-radius: 8px; padding: 24px;
              box-shadow: 0 1px 3px rgba(0,0,0,.08); margin-bottom: 40px; }}
  .example-title {{ font-size: 1.1rem; font-weight: 600; margin-bottom: 4px; }}
  .example-meta {{ font-size: 0.8rem; color: #94a3b8; margin-bottom: 20px; }}
  .cols {{ display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 20px; }}
  .col-title {{ font-size: 0.8rem; font-weight: 700; text-transform: uppercase;
                letter-spacing: .06em; color: #64748b; margin-bottom: 12px;
                padding-bottom: 6px; border-bottom: 2px solid #e2e8f0; }}
  .legend {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 20px;
             font-size: 0.8rem; }}
  .legend-item {{ display: flex; align-items: center; gap: 6px; }}
  .swatch {{ width: 12px; height: 12px; border-radius: 2px; flex-shrink: 0; }}
</style>
</head>
<body>
<h1>Diff Algorithm Comparison</h1>
<p class="subtitle">
  A: current (paragraph-level SequenceMatcher) &nbsp;·&nbsp;
  B1: sentence-level Heckel — superscript citations &nbsp;·&nbsp;
  B2: sentence-level Heckel — raw wikitext citations &nbsp;·&nbsp;
  C: LLM interpretation
</p>
<div class="legend">
  <div class="legend-item"><div class="swatch" style="background:#fafafa;border:1px solid #ccc"></div> unchanged</div>
  <div class="legend-item"><div class="swatch" style="background:#fff5f5;border-left:3px solid #e57373"></div> deleted</div>
  <div class="legend-item"><div class="swatch" style="background:#f5fff5;border-left:3px solid #66bb6a"></div> inserted</div>
  <div class="legend-item"><div class="swatch" style="background:#fffbeb;border-left:3px solid #f59e0b"></div> modified citation</div>
  <div class="legend-item"><div class="swatch" style="background:#eff6ff;border-left:3px solid #3b82f6"></div> moved</div>
</div>
{examples}
</body>
</html>"""

EXAMPLE_TEMPLATE = """
<div class="example">
  <div class="example-title">{section} — example {n}</div>
  <div class="example-meta">{orig_chars}c / {orig_paras}p → {rev_chars}c / {rev_paras}p</div>
  <div class="cols">
    <div>
      <div class="col-title">A · Paragraph-level SequenceMatcher (current)</div>
      {diff_a}
    </div>
    <div>
      <div class="col-title">B1 · Sentence-level Heckel — superscript citations</div>
      {diff_b1}
    </div>
    <div>
      <div class="col-title">B2 · Sentence-level Heckel — raw wikitext citations</div>
      {diff_b2}
    </div>
    <div>
      <div class="col-title">C · LLM interpretation</div>
      {diff_c}
    </div>
  </div>
</div>
"""


def load_examples(max_examples: int = 8) -> list[dict]:
    """Load hand-crafted examples that exercise the diff algorithms meaningfully."""
    return [
        {
            "section": "Lead (sentence rewrite)",
            "original": (
                "Grafana is an open-source analytics and monitoring platform. "
                "It was originally developed by Torkel Ödegaard in 2013. "
                "Grafana Labs was founded in 2014 to support its development. "
                "The platform supports dozens of data sources including Prometheus, "
                "InfluxDB, and Elasticsearch."
            ),
            "revised": (
                "Grafana is an open-source observability platform used for analytics and monitoring. "
                "It was created by Torkel Ödegaard in 2013 and is now maintained by Grafana Labs, "
                "a company founded in 2014.\n\n"
                "The platform integrates with dozens of data sources including Prometheus, "
                "InfluxDB, and Elasticsearch, and is widely used in cloud-native environments."
            ),
            "orig_paras": 1,
            "rev_paras": 2,
        },
        {
            "section": "Architecture (citations added)",
            "original": (
                "Grafana's backend is written in Go and its frontend in TypeScript using React. "
                "The application runs as a single binary that serves a web interface and connects "
                "to external data sources through a plugin system. "
                "Plugins can be installed from the Grafana plugin catalogue or built by third parties."
            ),
            "revised": (
                "Grafana's backend is written in Go and its frontend in TypeScript using React."
                "<ref>{{cite web|url=https://github.com/grafana/grafana|title=Grafana repository|"
                "access-date=2026-05-09}}</ref> "
                "The application runs as a single binary that serves a web interface and connects "
                "to external data sources through a plugin system."
                "<ref>{{cite web|url=https://grafana.com/docs/|title=Grafana docs|"
                "access-date=2026-05-09}}</ref>\n\n"
                "Plugins can be installed from the Grafana plugin catalogue or built by third parties. "
                "The plugin ecosystem includes over 100 community-built integrations."
            ),
            "orig_paras": 1,
            "rev_paras": 2,
        },
        {
            "section": "Architecture (citation URL changed)",
            "original": (
                "Grafana's backend is written in Go.<ref>{{cite web|url=https://github.com/grafana/grafana|"
                "title=Grafana repository|access-date=2025-01-01}}</ref> "
                "The frontend uses TypeScript and React.<ref>{{cite web|url=https://grafana.com/docs/|"
                "title=Grafana docs|access-date=2025-01-01}}</ref>"
            ),
            "revised": (
                "Grafana's backend is written in Go.<ref>{{cite web|url=https://github.com/grafana/grafana|"
                "title=Grafana repository|access-date=2026-05-09}}</ref> "
                "The frontend uses TypeScript and React.<ref>{{cite web|url=https://grafana.com/docs/grafana/latest/|"
                "title=Grafana documentation|access-date=2026-05-09}}</ref>"
            ),
            "orig_paras": 1,
            "rev_paras": 1,
        },
        {
            "section": "History (restructure + removal)",
            "original": (
                "Chicago Booth was founded in 1898 as the School of Commerce and Administration. "
                "It was renamed the Graduate School of Business in 1959. "
                "In 2008, it was renamed again after a $300 million gift from alumnus David G. Booth. "
                "The school moved to its current location in Hyde Park in 1930. "
                "Notable Chicago Booth alumni include James O. McKinsey, founder of McKinsey & Company, "
                "and Eugene Fama, Nobel laureate in Economics."
            ),
            "revised": (
                "Chicago Booth was founded in 1898 as the School of Commerce and Administration "
                "and is one of the oldest business schools in the United States. "
                "In 2008, it was renamed after a $300 million gift from alumnus David G. Booth.\n\n"
                "The school's Hyde Park campus has been its home since 1930. "
                "Eugene Fama, a Nobel laureate in Economics, is among its most distinguished faculty."
            ),
            "orig_paras": 1,
            "rev_paras": 2,
        },
    ][:max_examples]


def build_report(output_path: str = "scripts/diff_comparison.html") -> None:
    examples = load_examples()
    print(f"Loaded {len(examples)} examples")

    example_blocks = []
    for n, ex in enumerate(examples, 1):
        print(f"  Rendering example {n}: {ex['section']} ({ex['orig_paras']}p → {ex['rev_paras']}p)...")
        diff_a = diff_current(ex["original"], ex["revised"])
        diff_b1, diff_b2 = diff_heckel(ex["original"], ex["revised"])
        print("    Calling LLM...")
        diff_c = diff_llm(ex["original"], ex["revised"])
        block = EXAMPLE_TEMPLATE.format(
            section=html.escape(ex["section"]),
            n=n,
            orig_chars=len(ex["original"]),
            orig_paras=ex["orig_paras"],
            rev_chars=len(ex["revised"]),
            rev_paras=ex["rev_paras"],
            diff_a=diff_a,
            diff_b1=diff_b1,
            diff_b2=diff_b2,
            diff_c=diff_c,
        )
        example_blocks.append(block)

    page = PAGE_TEMPLATE.format(examples="\n".join(example_blocks))
    Path(output_path).write_text(page)
    print(f"\nWrote {output_path}")


if __name__ == "__main__":
    build_report()
