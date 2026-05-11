# ABOUTME: Diff algorithm comparison harness — renders side-by-side HTML for visual evaluation.
# ABOUTME: Compares paragraph-level SequenceMatcher vs sentence-level Heckel with citation support.

import html
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import openai
from dotenv import load_dotenv

load_dotenv()

from diff_utils import heckel_diff_ops
from tools.diff import _render_html, _word_diff_inline


def _render_mode_b(ops):
    """Raw wikitext render for Mode B column."""
    blocks: list[str] = []
    last_para = -1

    def maybe_para(np):
        nonlocal last_para
        if np >= 0 and np != last_para:
            blocks.append(
                f"<div style='font-size:11px;color:#94a3b8;margin:10px 0 4px;"
                f"text-transform:uppercase;letter-spacing:.06em'>"
                f"¶ paragraph {np + 1}</div>"
            )
            last_para = np

    _SENT_BASE = (
        "margin-bottom:6px;font-size:14px;line-height:1.7;"
        "padding:8px 14px;border-radius:0 4px 4px 0"
    )

    def sent_div(body, bg, border, extra=""):
        style = f"{_SENT_BASE};background:{bg};border-left:4px solid {border};{extra}"
        return f"<div style='{style}'>{body}</div>"

    def cite_block(text, bg, border, extra=""):
        escaped = html.escape(text)
        return (
            f"<code style='display:block;margin:2px 0 6px;font-size:11px;"
            f"white-space:pre-wrap;word-break:break-all;"
            f"background:{bg};border-left:3px solid {border};"
            f"padding:4px 8px;border-radius:0 3px 3px 0;{extra}'>"
            f"{escaped}</code>"
        )

    for entry in ops:
        tag, old_tok, new_tok = entry
        display = new_tok if new_tok else old_tok
        np = display.para_idx
        maybe_para(np if np >= 0 else last_para)

        if display.kind == "sentence":
            if tag == "equal":
                blocks.append(sent_div(html.escape(display.text), "#fafafa", "#ccc", "color:#555"))
            elif tag == "replace":
                blocks.append(sent_div(_word_diff_inline(old_tok.text, new_tok.text),
                                       "#f8fafc", "#94a3b8"))
            elif tag == "insert":
                blocks.append(sent_div(html.escape(display.text), "#f5fff5", "#66bb6a"))
            elif tag == "delete":
                blocks.append(sent_div(html.escape(display.text), "#fff5f5", "#e57373",
                                       "text-decoration:line-through;color:#888"))
            elif tag in ("move", "moved"):
                label = (
                    "<span style='font-size:11px;font-weight:600;color:#1d4ed8;"
                    "text-transform:uppercase;letter-spacing:.05em'>↕ moved</span> "
                )
                blocks.append(sent_div(label + html.escape(display.text), "#eff6ff", "#3b82f6"))
        else:
            if tag == "equal":
                blocks.append(cite_block(display.text, "#f8fafc", "#94a3b8"))
            elif tag == "replace":
                diff_body = _word_diff_inline(old_tok.text, new_tok.text)
                blocks.append(
                    f"<code style='display:block;margin:2px 0 6px;font-size:11px;"
                    f"white-space:pre-wrap;word-break:break-all;"
                    f"background:#fffbeb;border-left:3px solid #f59e0b;"
                    f"padding:4px 8px;border-radius:0 3px 3px 0'>{diff_body}</code>"
                )
            elif tag == "insert":
                blocks.append(cite_block(display.text, "#f5fff5", "#66bb6a"))
            elif tag == "delete":
                blocks.append(cite_block(display.text, "#fff5f5", "#e57373",
                                         "text-decoration:line-through;color:#888"))
            elif tag in ("move", "moved"):
                blocks.append(cite_block(display.text, "#eff6ff", "#3b82f6"))

    return "\n".join(blocks)


# ── Algorithm A: current (paragraph-level SequenceMatcher) ───────────────────

def diff_current(original: str, revised: str) -> str:
    from diff_utils import section_diff_html
    return section_diff_html(original, revised)


# ── Algorithm B: sentence-level Heckel (Mode A + Mode B) ─────────────────────

def diff_heckel(original: str, revised: str) -> tuple[str, str]:
    """Return (mode_a_html, mode_b_html)."""
    ops = heckel_diff_ops(original, revised)
    if not ops:
        err = "<p><em>mdiff/spacy not available</em></p>"
        return err, err
    return _render_html(ops), _render_mode_b(ops)


# ── Algorithm C: LLM interpretation layer ─────────────────────────────────────

def _extract_ops_for_llm(original: str, revised: str) -> dict:
    ops_raw = heckel_diff_ops(original, revised)
    result = {"deleted": [], "inserted": [], "replaced": [], "moved": [], "unchanged": []}
    for tag, old_tok, new_tok in ops_raw:
        display = new_tok if new_tok else old_tok
        if tag == "equal":
            result["unchanged"].append(display.text)
        elif tag == "replace":
            result["replaced"].append({"from": old_tok.text, "to": new_tok.text})
        elif tag == "insert":
            result["inserted"].append(display.text)
        elif tag == "delete":
            result["deleted"].append(display.text)
        elif tag in ("move", "moved"):
            result["moved"].append(display.text)
    return result


_LLM_PROMPT = """\
You are a diff renderer for Wikipedia article edits. You will be given a \
structured diff — deleted sentences, inserted sentences, replaced sentences \
(with before/after), moved sentences, and unchanged sentences.

Your job is to render the FULL revised text as a visual diff that a human \
reviewer can read. Show every sentence — unchanged ones in plain text, \
changed ones highlighted.

Rendering rules (HTML only, no markdown):
- Unchanged sentence: plain text, no markup
- Deleted sentence (no replacement): wrap in \
<span style="background:#ffd7d5;text-decoration:line-through;padding:1px 3px;\
border-radius:2px">...</span>
- Inserted sentence (no original): wrap in \
<span style="background:#d4edda;padding:1px 3px;border-radius:2px">...</span>
- Replaced sentence: show the OLD version struck-through then NEW version highlighted
- Moved sentence: wrap in \
<span style="background:#fef3c7;padding:1px 3px;border-radius:2px">↕ ...</span>
- Separate paragraphs with <p> tags
- Do NOT add any prose explanation — only the rendered diff text
- Do NOT invent any text not present in the structured diff

Structured diff:
{ops_json}
"""


def diff_llm(original: str, revised: str) -> str:
    ops = _extract_ops_for_llm(original, revised)
    if not any(ops[k] for k in ("deleted", "inserted", "replaced", "moved")):
        return "<p><em>(no changes)</em></p>"
    ops_for_llm = {k: v for k, v in ops.items() if k != "unchanged"}
    client = openai.OpenAI()
    response = client.chat.completions.create(
        model=os.getenv("DRAFT_MODEL", "gpt-4o"),
        messages=[{"role": "user", "content": _LLM_PROMPT.format(
            ops_json=json.dumps(ops_for_llm, indent=2)
        )}],
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
  <div class="legend-item"><div class="swatch" style="background:#fafafa;border:1px solid #ccc">
  </div> unchanged</div>
  <div class="legend-item"><div class="swatch" style="background:#fff5f5;border-left:3px solid #e57373">
  </div> deleted</div>
  <div class="legend-item"><div class="swatch" style="background:#f5fff5;border-left:3px solid #66bb6a">
  </div> inserted</div>
  <div class="legend-item"><div class="swatch" style="background:#fffbeb;border-left:3px solid #f59e0b">
  </div> modified citation</div>
  <div class="legend-item"><div class="swatch" style="background:#eff6ff;border-left:3px solid #3b82f6">
  </div> moved</div>
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
                "Grafana's backend is written in Go."
                "<ref>{{cite web|url=https://github.com/grafana/grafana|"
                "title=Grafana repository|access-date=2025-01-01}}</ref> "
                "The frontend uses TypeScript and React."
                "<ref>{{cite web|url=https://grafana.com/docs/|"
                "title=Grafana docs|access-date=2025-01-01}}</ref>"
            ),
            "revised": (
                "Grafana's backend is written in Go."
                "<ref>{{cite web|url=https://github.com/grafana/grafana|"
                "title=Grafana repository|access-date=2026-05-09}}</ref> "
                "The frontend uses TypeScript and React."
                "<ref>{{cite web|url=https://grafana.com/docs/grafana/latest/|"
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
