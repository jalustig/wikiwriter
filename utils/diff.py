# ABOUTME: Diff utilities: paragraph-level SequenceMatcher and sentence-level Heckel with citations.
# ABOUTME: Provides HTML and plaintext renderers used by the Streamlit UI, CLI, and tools layer.

import difflib
import html
import re
from dataclasses import dataclass
from typing import Literal

try:
    import spacy as _spacy
    _nlp = _spacy.load("en_core_web_sm", disable=["ner", "lemmatizer"])
    _HAS_SPACY = True
except Exception:
    _HAS_SPACY = False

try:
    from mdiff import HeckelSequenceMatcher
    _HAS_MDIFF = True
except ImportError:
    _HAS_MDIFF = False


# ── Token data model ───────────────────────────────────────────────────────────

@dataclass
class Token:
    kind: Literal["sentence", "citation"]
    text: str
    para_idx: int


# ── Segmentation ───────────────────────────────────────────────────────────────

_REF_PAT = re.compile(r'<ref[^>]*>.*?</ref>|<ref[^>]*/>', re.DOTALL)
_URL_PAT = re.compile(r'(?:url|href)\s*=\s*([^\s|}]+)', re.IGNORECASE)


def _tokenize_paragraph(para: str, para_idx: int) -> list[Token]:
    """Split one paragraph into interleaved sentence and citation Tokens."""
    spaced = re.sub(r'(?<! )<ref', ' <ref', para)
    tokens: list[Token] = []
    cursor = 0
    for m in _REF_PAT.finditer(spaced):
        prose_run = spaced[cursor:m.start()]
        if prose_run.strip() and _HAS_SPACY:
            for sent in _nlp(prose_run).sents:
                s = sent.text.strip()
                if s:
                    tokens.append(Token("sentence", s, para_idx))
        tokens.append(Token("citation", m.group(), para_idx))
        cursor = m.end()
    trailing = spaced[cursor:]
    if trailing.strip() and _HAS_SPACY:
        for sent in _nlp(trailing).sents:
            s = sent.text.strip()
            if s:
                tokens.append(Token("sentence", s, para_idx))
    return tokens


def tokenize_section(text: str) -> list[Token]:
    """Produce flat Token list from wikitext (all paragraphs)."""
    tokens: list[Token] = []
    for i, para in enumerate(split_paragraphs(text)):
        tokens.extend(_tokenize_paragraph(para, i))
    return tokens


# ── Similarity ─────────────────────────────────────────────────────────────────

_MIN_SIMILARITY = 0.25
_MIN_CITATION_SIMILARITY = 0.50


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
    url_a, url_b = _extract_url(a.text), _extract_url(b.text)
    if url_a and url_b:
        return 1.0 if url_a == url_b else _lexical_sim(a.text, b.text)
    return _lexical_sim(a.text, b.text)


def _threshold(kind: str) -> float:
    return _MIN_CITATION_SIMILARITY if kind == "citation" else _MIN_SIMILARITY


# ── Heckel alignment pipeline ──────────────────────────────────────────────────

def heckel_diff_ops(original: str, revised: str) -> list[tuple]:
    """
    Return aligned op list: (tag, old_token|None, new_token|None).
    Tags: equal, replace, delete, insert, move, moved.
    Falls back to empty list if mdiff or spacy are unavailable.
    """
    if not _HAS_MDIFF or not _HAS_SPACY:
        return []

    orig_tokens = tokenize_section(original)
    rev_tokens = tokenize_section(revised)
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


_THEME_STYLE = """
<style>
.diff-root {
  --diff-bg-equal:   #f8fafc; --diff-fg-equal:   #0f172a;
  --diff-bg-insert:  #f5fff5; --diff-fg-insert:  #14532d;
  --diff-bg-delete:  #fff5f5; --diff-fg-delete:  #7f1d1d;
  --diff-bg-replace: #f8fafc; --diff-fg-replace: #0f172a;
  --diff-bg-move:    #eff6ff; --diff-fg-move:    #1e3a5f;
  --diff-meta:       #94a3b8;
  --diff-border:     #e2e8f0;
  --diff-cite-label: #64748b;
  --word-del-bg:     #ffd7d5;
  --word-ins-bg:     #d4edda;
}
.diff-root.dark {
  --diff-bg-equal:   #1e2430; --diff-fg-equal:   #cbd5e1;
  --diff-bg-insert:  #0d2318; --diff-fg-insert:  #86efac;
  --diff-bg-delete:  #2d1414; --diff-fg-delete:  #fca5a5;
  --diff-bg-replace: #1e2430; --diff-fg-replace: #cbd5e1;
  --diff-bg-move:    #0f1d35; --diff-fg-move:    #93c5fd;
  --diff-meta:       #64748b;
  --diff-border:     #334155;
  --diff-cite-label: #94a3b8;
  --word-del-bg:     #5c1f1f;
  --word-ins-bg:     #1a3d24;
}
</style>
<script>
(function apply(attempt) {
  function getLum(el) {
    if (!el) return null;
    var s = window.getComputedStyle(el);
    var bg = s.backgroundColor;
    // Skip transparent (alpha == 0)
    if (bg === 'transparent' || bg === 'rgba(0, 0, 0, 0)') return null;
    var m = bg.match(/\\d+/g);
    if (!m || m.length < 3) return null;
    // If alpha channel present and zero, skip
    if (m.length >= 4 && +m[3] === 0) return null;
    return 0.299 * +m[0] + 0.587 * +m[1] + 0.114 * +m[2];
  }
  var selectors = [
    '[data-testid="stAppViewContainer"]',
    '[data-testid="stApp"]',
    '[data-testid="stMainBlockContainer"]',
    '.main',
    'body'
  ];
  var lum = null;
  for (var i = 0; i < selectors.length; i++) {
    lum = getLum(document.querySelector(selectors[i]));
    if (lum !== null) break;
  }
  if (lum === null && attempt < 5) {
    setTimeout(function() { apply(attempt + 1); }, 100);
    return;
  }
  var isDark = lum !== null && lum < 128;
  document.querySelectorAll('.diff-root').forEach(function(el) {
    el.classList.toggle('dark', isDark);
  });
})(0);
</script>
"""


def paragraph_diff_html(old_para: str, new_para: str) -> str:
    """
    Render one paragraph pair as HTML: original on top, revised below.
    Word-level highlights: red strikethrough for deletions, green for insertions.
    """
    if not old_para:
        escaped = html.escape(new_para)
        return (
            "<div style='margin-bottom:14px;font-size:14px;line-height:1.7'>"
            f"<div style='background:var(--diff-bg-insert);color:var(--diff-fg-insert);"
            f"padding:10px 14px;border-left:4px solid #66bb6a'>{escaped}</div>"
            "</div>"
        )
    if not new_para:
        escaped = html.escape(old_para)
        return (
            "<div style='margin-bottom:14px;font-size:14px;line-height:1.7'>"
            f"<div style='background:var(--diff-bg-delete);color:var(--diff-fg-delete);"
            f"padding:10px 14px;border-left:4px solid #e57373;"
            f"text-decoration:line-through'>{escaped}</div>"
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
                f"<span style='background:var(--word-del-bg);text-decoration:line-through;"
                f"border-radius:2px;padding:0 2px'>{escaped}</span>"
            )
        elif tag == "insert":
            new_parts.append(
                f"<span style='background:var(--word-ins-bg);border-radius:2px;"
                f"padding:0 2px'>{escaped}</span>"
            )

    old_html = " ".join(old_parts)
    new_html = " ".join(new_parts)
    return (
        "<div style='margin-bottom:14px;font-size:14px;line-height:1.7'>"
        f"<div style='background:var(--diff-bg-delete);color:var(--diff-fg-equal);"
        f"padding:10px 14px;border-left:4px solid #e57373;margin-bottom:3px'>{old_html}</div>"
        f"<div style='background:var(--diff-bg-insert);color:var(--diff-fg-equal);"
        f"padding:10px 14px;border-left:4px solid #66bb6a'>{new_html}</div>"
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

    def _wrap(body: str) -> str:
        return _THEME_STYLE + f"<div class='diff-root'>{body}</div>"

    if not orig_paras:
        return _wrap("".join(paragraph_diff_html("", p) for p in rev_paras))
    if not rev_paras:
        return _wrap("".join(paragraph_diff_html(p, "") for p in orig_paras))

    matcher = difflib.SequenceMatcher(None, orig_paras, rev_paras, autojunk=False)
    blocks = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for p in orig_paras[i1:i2]:
                escaped = html.escape(p)
                blocks.append(
                    "<div style='margin-bottom:14px;font-size:14px;line-height:1.7;"
                    f"padding:10px 14px;background:var(--diff-bg-replace);"
                    f"color:var(--diff-fg-equal);border-left:4px solid var(--diff-border)'>"
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
    return _wrap("\n".join(blocks))


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
