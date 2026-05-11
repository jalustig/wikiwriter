# Two-Pass Assessment + Article Grader Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix article grader section truncation and add two-pass ASSESS⟲FOCUS architecture so large articles get editorial decisions grounded in actual section text.

**Architecture:** The article grader is fixed first (section-by-section prompt building). Then `assess_article` gains an `article_text` argument (always populated — truncated snippets on Pass 1, full candidate text on Pass 2) plus an optional `focus_context` for the second pass. The orchestrator wraps these in an ASSESS⟲FOCUS loop gated on `article_class`. DAG visualization and constants get a FOCUS node and a back-edge.

**Tech Stack:** Python 3.12, Pydantic v2, OpenAI async client, Pillow (PIL) for DAG image, pytest

---

## File Map

| File | Change |
|---|---|
| `workers/article_grader.py` | Replace `wikitext[:12000]` slice with section-by-section assembly |
| `tests/test_article_grader.py` | Update existing tests; add section-coverage test |
| `models.py` | Add `needs_focus: bool = False` to `ArticleAssessment` |
| `workers/assess_article.py` | Add `article_text` to prompt; add `focus_context` param; adjust cap logic |
| `prompts/assess_article.txt` | Add `{article_text}` and optional `{focus_context}` blocks |
| `tests/test_assess_article.py` | Add tests for `_build_article_text`, `needs_focus` field, focused-pass cap behaviour |
| `orchestrator.py` | ASSESS→FOCUS→ASSESS loop; FOCUS stage events |
| `constants.py` | Add FOCUS to `STAGE_META` |
| `utils/dag.py` | Add FOCUS node, three-state progressive reveal, FOCUS→ASSESS back-edge |
| `tests/test_dag_image.py` | Add smoke tests for three-state progressive reveal |

---

## Task 1: Fix article grader — section-by-section prompt building

**Files:**
- Modify: `workers/article_grader.py`
- Modify: `tests/test_article_grader.py`

### Background

`_build_grader_prompt` currently takes a raw `wikitext` string and slices it to 12,000 chars. This means only the first ~4 sections ever get scores. We need to build `sections_text` from `article.section_texts` section-by-section, capping each at 2,000 chars, so every section gets included.

The existing tests call `_build_grader_prompt("title", wikitext_string)`. We need to change the signature to accept an `article` object instead and update those tests.

- [ ] **Step 1: Write failing tests**

In `tests/test_article_grader.py`, add these tests (keep all existing tests — update their call sites):

```python
def test_all_sections_appear_in_prompt():
    """Every section in the article should appear in the grader prompt."""
    sections = ["Lead", "History", "Geography", "Economy", "Culture", "Demographics"]
    section_texts = {s: f"Content of {s} section." * 20 for s in sections}
    article = _make_article(
        wikitext="dummy",
        section_texts=section_texts,
    )
    article.sections = sections
    prompt = _build_grader_prompt(article)
    for name in sections:
        assert name in prompt, f"Section '{name}' missing from grader prompt"


def test_per_section_text_is_truncated():
    """Each section contributes at most 2000 chars to avoid any one section dominating."""
    long_text = "x" * 5000
    article = _make_article(
        wikitext="dummy",
        section_texts={"Lead": long_text},
    )
    article.sections = ["Lead"]
    prompt = _build_grader_prompt(article)
    # The 5000-char section should be capped — prompt should not contain 5000 x's in a row
    assert "x" * 2001 not in prompt


def test_prompt_includes_article_title_v2():
    article = _make_article(wikitext="dummy", section_texts={"Lead": "Some content."})
    article.sections = ["Lead"]
    prompt = _build_grader_prompt(article)
    assert "Test Article" in prompt
```

Also update the three existing tests to use the new signature. Replace:
```python
def test_prompt_includes_ref_tags_from_wikitext():
    wikitext = (
        "The sky is blue.<ref>{{cite book|title=Skies|author=A. Smith}}</ref>\n"
        "==History==\nSome history here.<ref name=\"foo\">Source</ref>\n"
    )
    article = _make_article(wikitext=wikitext)
    prompt = _build_grader_prompt("Test Article", wikitext)
    assert "<ref>" in prompt or '<ref name="foo">' in prompt


def test_prompt_includes_cite_templates():
    wikitext = "Claim.<ref>{{cite web|url=http://example.com|title=Example}}</ref>"
    prompt = _build_grader_prompt("Test Article", wikitext)
    assert "cite web" in prompt


def test_prompt_includes_article_title():
    prompt = _build_grader_prompt("Service star", "Some content")
    assert "Service star" in prompt
```

With:
```python
def test_prompt_includes_ref_tags_from_wikitext():
    wikitext = (
        "The sky is blue.<ref>{{cite book|title=Skies|author=A. Smith}}</ref>\n"
        "==History==\nSome history here.<ref name=\"foo\">Source</ref>\n"
    )
    article = _make_article(
        wikitext=wikitext,
        section_texts={"Lead": wikitext},
    )
    article.sections = ["Lead"]
    prompt = _build_grader_prompt(article)
    assert "<ref>" in prompt or '<ref name="foo">' in prompt


def test_prompt_includes_cite_templates():
    wikitext = "Claim.<ref>{{cite web|url=http://example.com|title=Example}}</ref>"
    article = _make_article(
        wikitext=wikitext,
        section_texts={"Lead": wikitext},
    )
    article.sections = ["Lead"]
    prompt = _build_grader_prompt(article)
    assert "cite web" in prompt


def test_prompt_includes_article_title():
    article = _make_article(
        wikitext="Some content",
        section_texts={"Lead": "Some content"},
    )
    article.sections = ["Lead"]
    article.title = "Service star"
    prompt = _build_grader_prompt(article)
    assert "Service star" in prompt
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/jason/code/wikiwriter && python -m pytest tests/test_article_grader.py -v 2>&1 | tail -20
```

Expected: failures on the new tests; old tests may fail due to signature change.

- [ ] **Step 3: Implement the new `_build_grader_prompt`**

In `workers/article_grader.py`, change:

```python
_WIKITEXT_LIMIT = 12000


def _build_grader_prompt(article_title: str, wikitext: str) -> str:
    return _PROMPT_TEMPLATE.format(
        article_title=article_title,
        sections_text=wikitext[:_WIKITEXT_LIMIT],
    )
```

To:

```python
_SECTION_CHAR_LIMIT = 2000


def _build_grader_prompt(article: "WikiArticle") -> str:
    parts = []
    for name in article.sections:
        text = article.section_texts.get(name, "")[:_SECTION_CHAR_LIMIT]
        if text.strip():
            parts.append(f"== {name} ==\n{text}" if name != "Lead" else text)
    sections_text = "\n\n".join(parts)
    return _PROMPT_TEMPLATE.format(
        article_title=article.title,
        sections_text=sections_text,
    )
```

Also update the `run` method's call site — change:

```python
        prompt = _build_grader_prompt(article.title, article.wikitext)
```

To:

```python
        prompt = _build_grader_prompt(article)
```

- [ ] **Step 4: Run all grader tests**

```bash
cd /Users/jason/code/wikiwriter && python -m pytest tests/test_article_grader.py -v 2>&1 | tail -20
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
cd /Users/jason/code/wikiwriter && python -m pytest --tb=short -q 2>&1 | tail -20
```

Expected: all tests pass (or same failures as before this task).

- [ ] **Step 6: Lint**

```bash
cd /Users/jason/code/wikiwriter && flake8 workers/article_grader.py tests/test_article_grader.py
```

Expected: no output.

- [ ] **Step 7: Commit**

```bash
cd /Users/jason/code/wikiwriter && git add workers/article_grader.py tests/test_article_grader.py && git commit -m "fix: grade all sections — section-by-section prompt assembly in article_grader"
```

---

## Task 2: Add `needs_focus` field to `ArticleAssessment`

**Files:**
- Modify: `models.py`
- Modify: `tests/test_assess_article.py`

### Background

`ArticleAssessment` needs a `needs_focus: bool = False` field. When `True`, the orchestrator knows to run a FOCUS pass before making the final section selection. Defaults to `False` so all existing code is unaffected.

- [ ] **Step 1: Write failing test**

Add to `tests/test_assess_article.py`:

```python
# ── needs_focus field ───────────────────────────────────────────────────────

def test_needs_focus_defaults_false():
    result = _build_assessment(_raw_normal(), flip_flopped=set())
    assert result.needs_focus is False


def test_needs_focus_propagates_true():
    raw = _raw_normal()
    raw["needs_focus"] = True
    raw["article_class"] = "COMPLETE"
    result = _build_assessment(raw, flip_flopped=set())
    assert result.needs_focus is True
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/jason/code/wikiwriter && python -m pytest tests/test_assess_article.py::test_needs_focus_defaults_false tests/test_assess_article.py::test_needs_focus_propagates_true -v 2>&1 | tail -10
```

Expected: `AttributeError` or similar — field doesn't exist yet.

- [ ] **Step 3: Add the field to `ArticleAssessment`**

In `models.py`, in the `ArticleAssessment` class, add after `scope_of_work`:

```python
    needs_focus: bool = False             # True when orchestrator should run a FOCUS pass
```

Also update `_build_assessment` in `workers/assess_article.py` to pass the field through from the LLM response. In `_build_assessment`, add to the `ArticleAssessment(...)` constructor call:

```python
        needs_focus=bool(raw.get("needs_focus", False)),
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/jason/code/wikiwriter && python -m pytest tests/test_assess_article.py -v 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 5: Lint**

```bash
cd /Users/jason/code/wikiwriter && flake8 models.py workers/assess_article.py tests/test_assess_article.py
```

Expected: no output.

- [ ] **Step 6: Commit**

```bash
cd /Users/jason/code/wikiwriter && git add models.py workers/assess_article.py tests/test_assess_article.py && git commit -m "feat: add needs_focus field to ArticleAssessment"
```

---

## Task 3: Add article text to `assess_article` Pass 1

**Files:**
- Modify: `workers/assess_article.py`
- Modify: `prompts/assess_article.txt`
- Modify: `tests/test_assess_article.py`

### Background

`assess_article` currently sends section names and scores but no prose. We add a `_build_article_text` helper that assembles truncated section snippets (~400 chars each, total cap ~6000 chars), and pass the result to the prompt as `{article_text}`. This is always present — Pass 1 gets snippets, Pass 2 (next task) gets full candidate text.

The prompt currently has no `{article_text}` placeholder; we add it in the "Article Summary" section.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_assess_article.py`:

```python
from workers.assess_article import _build_article_text
from models import WikiArticle


def _make_wiki_article(sections, section_texts):
    return WikiArticle(
        title="Test",
        url="https://en.wikipedia.org/wiki/Test",
        wikitext="",
        sections=sections,
        section_texts=section_texts,
        citations=[],
        assessment_class=None,
    )


# ── _build_article_text ─────────────────────────────────────────────────────

def test_build_article_text_includes_all_sections():
    sections = ["Lead", "History", "Geography"]
    texts = {s: f"Text of {s}." for s in sections}
    article = _make_wiki_article(sections, texts)
    result = _build_article_text(article)
    assert "Lead" in result
    assert "History" in result
    assert "Geography" in result


def test_build_article_text_truncates_long_sections():
    article = _make_wiki_article(["Lead"], {"Lead": "x" * 1000})
    result = _build_article_text(article, per_section_limit=400)
    assert "x" * 401 not in result


def test_build_article_text_respects_total_cap():
    sections = [f"S{i}" for i in range(30)]
    texts = {s: "word " * 200 for s in sections}
    article = _make_wiki_article(sections, texts)
    result = _build_article_text(article)
    assert len(result) <= 6500  # total cap is 6000 with a small buffer for headers
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/jason/code/wikiwriter && python -m pytest tests/test_assess_article.py::test_build_article_text_includes_all_sections tests/test_assess_article.py::test_build_article_text_truncates_long_sections tests/test_assess_article.py::test_build_article_text_respects_total_cap -v 2>&1 | tail -10
```

Expected: `ImportError` — `_build_article_text` doesn't exist yet.

- [ ] **Step 3: Implement `_build_article_text`**

Add to `workers/assess_article.py` (after the imports, before `_source_quality_summary`):

```python
_PER_SECTION_LIMIT = 400
_TOTAL_TEXT_LIMIT = 6000


def _build_article_text(
    article: "WikiArticle",
    per_section_limit: int = _PER_SECTION_LIMIT,
    candidate_sections: list[str] | None = None,
    candidate_full_limit: int = 3000,
) -> str:
    """Build article text for the assess prompt.

    For Pass 1 (candidate_sections=None): first per_section_limit chars of each section.
    For Pass 2 (candidate_sections provided): full text (up to candidate_full_limit) for
    candidates, truncated snippets for all others.
    """
    parts = []
    total = 0
    for name in article.sections:
        text = article.section_texts.get(name, "")
        if not text.strip():
            continue
        if candidate_sections is not None and name in candidate_sections:
            snippet = text[:candidate_full_limit]
        else:
            snippet = text[:per_section_limit]
        if total + len(snippet) > _TOTAL_TEXT_LIMIT:
            remaining = _TOTAL_TEXT_LIMIT - total
            if remaining <= 0:
                break
            snippet = snippet[:remaining]
        header = f"== {name} ==" if name != "Lead" else ""
        parts.append(f"{header}\n{snippet}".strip() if header else snippet)
        total += len(snippet)
    return "\n\n".join(parts)
```

- [ ] **Step 4: Add `{article_text}` to the prompt**

In `prompts/assess_article.txt`, add after the `### Article Summary` block (after the `Scope:` line):

```
### Article Text (excerpts)
{article_text}
```

The full addition in context — replace:

```
### Article Summary
Topic: {article_topic}
Scope: {article_scope}

### Current Quality
```

With:

```
### Article Summary
Topic: {article_topic}
Scope: {article_scope}

### Article Text (excerpts)
{article_text}

### Current Quality
```

- [ ] **Step 5: Wire up `_build_article_text` in `assess_article`**

In `workers/assess_article.py`, in the `assess_article` function, add just before the `prompt = _PROMPT.format(...)` call:

```python
    article_text = _build_article_text(article)
```

Then add `article_text=article_text,` to the `_PROMPT.format(...)` call:

```python
    prompt = _PROMPT.format(
        article_title=article.title,
        article_topic=summary.topic,
        article_scope=summary.scope,
        article_text=article_text,
        letter_grade=grade.letter_grade,
        overall_score=grade.overall_score,
        assessment_class=article.assessment_class or "unrated",
        dimension_scores=dimension_scores,
        section_scores=section_scores,
        grade_narrative=grade.narrative,
        caution_level=environment.caution_level,
        flip_flopped_sections=flip,
        editor_norms=editor_norms,
        policies_and_restrictions=policies,
        active_disputes=disputes,
        environment_narrative=environment.environment_narrative,
        source_quality_summary=_source_quality_summary(source_evals),
    )
```

- [ ] **Step 6: Run all assess_article tests**

```bash
cd /Users/jason/code/wikiwriter && python -m pytest tests/test_assess_article.py -v 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 7: Run full suite**

```bash
cd /Users/jason/code/wikiwriter && python -m pytest --tb=short -q 2>&1 | tail -20
```

Expected: all tests pass (or same failures as before this task).

- [ ] **Step 8: Lint**

```bash
cd /Users/jason/code/wikiwriter && flake8 workers/assess_article.py prompts/ tests/test_assess_article.py
```

Expected: no output (flake8 skips .txt files).

- [ ] **Step 9: Commit**

```bash
cd /Users/jason/code/wikiwriter && git add workers/assess_article.py prompts/assess_article.txt tests/test_assess_article.py && git commit -m "feat: pass article text to assess_article prompt"
```

---

## Task 4: Add `focus_context` pass and `needs_focus` gating to `assess_article`

**Files:**
- Modify: `workers/assess_article.py`
- Modify: `prompts/assess_article.txt`
- Modify: `tests/test_assess_article.py`

### Background

When `assess_article` is called for Pass 2, it receives `focus_context` — a dict with `candidate_sections` (list of section names). In this case, `_build_article_text` is called with those names so the LLM gets full text for candidates. The prompt gets a `{focus_context_block}` that either includes a directive about the focused sections or is empty. The section cap (`_enforce_section_cap`) is only applied when this is a final decision (i.e., `focus_context is None` OR `article_class` in STUB/DEVELOPING).

- [ ] **Step 1: Write failing tests**

Add to `tests/test_assess_article.py`:

```python
# ── focused pass: needs_focus and cap behaviour ─────────────────────────────

def test_cap_not_applied_when_needs_focus_true():
    """Pass 1 for COMPLETE article: LLM returns needs_focus=True, cap should NOT be enforced."""
    raw = _raw_normal()
    raw["article_class"] = "COMPLETE"
    raw["needs_focus"] = True
    raw["sections"] = [
        {"name": f"S{i}", "action": "EDIT", "edit_type": "EXPAND", "rationale": "thin"}
        for i in range(5)
    ]
    result = _build_assessment(raw, flip_flopped=set(), is_final=False)
    edits = [s for s in result.sections if s.action == "EDIT"]
    assert len(edits) == 5  # cap not enforced on non-final pass


def test_cap_applied_when_is_final():
    """Final pass always enforces the cap."""
    raw = _raw_normal()
    raw["article_class"] = "COMPLETE"
    raw["needs_focus"] = False
    raw["sections"] = [
        {"name": f"S{i}", "action": "EDIT", "edit_type": "EXPAND", "rationale": "thin"}
        for i in range(5)
    ]
    result = _build_assessment(raw, flip_flopped=set(), is_final=True)
    edits = [s for s in result.sections if s.action == "EDIT"]
    assert len(edits) <= 3
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/jason/code/wikiwriter && python -m pytest tests/test_assess_article.py::test_cap_not_applied_when_needs_focus_true tests/test_assess_article.py::test_cap_applied_when_is_final -v 2>&1 | tail -10
```

Expected: `TypeError` — `_build_assessment` doesn't accept `is_final`.

- [ ] **Step 3: Add `is_final` param to `_build_assessment` and update cap logic**

In `workers/assess_article.py`, change `_build_assessment` signature from:

```python
def _build_assessment(raw: dict, flip_flopped: set) -> ArticleAssessment:
```

To:

```python
def _build_assessment(raw: dict, flip_flopped: set, is_final: bool = True) -> ArticleAssessment:
```

Inside `_build_assessment`, change the cap logic. Find:

```python
    else:
        sections = _parse_sections(raw.get("sections", []), flip_flopped)
        sections = _enforce_section_cap(sections)
```

Replace with:

```python
    else:
        sections = _parse_sections(raw.get("sections", []), flip_flopped)
        if is_final:
            sections = _enforce_section_cap(sections)
```

Also add `needs_focus=bool(raw.get("needs_focus", False)),` to the `ArticleAssessment(...)` constructor if not already present (it should be from Task 2).

- [ ] **Step 4: Add `focus_context` param to `assess_article` function**

In `workers/assess_article.py`, change `assess_article` signature from:

```python
async def assess_article(
    article: WikiArticle,
    summary: ArticleSummary,
    grade: ContentGrade,
    environment: EditorialEnvironment,
    source_evals: list[SourceEvaluation],
) -> ArticleAssessment:
```

To:

```python
async def assess_article(
    article: WikiArticle,
    summary: ArticleSummary,
    grade: ContentGrade,
    environment: EditorialEnvironment,
    source_evals: list[SourceEvaluation],
    focus_context: dict | None = None,
) -> ArticleAssessment:
```

- [ ] **Step 5: Update cache key and `_build_article_text` call for focused pass**

In `assess_article`, update the cache key and article text build to be focus-aware:

Replace the existing cache key setup:

```python
    key = cache_key(
        "assess_article",
        article.url,
        grade.overall_score,
        environment.caution_level,
    )
```

With:

```python
    if focus_context:
        candidate_names = sorted(focus_context.get("candidate_sections", []))
        key = cache_key(
            "assess_article_focused",
            article.url,
            grade.overall_score,
            environment.caution_level,
            *candidate_names,
        )
    else:
        key = cache_key(
            "assess_article",
            article.url,
            grade.overall_score,
            environment.caution_level,
        )
```

Update the `_build_article_text` call:

```python
    if focus_context:
        article_text = _build_article_text(
            article,
            candidate_sections=focus_context.get("candidate_sections", []),
        )
    else:
        article_text = _build_article_text(article)
```

- [ ] **Step 6: Add `{focus_context_block}` to the prompt and pass it**

In `prompts/assess_article.txt`, add after the `### Article Text (excerpts)` block:

Replace:

```
### Article Text (excerpts)
{article_text}

### Current Quality
```

With:

```
### Article Text (excerpts)
{article_text}
{focus_context_block}
### Current Quality
```

In `workers/assess_article.py`, build the focus block and add to `_PROMPT.format(...)`:

```python
    if focus_context:
        candidate_names = focus_context.get("candidate_sections", [])
        focus_context_block = (
            "\n### Focus Instruction\n"
            "You are now making a FINAL section selection. Full text has been provided above "
            f"for these candidate sections: {', '.join(candidate_names)}.\n"
            "Choose at most 3 of these for EDIT. Do NOT set needs_focus=true in your response.\n\n"
        )
    else:
        focus_context_block = ""
```

Add `focus_context_block=focus_context_block,` to `_PROMPT.format(...)`.

- [ ] **Step 7: Pass `is_final` to `_build_assessment`**

In the `assess_article` function, find the call to `_build_assessment`:

```python
    result = _build_assessment(raw, flip_set)
```

Replace with:

```python
    is_final = focus_context is not None or raw.get("article_class") in ("STUB", "DEVELOPING")
    result = _build_assessment(raw, flip_set, is_final=is_final)
```

- [ ] **Step 8: Run all assess_article tests**

```bash
cd /Users/jason/code/wikiwriter && python -m pytest tests/test_assess_article.py -v 2>&1 | tail -25
```

Expected: all tests pass.

- [ ] **Step 9: Run full suite**

```bash
cd /Users/jason/code/wikiwriter && python -m pytest --tb=short -q 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 10: Lint**

```bash
cd /Users/jason/code/wikiwriter && flake8 workers/assess_article.py prompts/ tests/test_assess_article.py
```

Expected: no output.

- [ ] **Step 11: Commit**

```bash
cd /Users/jason/code/wikiwriter && git add workers/assess_article.py prompts/assess_article.txt tests/test_assess_article.py && git commit -m "feat: add two-pass assess_article with focus_context and needs_focus gating"
```

---

## Task 5: Wire ASSESS⟲FOCUS loop in orchestrator

**Files:**
- Modify: `orchestrator.py`

### Background

After the first ASSESS call, if `assessment.needs_focus` is `True`, the orchestrator runs a FOCUS stage (building `focus_context` from candidate section names and texts) then calls `assess_article` again with `focus_context`. Both ASSESS runs emit their own `running`/`done` events; the FOCUS stage gets its own events too. No new tests needed here — the orchestrator is tested via integration tests and the existing smoke test.

- [ ] **Step 1: Add FOCUS import and update `assess_article` import**

In `orchestrator.py`, the `assess_article` import is already present. No new imports needed — we build `focus_context` inline.

- [ ] **Step 2: Replace the ASSESS block**

Find the ASSESS block in `orchestrator.py` (around line 305):

```python
        # ── ASSESS (WHAT) ────────────────────────────────────────────────────
        yield ProgressEvent(stage="ASSESS", status="running", message="Assessing what the article needs...")
        assessment = await assess_article(
            article, article_summary, content_grade, environment, source_evals
        )
        sections_to_edit = [s for s in assessment.sections if s.action == "EDIT"]
        assess_ctx = {
```

Replace the entire ASSESS block (from `# ── ASSESS` through the `return` after `not sections_to_edit`) with:

```python
        # ── ASSESS (WHAT) — may loop through FOCUS for large articles ─────────
        yield ProgressEvent(stage="ASSESS", status="running", message="Assessing what the article needs...")
        assessment = await assess_article(
            article, article_summary, content_grade, environment, source_evals
        )

        if assessment.needs_focus and not assessment.no_edit:
            candidate_names = [s.name for s in assessment.sections if s.action == "EDIT"]
            yield ProgressEvent(
                stage="ASSESS", status="done",
                message=f"Pass 1 complete — {len(candidate_names)} candidates identified, reading section text…",
                data={"assessment": assessment.model_dump()},
            )

            # ── FOCUS ────────────────────────────────────────────────────────
            yield ProgressEvent(
                stage="FOCUS", status="running",
                message=f"Reading {len(candidate_names)} candidate sections…",
            )
            focus_context = {"candidate_sections": candidate_names}
            yield ProgressEvent(
                stage="FOCUS", status="done",
                message=f"Section text loaded for: {', '.join(candidate_names)}",
            )

            # ── ASSESS Pass 2 ────────────────────────────────────────────────
            yield ProgressEvent(
                stage="ASSESS", status="running",
                message="Final section selection with full text context…",
            )
            assessment = await assess_article(
                article, article_summary, content_grade, environment, source_evals,
                focus_context=focus_context,
            )

        sections_to_edit = [s for s in assessment.sections if s.action == "EDIT"]
        assess_ctx = {
            "article_title": article.title,
            "importance": assessment.importance.tier,
            "article_class": assessment.article_class,
            "effort_ceiling": assessment.effort_ceiling,
            "edit_rationale": assessment.edit_rationale,
            "no_edit": assessment.no_edit,
            "no_edit_reason": assessment.no_edit_reason,
            "primary_weaknesses": assessment.primary_weaknesses,
            "source_trust_verdict": assessment.source_trust_verdict,
            "sections_to_edit": [
                {"name": s.name, "edit_type": s.edit_type, "rationale": s.rationale}
                for s in sections_to_edit
            ],
            "would_edit_sections": [
                {"name": s.name, "edit_type": s.edit_type, "rationale": s.rationale}
                for s in assessment.would_edit_sections
            ],
        }
        async for t in _narrate("assess", assess_ctx):
            yield t
        async for s in _emit_summary("assess", assess_ctx):
            yield s

        if assessment.no_edit:
            yield ProgressEvent(
                stage="ASSESS", status="done",
                message=f"No edit — {assessment.no_edit_reason}",
                data={"assessment": assessment.model_dump()},
            )
            return

        yield ProgressEvent(
            stage="ASSESS", status="done",
            message=f"{assessment.importance.tier} | {assessment.article_class} | "
                    f"{len(sections_to_edit)} sections to edit | {assessment.effort_ceiling} effort",
            data={"assessment": assessment.model_dump()},
        )

        if not sections_to_edit:
            yield ProgressEvent(
                stage="ASSESS", status="done",
                message="Assessment complete — no sections flagged for editing.",
                data={"assessment": assessment.model_dump()},
            )
            return
```

- [ ] **Step 3: Run smoke tests**

```bash
cd /Users/jason/code/wikiwriter && python -m pytest tests/test_ui_smoke.py tests/test_orchestrator_revision.py --tb=short -q 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 4: Run full suite**

```bash
cd /Users/jason/code/wikiwriter && python -m pytest --tb=short -q 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 5: Lint**

```bash
cd /Users/jason/code/wikiwriter && flake8 orchestrator.py
```

Expected: no output.

- [ ] **Step 6: Commit**

```bash
cd /Users/jason/code/wikiwriter && git add orchestrator.py && git commit -m "feat: ASSESS⟲FOCUS loop in orchestrator for large articles"
```

---

## Task 6: Add FOCUS to `constants.py` and `utils/dag.py`

**Files:**
- Modify: `constants.py`
- Modify: `utils/dag.py`
- Modify: `tests/test_dag_image.py`

### Background

The DAG visualization needs three states:
1. ASSESS not done → `_INITIAL_ROWS` (FETCH + GATHER + ???)
2. ASSESS done, PLAN not done → `_ASSESS_FOCUS_ROWS` (FETCH + GATHER + ASSESS + FOCUS + ???)
3. PLAN done → `_PIPELINE_ROWS` (full pipeline)

A FOCUS→ASSESS back-edge (left side, amber) mirrors the existing CRITIQUE→PLAN back-edge (right side, red).

- [ ] **Step 1: Write failing tests**

Check what's in `tests/test_dag_image.py` first:

```bash
cat -n /Users/jason/code/wikiwriter/tests/test_dag_image.py
```

Add tests for the three-state logic and FOCUS node. Add to `tests/test_dag_image.py`:

```python
from utils.dag import render_agent_loop


def test_initial_state_shows_question_marks():
    """Before ASSESS completes, DAG shows ??? not PLAN."""
    img_bytes = render_agent_loop([], current_stage="FETCH", done_stages=set(), loop_count=0)
    assert isinstance(img_bytes, bytes) and len(img_bytes) > 100


def test_assess_done_shows_focus_row():
    """After ASSESS done but before PLAN, DAG shows FOCUS node."""
    img_bytes = render_agent_loop(
        [], current_stage="FOCUS", done_stages={"ASSESS"}, loop_count=0
    )
    assert isinstance(img_bytes, bytes) and len(img_bytes) > 100


def test_plan_done_shows_full_pipeline():
    """After PLAN done, full pipeline rows are shown."""
    img_bytes = render_agent_loop(
        [], current_stage="EXEC", done_stages={"ASSESS", "FOCUS", "PLAN"}, loop_count=0
    )
    assert isinstance(img_bytes, bytes) and len(img_bytes) > 100
```

- [ ] **Step 2: Run tests to confirm they fail (or check current state)**

```bash
cd /Users/jason/code/wikiwriter && python -m pytest tests/test_dag_image.py -v 2>&1 | tail -20
```

Note which tests exist and which fail — the three new tests should import-error if functions changed.

- [ ] **Step 3: Add FOCUS to `constants.py`**

In `constants.py`, add to `STAGE_META`:

```python
    "FOCUS":    ("🔎", "Reading candidate sections…", "Sections read"),
```

Add it after the `"ASSESS"` entry:

```python
    "ASSESS":    ("🧠", "Choosing editorial approach…", "Approach decided"),
    "FOCUS":     ("🔎", "Reading candidate sections…",  "Sections read"),
    "PLAN":      ("🗺️",  "Planning tasks…",             "Task plan ready"),
```

- [ ] **Step 4: Update `utils/dag.py` — add FOCUS to layout constants**

In `utils/dag.py`, after `_INITIAL_ROWS`, add `_ASSESS_FOCUS_ROWS`:

```python
# Shown after ASSESS completes, before PLAN: FOCUS node visible, rest still ???
_ASSESS_FOCUS_ROWS = [
    "FETCH",
    ["CHECK_SOURCES", "GRADE_CONTENT", "REVIEW_CONTEXT"],
    "ASSESS",
    "FOCUS",
    "???",
]
```

Add `"FOCUS"` to `_STAGE_LABELS`:

```python
    "FOCUS":          "Focus",
```

Add `"FOCUS"` to `_PIPELINE_ROWS` (after `"ASSESS"`, before `"PLAN"`):

```python
_PIPELINE_ROWS = [
    "FETCH",
    ["CHECK_SOURCES", "GRADE_CONTENT", "REVIEW_CONTEXT"],
    "ASSESS",
    "FOCUS",
    "PLAN",
    "EXEC",
    "CRITIQUE",
    "GRADE",
    "SUMMARIZE",
    "OUTPUT",
]
```

- [ ] **Step 5: Update three-state row selection in `render_agent_loop`**

In `render_agent_loop`, find:

```python
    rows = _PIPELINE_ROWS if "ASSESS" in done_stages else _INITIAL_ROWS
```

Replace with:

```python
    if "PLAN" in done_stages:
        rows = _PIPELINE_ROWS
    elif "ASSESS" in done_stages:
        rows = _ASSESS_FOCUS_ROWS
    else:
        rows = _INITIAL_ROWS
```

- [ ] **Step 6: Update `back_edge_extra` height for the FOCUS→ASSESS back-edge**

Find:

```python
    back_edge_extra = 40 if "ASSESS" in done_stages else 0
```

Replace with:

```python
    back_edge_extra = 40 if "ASSESS" in done_stages else 0
```

(No change needed — extra space is already allocated when ASSESS is done, which is when the back-edge appears.)

- [ ] **Step 7: Add FOCUS→ASSESS back-edge drawing**

In `render_agent_loop`, after the CRITIQUE→PLAN back-edge block (which ends around `draw.text(..., f"loop {loop_count}", ...)`), add:

```python
    # ── Back-edge FOCUS → ASSESS (amber; runs at most once) ──────────────────
    if "FOCUS" in pos and "ASSESS" in pos:
        _, focus_cy = pos["FOCUS"]
        _, assess_cy = pos["ASSESS"]
        left_x = PAD - 4
        pts = [
            (PAD, focus_cy),
            (left_x - 2, focus_cy),
            (left_x - 2, assess_cy),
            (PAD, assess_cy),
        ]
        draw.line(pts, fill="#CA8A04", width=2)
        ax = PAD
        draw.polygon(
            [(ax - 7, assess_cy - 4), (ax - 7, assess_cy + 4), (ax, assess_cy)],
            fill="#CA8A04",
        )
```

- [ ] **Step 8: Run dag image tests**

```bash
cd /Users/jason/code/wikiwriter && python -m pytest tests/test_dag_image.py -v 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 9: Run full suite**

```bash
cd /Users/jason/code/wikiwriter && python -m pytest --tb=short -q 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 10: Lint**

```bash
cd /Users/jason/code/wikiwriter && flake8 constants.py utils/dag.py tests/test_dag_image.py
```

Expected: no output.

- [ ] **Step 11: Commit**

```bash
cd /Users/jason/code/wikiwriter && git add constants.py utils/dag.py tests/test_dag_image.py && git commit -m "feat: add FOCUS stage node and ASSESS⟲FOCUS back-edge to DAG visualization"
```
