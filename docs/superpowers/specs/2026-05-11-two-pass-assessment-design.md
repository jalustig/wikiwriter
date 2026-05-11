# Two-Pass Assessment + Article Grader Fix — Design Spec

## Problem

Two independent quality bugs:

1. **Article grader truncation**: `article_grader.py` slices `wikitext[:12000]`, so only the first ~4 sections get scored. Sections appearing later in the article are silently missing from `section_grades`, which means they never appear in the UI chart and `assess_article` never sees their scores.

2. **Assessment content blindness**: `assess_article` picks which sections to edit using only section names and numeric scores — it never reads the actual section text. For large, complex articles this produces low-quality editorial decisions.

---

## Fix 1: Article Grader — Section-by-Section Prompt Building

**Goal:** Every section in the article gets a score in `section_grades`.

**Approach:** Replace the single `wikitext[:12000]` slice with a section-by-section assembly from `article.section_texts`, applying a per-section character cap (2000 chars). This ensures all sections contribute to the prompt without any single long section consuming the entire budget.

**Changes:**
- `workers/article_grader.py`: Replace `_build_grader_prompt(article_title, wikitext)` with a version that iterates `article.sections` and builds `sections_text` from `article.section_texts[name][:2000]` per section.
- No model changes. No prompt file changes — the prompt already accepts `sections_text`.
- Cache key already includes `article.wikitext[:500]` (the first 500 chars of raw wikitext), which remains stable and unique per article.

---

## Fix 2: Two-Pass Assessment (ASSESS ⟲ FOCUS)

### When it fires

| `article_class` | Behaviour |
|---|---|
| STUB / DEVELOPING | Single pass. Coarse assessment with names + scores is sufficient — article is short. |
| COMPLETE / OVER_DETAILED | Two passes. Pass 1 identifies 3–5 candidate sections; Pass 2 reads their full text and makes the final selection. |

### Pass 1 — Coarse ASSESS (all articles)

`assess_article` always receives some article text. Pass 1 includes a **truncated lead + first paragraph of each section** (e.g. `section_texts[name][:400]` per section, up to a total cap of ~6000 chars). This gives the LLM enough prose context to assess tone, depth, and quality directionally — without the full text needed for fine-grained editorial selection.

Receives: truncated article text, section names, section scores, content grade, environment metadata, source evaluations.

For STUB/DEVELOPING: returns final `ArticleAssessment` as today.

For COMPLETE/OVER_DETAILED: returns an intermediate `ArticleAssessment` with `article_class` set, `sections` populated with 3–5 candidates tagged `action="EDIT"` (no cap applied yet), and a new field `needs_focus: bool = True` that signals the orchestrator to run a FOCUS pass.

### Pass 2 — FOCUS then re-ASSESS

**FOCUS stage** (new): reads actual section text for the candidate sections identified in Pass 1. Builds a `FocusContext` (just a structured dict / simple model) containing:
- `candidate_sections`: list of `{name, score, text}` for each Pass-1 EDIT candidate
- Original `ArticleAssessment` from Pass 1

**Second ASSESS call**: calls `assess_article` again, now with `focus_context` included in the prompt. Receives the same metadata as Pass 1 plus actual section text for candidates. Returns the final `ArticleAssessment` (with `needs_focus: bool = False`, `_MAX_EDIT_SECTIONS` cap enforced).

### Model changes

Add `needs_focus: bool = False` field to `ArticleAssessment`. Defaults to False so all existing paths are unaffected.

### Prompt strategy

Both passes use `assess_article.txt`. The prompt receives an `article_text` block in both passes:

- **Pass 1**: `article_text` = truncated lead + first ~400 chars of each section (coarse overview).
- **Pass 2**: `article_text` = full text of candidate sections only (for fine-grained selection), plus the same truncated overview of non-candidate sections.

A single prompt with an optional `{focus_context}` placeholder handles both passes. When `focus_context` is `None` (Pass 1 or STUB/DEVELOPING), that block is omitted or replaced with an empty string. This avoids maintaining two separate prompt files.

### Worker implementation

`assess_article` gains:
- A required `article` parameter (it already has this) used to build `article_text` for the prompt — always populated, content varies by pass.
- An optional `focus_context: dict | None = None` parameter. When present, `article_text` includes full candidate section text instead of truncated snippets, and the prompt's `{focus_context}` block is populated.

The `_enforce_section_cap` call happens only when `focus_context is None` and `article_class` is not COMPLETE/OVER_DETAILED (i.e., it's a final or single-pass assessment).

### Cache key

Pass 1 cache key: unchanged (same as today — `assess_article`, `article.url`, `grade.overall_score`, `environment.caution_level`).  
Pass 2 cache key: `assess_article_focused`, `article.url`, `grade.overall_score`, `environment.caution_level`, `sorted(candidate_section_names)`.

---

## Orchestrator — ASSESS⟲FOCUS Loop

```
ASSESS (Pass 1)
  if needs_focus:
    FOCUS (build section text context)
    ASSESS (Pass 2, with focus_context)
  → final assessment
PLAN ...
```

The orchestrator emits:
- `ProgressEvent(stage="ASSESS", status="running")` at loop start
- `ProgressEvent(stage="FOCUS", status="running")` before Pass 2 context building
- `ProgressEvent(stage="FOCUS", status="done")` after context built
- `ProgressEvent(stage="ASSESS", status="running")` again for Pass 2
- `ProgressEvent(stage="ASSESS", status="done")` after final assessment

PLAN and downstream stages are unchanged.

---

## Agent Loop DAG Visualization

### Pipeline layout changes

**Before ASSESS finishes** (`_INITIAL_ROWS`):
```
FETCH
[CHECK_SOURCES, GRADE_CONTENT, REVIEW_CONTEXT]
???
```

**During / after ASSESS⟲FOCUS loop** (new intermediate state):
```
FETCH
[CHECK_SOURCES, GRADE_CONTENT, REVIEW_CONTEXT]
ASSESS
FOCUS          ← new; shown once ASSESS has run once
???
```

**After FOCUS completes (loop exits)**:
```
FETCH
[CHECK_SOURCES, GRADE_CONTENT, REVIEW_CONTEXT]
ASSESS
FOCUS
PLAN
EXEC
CRITIQUE
GRADE
SUMMARIZE
OUTPUT
```

### Back-edge

A left-side back-edge from FOCUS → ASSESS (mirroring the existing CRITIQUE → PLAN back-edge on the right). Color: amber/yellow to distinguish from the red CRITIQUE→PLAN loop. Label: "focus" (no count — loop runs at most once).

The back-edge is drawn only when FOCUS appears in the current rows (i.e., after ASSESS has run at least once).

### Progressive reveal logic

Current: `rows = _PIPELINE_ROWS if "ASSESS" in done_stages else _INITIAL_ROWS`

New: three states:
1. ASSESS not yet done → `_INITIAL_ROWS`
2. ASSESS done, FOCUS not yet done → `_ASSESS_FOCUS_ROWS` (FETCH + GATHER + ASSESS + FOCUS + ???)
3. FOCUS done (or article was STUB/DEVELOPING — no FOCUS stage) → `_PIPELINE_ROWS`

For STUB/DEVELOPING articles that skip FOCUS, the orchestrator still emits a synthetic `FOCUS` done-stage event so the DAG transitions directly from state 2 to state 3 without showing FOCUS as pending.

Actually simpler: emit no FOCUS event for STUB/DEVELOPING; instead gate state transition on `"PLAN" in done_stages` for the full reveal.

Revised three states:
1. "ASSESS" not in done_stages → `_INITIAL_ROWS`
2. "ASSESS" in done_stages and "PLAN" not in done_stages → `_ASSESS_FOCUS_ROWS`
3. "PLAN" in done_stages → `_PIPELINE_ROWS`

This means for STUB/DEVELOPING articles, the DAG briefly shows FOCUS (as pending) between ASSESS and PLAN being done, which is acceptable.

### `constants.py` addition

```python
"FOCUS": ("🔎", "Reading candidate sections…", "Sections read"),
```

---

## Files Changed

| File | Change |
|---|---|
| `workers/article_grader.py` | Section-by-section prompt assembly |
| `models.py` | Add `needs_focus: bool = False` to `ArticleAssessment` |
| `workers/assess_article.py` | Add `focus_context` param; conditional cap; two cache keys |
| `prompts/assess_article.txt` | Add `{article_text}` and optional `{focus_context}` blocks |
| `orchestrator.py` | ASSESS→FOCUS→ASSESS loop; FOCUS stage events |
| `constants.py` | Add FOCUS to STAGE_META |
| `utils/dag.py` | Add FOCUS node, back-edge, three-state progressive reveal |

No new worker files needed — Pass 2 reuses `assess_article` with an extra argument.

---

## What This Does NOT Change

- `_MAX_EDIT_SECTIONS = 3` cap is retained; it just applies only on the final ASSESS pass.
- All downstream workers (PLAN, EXEC, CRITIQUE, etc.) are unchanged.
- The existing CRITIQUE→PLAN back-edge and loop count display are unchanged.
- Cache structure for article_grader is unchanged (cache key already uses `wikitext[:500]`).
