# WikiWriter UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Streamlit UI with a demo-quality interface: sidebar agent loop diagram + task DAG, two-tab layout (Run thinking feed / Debug data panels), and batch progress counters.

**Architecture:** Extract PIL rendering into `dag_image.py` with two public functions. Add `count`/`total` to `ProgressEvent`. Rewrite `app.py` around sidebar + two tabs, maintaining state as plain Python variables updated inside the async event loop. All `st.empty()` placeholders are created before the async run starts; the loop writes into them.

**Tech Stack:** Streamlit, Pillow (PIL), Playwright (testing), asyncio, Pydantic

---

## File map

| File | Change |
|------|--------|
| `dag_image.py` | **Create** — PIL rendering for agent loop diagram and task DAG |
| `tests/test_dag_image.py` | **Create** — unit tests for both renderers |
| `models.py` | **Modify** — add `count: int \| None` and `total: int \| None` to `ProgressEvent` |
| `orchestrator.py` | **Modify** — emit count/total during source evaluation |
| `app.py` | **Rewrite** — sidebar + two-tab layout, flat thinking feed |
| `tests/test_ui_smoke.py` | **Create** — Playwright smoke test |

---

## Task 1: Add `count`/`total` to `ProgressEvent`

**Files:**
- Modify: `models.py:8-12`

- [ ] **Step 1: Add the two optional fields**

Replace the current `ProgressEvent` class:

```python
class ProgressEvent(BaseModel):
    stage: str
    status: Literal["running", "done", "error", "thinking"]
    message: str
    data: dict | None = None
    count: int | None = None   # current item in a batch
    total: int | None = None   # total items in the batch
```

- [ ] **Step 2: Verify tests still pass (no consumer breaks)**

```bash
cd /Users/jason/code/wikiwriter
PYTHONPATH=. .venv/bin/pytest tests/ -q
```

Expected: all 114 tests pass (new fields are optional with `None` defaults).

- [ ] **Step 3: Commit**

```bash
git add models.py
git commit -m "Add count/total progress fields to ProgressEvent"
```

---

## Task 2: Emit source-eval progress from orchestrator

**Files:**
- Modify: `orchestrator.py` — GATHER stage, lines ~173–180

Context: currently source tasks run with `asyncio.gather(*source_tasks)` which gives no per-item progress. Change to `asyncio.as_completed` so each resolved task emits a count event.

- [ ] **Step 1: Replace the source gather block**

Find this block (around line 173):

```python
source_tasks = [
    asyncio.create_task(_eval_source(c))
    for c in article.citations[:20]
]

content_grade, environment = await asyncio.gather(grade_task, env_task)
source_results = await asyncio.gather(*source_tasks, return_exceptions=True)
source_evals = [r for r in source_results if isinstance(r, SourceEvaluation)]
```

Replace with:

```python
citations_to_eval = article.citations[:20]
source_tasks = [
    asyncio.create_task(_eval_source(c))
    for c in citations_to_eval
]

content_grade, environment = await asyncio.gather(grade_task, env_task)

source_results = []
for i, task in enumerate(asyncio.as_completed(source_tasks), start=1):
    result = await task
    source_results.append(result)
    yield ProgressEvent(
        stage="GATHER", status="running",
        message="Evaluating sources",
        count=i, total=len(citations_to_eval),
    )
source_evals = [r for r in source_results if isinstance(r, SourceEvaluation)]
```

- [ ] **Step 2: Run tests**

```bash
PYTHONPATH=. .venv/bin/pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 3: Lint**

```bash
.venv/bin/flake8 orchestrator.py
```

Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add orchestrator.py
git commit -m "Emit per-source progress events during GATHER"
```

---

## Task 3: Create `dag_image.py`

**Files:**
- Create: `dag_image.py`

This module has two public functions. `render_task_dag` is the existing `_dag_png` logic from `app.py` extended with node highlighting. `render_agent_loop` is new.

The agent loop diagram is a **vertical** flowchart of the 7 canonical stages. Sidebar is ~220px wide so nodes are 190×34px with 16px vertical gap.

Node colors:
- Not reached: `#E2E8F0` fill, `#94A3B8` border
- Active (current): `#DBEAFE` fill, `#3B82F6` border, width=3
- Done: `#DCFCE7` fill, `#16A34A` border
- Error: `#FEE2E2` fill, `#DC2626` border

Back-edge (CRITIQUE → PLAN): an L-shaped polyline on the right side of the image — right from CRITIQUE node's right edge, up to PLAN node's right edge, left to PLAN node. Labeled "Revision loop N" in red. Only drawn when `loop_count > 0`.

- [ ] **Step 1: Write `dag_image.py`**

```python
# ABOUTME: PIL-based image renderers for the agent loop diagram and task DAG.
# ABOUTME: Used by the Streamlit sidebar to visualise agent state in real time.

import io

from PIL import Image, ImageDraw, ImageFont

from dag import dag_layers

STAGES = ["FETCH", "GATHER", "ASSESS", "PLAN", "EXEC", "CRITIQUE", "GRADE"]
_STAGE_LABELS = {
    "FETCH":    "🌐  Fetch",
    "GATHER":   "📊  Gather",
    "ASSESS":   "🧠  Assess",
    "PLAN":     "🗺  Plan",
    "EXEC":     "✏  Execute",
    "CRITIQUE": "🔬  Critique",
    "GRADE":    "📈  Grade",
}

_NODE_COLORS = {
    "done":    ("#DCFCE7", "#16A34A", 2),
    "active":  ("#DBEAFE", "#3B82F6", 3),
    "error":   ("#FEE2E2", "#DC2626", 2),
    "pending": ("#F1F5F9", "#CBD5E1", 1),
}

_TYPE_COLORS = {
    "research_section":   ("#DBEAFE", "#3B82F6"),
    "draft_section":      ("#DCFCE7", "#16A34A"),
    "synthesize":         ("#F3E8FF", "#9333EA"),
    "draft_full_article": ("#FEF9C3", "#CA8A04"),
}
_DEFAULT_NODE_COLOR = ("#F1F5F9", "#64748B")


def _fonts():
    try:
        return (
            ImageFont.load_default(size=12),
            ImageFont.load_default(size=10),
            ImageFont.load_default(size=9),
        )
    except TypeError:
        f = ImageFont.load_default()
        return f, f, f


def render_agent_loop(
    stage_history: list[str],
    current_stage: str | None,
    done_stages: set[str],
    loop_count: int,
    width: int = 210,
) -> bytes:
    """Render the agent loop diagram as PNG bytes for st.image()."""
    NW, NH = width - 20, 34
    PAD = 10
    VG = 14   # vertical gap between nodes
    n = len(STAGES)
    H = PAD + n * NH + (n - 1) * VG + PAD + (40 if loop_count > 0 else 0)

    img = Image.new("RGB", (width, H), "#FFFFFF")
    draw = ImageDraw.Draw(img)
    f_label, _, f_small = _fonts()

    # Node positions (centre-x, centre-y)
    cx = PAD + NW // 2
    positions: dict[str, tuple[int, int]] = {}
    for i, stage in enumerate(STAGES):
        cy = PAD + i * (NH + VG) + NH // 2
        positions[stage] = (cx, cy)

    # Draw forward edges first
    for i in range(len(STAGES) - 1):
        s1, s2 = STAGES[i], STAGES[i + 1]
        _, y1 = positions[s1]
        _, y2 = positions[s2]
        mid_y1 = y1 + NH // 2
        mid_y2 = y2 - NH // 2
        draw.line([(cx, mid_y1), (cx, mid_y2 - 4)], fill="#94A3B8", width=1)
        # Arrowhead
        draw.polygon(
            [(cx - 4, mid_y2 - 7), (cx + 4, mid_y2 - 7), (cx, mid_y2)],
            fill="#94A3B8",
        )

    # Draw back-edge if loop occurred (CRITIQUE → PLAN)
    if loop_count > 0:
        plan_idx = STAGES.index("PLAN")
        crit_idx = STAGES.index("CRITIQUE")
        _, plan_cy = positions["PLAN"]
        _, crit_cy = positions["CRITIQUE"]
        right_x = PAD + NW + 6
        plan_y = plan_cy
        crit_y = crit_cy
        # L-shaped path: right edge of CRITIQUE → right → up → right edge of PLAN
        pts = [
            (PAD + NW, crit_y),
            (right_x + 2, crit_y),
            (right_x + 2, plan_y),
            (PAD + NW, plan_y),
        ]
        draw.line(pts, fill="#DC2626", width=2)
        # Arrowhead pointing left into PLAN
        ax = PAD + NW
        draw.polygon(
            [(ax + 7, plan_y - 4), (ax + 7, plan_y + 4), (ax, plan_y)],
            fill="#DC2626",
        )
        label = f"loop {loop_count}"
        draw.text((right_x + 4, (plan_y + crit_y) // 2 - 5), label, fill="#DC2626", font=f_small)

    # Draw nodes
    for stage in STAGES:
        cx_node, cy_node = positions[stage]
        x0 = PAD
        y0 = cy_node - NH // 2
        x1 = PAD + NW
        y1 = cy_node + NH // 2

        if stage == current_stage:
            state = "active"
        elif stage in done_stages:
            state = "done"
        else:
            state = "pending"

        fill, border, bw = _NODE_COLORS[state]
        draw.rounded_rectangle([x0, y0, x1, y1], radius=6, fill=fill, outline=border, width=bw)

        label = _STAGE_LABELS.get(stage, stage)
        draw.text((cx_node, cy_node), label, fill="#1E293B", anchor="mm", font=f_label)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_task_dag(
    dag: dict,
    done_nodes: set[str],
    current_nodes: set[str],
    width: int = 210,
) -> bytes:
    """Render the task DAG as PNG bytes. Nodes highlighted by execution state."""
    layers = dag_layers(dag)

    NW, NH = 190, 58
    HG, VG = 60, 12
    PAD = 10

    n_layers = len(layers)
    max_per_layer = max(len(layer) for layer in layers)

    W = n_layers * NW + (n_layers - 1) * HG + 2 * PAD
    H = max(120, max_per_layer * NH + (max_per_layer - 1) * VG + 2 * PAD)

    pos: dict[str, tuple[int, int]] = {}
    for li, layer in enumerate(layers):
        n = len(layer)
        col_h = n * NH + (n - 1) * VG
        y0 = (H - col_h) // 2
        for i, nid in enumerate(layer):
            cx = PAD + li * (NW + HG) + NW // 2
            cy = y0 + i * (NH + VG) + NH // 2
            pos[nid] = (cx, cy)

    img = Image.new("RGB", (W, H), "#F8FAFC")
    draw = ImageDraw.Draw(img)
    f_label, f_small, f_id = _fonts()

    # Edges
    for nid, node in dag.items():
        cx2, cy2 = pos[nid]
        deps = node.get("deps", []) if isinstance(node, dict) else node.deps
        for dep in deps:
            cx1, cy1 = pos[dep]
            x_start = cx1 + NW // 2
            x_end = cx2 - NW // 2 - 1
            draw.line([(x_start, cy1), (x_end - 4, cy2)], fill="#94A3B8", width=2)
            draw.polygon(
                [(x_end - 9, cy2 - 5), (x_end - 9, cy2 + 5), (x_end, cy2)],
                fill="#94A3B8",
            )

    # Nodes
    for nid, node in dag.items():
        cx, cy = pos[nid]
        x0, y0 = cx - NW // 2 + 1, cy - NH // 2 + 1
        x1, y1 = cx + NW // 2 - 1, cy + NH // 2 - 1

        node_type = node.get("type", "") if isinstance(node, dict) else node.type
        params = node.get("params", {}) if isinstance(node, dict) else node.params

        # State overrides type color
        if nid in done_nodes:
            fill, border = "#DCFCE7", "#16A34A"
            bw = 2
        elif nid in current_nodes:
            fill, border = "#DBEAFE", "#3B82F6"
            bw = 3
        else:
            fill, border = _TYPE_COLORS.get(node_type, _DEFAULT_NODE_COLOR)
            bw = 2

        draw.rounded_rectangle([x0, y0, x1, y1], radius=8, fill=fill, outline=border, width=bw)
        draw.text((x0 + 6, y0 + 4), f"[{nid}]", fill=border, font=f_id)

        type_label = node_type.replace("_", " ")
        has_params = bool(params)
        draw.text(
            (cx, cy - 6 if has_params else cy),
            type_label, fill="#1E293B", anchor="mm", font=f_label,
        )
        if has_params:
            pstr = "  ".join(str(v) for v in params.values())
            if len(pstr) > 28:
                pstr = pstr[:26] + "…"
            draw.text((cx, cy + 8), pstr, fill="#475569", anchor="mm", font=f_small)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
```

- [ ] **Step 2: Lint**

```bash
.venv/bin/flake8 dag_image.py
```

Expected: no output.

- [ ] **Step 3: Quick smoke check — confirm both functions return PNG bytes**

```bash
PYTHONPATH=. .venv/bin/python -c "
from dag_image import render_agent_loop, render_task_dag
png = render_agent_loop(['FETCH','GATHER'], 'GATHER', {'FETCH'}, 0)
assert png[:4] == b'\x89PNG', 'not PNG'
dag = {'t1': {'type': 'research_section', 'params': {'section': 'History'}, 'deps': []}}
png2 = render_task_dag(dag, set(), set())
assert png2[:4] == b'\x89PNG', 'not PNG'
print('OK')
"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add dag_image.py
git commit -m "Add dag_image.py: agent loop diagram and task DAG PIL renderers"
```

---

## Task 4: Write tests for `dag_image.py`

**Files:**
- Create: `tests/test_dag_image.py`

- [ ] **Step 1: Write tests**

```python
# ABOUTME: Tests for PIL-based agent loop and task DAG image renderers.
# ABOUTME: Checks output is valid PNG bytes and responds to state changes.

import pytest
from dag_image import render_agent_loop, render_task_dag

PNG_MAGIC = b"\x89PNG"


def test_agent_loop_returns_png():
    png = render_agent_loop([], None, set(), 0)
    assert png[:4] == PNG_MAGIC


def test_agent_loop_with_active_stage():
    png = render_agent_loop(["FETCH"], "FETCH", set(), 0)
    assert png[:4] == PNG_MAGIC
    assert len(png) > 1000


def test_agent_loop_with_done_stages():
    png = render_agent_loop(["FETCH", "GATHER"], "GATHER", {"FETCH"}, 0)
    assert png[:4] == PNG_MAGIC


def test_agent_loop_with_back_edge():
    # loop_count > 0 triggers back-edge drawing
    png_no_loop = render_agent_loop(["FETCH"], "PLAN", {"FETCH", "GATHER", "ASSESS"}, 0)
    png_loop = render_agent_loop(
        ["FETCH", "GATHER", "ASSESS", "PLAN", "EXEC", "CRITIQUE", "PLAN"],
        "PLAN",
        {"FETCH", "GATHER", "ASSESS", "EXEC", "CRITIQUE"},
        1,
    )
    assert png_loop[:4] == PNG_MAGIC
    # Image with back-edge should differ from one without
    assert png_loop != png_no_loop


def test_task_dag_returns_png():
    dag = {
        "t1": {"type": "research_section", "params": {"section": "History"}, "deps": []},
        "t2": {"type": "draft_section", "params": {"section": "History"}, "deps": ["t1"]},
    }
    png = render_task_dag(dag, set(), set())
    assert png[:4] == PNG_MAGIC


def test_task_dag_done_nodes():
    dag = {
        "t1": {"type": "research_section", "params": {}, "deps": []},
        "t2": {"type": "draft_section", "params": {}, "deps": ["t1"]},
    }
    png_none_done = render_task_dag(dag, set(), set())
    png_t1_done = render_task_dag(dag, {"t1"}, set())
    # Images must differ when a node is done
    assert png_none_done != png_t1_done


def test_task_dag_current_nodes():
    dag = {"t1": {"type": "research_section", "params": {}, "deps": []}}
    png_idle = render_task_dag(dag, set(), set())
    png_active = render_task_dag(dag, set(), {"t1"})
    assert png_idle != png_active


def test_task_dag_empty():
    # Empty dag should not crash
    png = render_task_dag({}, set(), set())
    assert isinstance(png, bytes)
```

- [ ] **Step 2: Run tests**

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_dag_image.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_dag_image.py
git commit -m "Add tests for dag_image renderers"
```

---

## Task 5: Install Playwright

**Files:** none (environment setup)

- [ ] **Step 1: Install playwright into the venv**

```bash
cd /Users/jason/code/wikiwriter
.venv/bin/pip install playwright
```

- [ ] **Step 2: Install browser binaries**

```bash
.venv/bin/playwright install chromium
```

Expected: downloads Chromium, ends with "Chromium ... downloaded to ..."

- [ ] **Step 3: Verify installation**

```bash
PYTHONPATH=. .venv/bin/python -c "from playwright.sync_api import sync_playwright; print('OK')"
```

Expected: `OK`

---

## Task 6: Rewrite `app.py`

**Files:**
- Modify: `app.py` (full rewrite)

This is the main task. The new app:
1. Sidebar: agent loop image + task DAG image + progress counter, all in `st.empty()` placeholders
2. Main area: `st.tabs(["▶ Run", "🔬 Debug"])`
3. Run tab: flat thinking feed (one `st.empty()` rewritten on each thought) + results appended after done
4. Debug tab: per-stage `st.empty()` placeholders filled as stages complete

Key implementation detail for the thinking feed: maintain `feed_lines: list[str]` and call `feed_ph.markdown("\n\n".join(feed_lines))` on every update. A new stage separator line is added once per stage.

Key detail for current_stage tracking: a back-edge is when a stage in `done_stages` fires again. Track `last_stage_in_feed` to know when to insert a separator.

- [ ] **Step 1: Write the new `app.py`**

```python
# ABOUTME: Streamlit app — sidebar agent loop diagram, two-tab layout (Run/Debug).
# ABOUTME: Run tab shows flat thinking feed + results; Debug tab shows raw data panels.

import asyncio

import streamlit as st

from constants import STAGE_META
from dag_image import render_agent_loop, render_task_dag
from diff_utils import section_diff_html
from models import (
    ContentGrade, EditorialEnvironment, ArticleAssessment,
    CritiqueResult, EditProposal,
)
from orchestrator import WikiWriterOrchestrator

CAUTION_COLORS = {"LOW": "green", "MODERATE": "orange", "HIGH": "red", "CRITICAL": "red"}
VERDICT_COLORS = {
    "PASS": "#16A34A", "REVISE": "#D97706", "PARTIAL_ACCEPT": "#2563EB", "DISCARD": "#DC2626",
}

CANONICAL_STAGES = ["FETCH", "GATHER", "ASSESS", "PLAN", "EXEC", "CRITIQUE", "GRADE"]


# ── Debug panel renderers ──────────────────────────────────────────────────────

def render_environment_panel(env: EditorialEnvironment) -> None:
    st.subheader("Editorial Environment")
    color = CAUTION_COLORS.get(env.caution_level, "gray")
    st.markdown(
        f"<span style='background:{color};color:white;padding:4px 10px;"
        f"border-radius:4px;font-weight:bold;'>{env.caution_level}</span>",
        unsafe_allow_html=True,
    )
    st.write("")
    col1, col2, col3 = st.columns(3)
    col1.metric("Revert Rate (12mo)", f"{env.revert_rate_12mo:.1%}")
    col2.metric("Edit Velocity", env.edit_velocity)
    col3.metric("Dominant Editor", env.dominant_editor or "None")
    if env.flip_flopped_sections:
        st.write("**Flip-flopped sections:**", ", ".join(env.flip_flopped_sections))
    if env.policies_and_restrictions:
        st.write("**Policies/restrictions:**")
        for p in env.policies_and_restrictions:
            st.write(f"- {p}")
    if env.editor_imposed_norms:
        st.write("**Editor norms:**")
        for n in env.editor_imposed_norms:
            st.write(f"- {n}")
    st.caption(env.environment_narrative)


def render_grade_panel(grade: ContentGrade) -> None:
    st.subheader("Article Quality")
    st.metric("Grade", f"{grade.letter_grade} ({grade.overall_score:.1f}/10)")
    rows = [{"Dimension": dim, "Score": f"{score:.1f}"} for dim, score in grade.dimension_scores.items()]
    st.table(rows)
    st.caption(grade.narrative)


def render_assessment_panel(assessment: ArticleAssessment) -> None:
    st.subheader("Article Assessment")
    col1, col2, col3 = st.columns(3)
    col1.metric("Importance", assessment.importance.tier)
    col2.metric("Class", assessment.article_class)
    col3.metric("Effort", assessment.effort_ceiling)
    st.caption(assessment.edit_rationale)
    if assessment.primary_weaknesses:
        st.write("**Primary weaknesses:**")
        for w in assessment.primary_weaknesses:
            st.write(f"- {w}")
    st.write("**Per-section decisions:**")
    for s in assessment.sections:
        icon = "✏️" if s.action == "EDIT" else "✓"
        tag = f"[{s.edit_type}]" if s.edit_type else ""
        st.write(f"{icon} **{s.name}** {tag} — {s.rationale}")


def render_section_diff(draft: dict) -> None:
    changes = draft.get("changes_made", [])
    header = f"**{draft['section_name']}**" + (f" — {changes[0]}" if changes else "")
    with st.expander(header, expanded=False):
        if changes:
            st.write("**Changes made:**")
            for c in changes:
                st.write(f"- {c}")
        orig, revised = draft["original_text"], draft["revised_text"]
        if orig.strip() == revised.strip():
            st.write("_(no text changes)_")
        else:
            st.html(section_diff_html(orig, revised))
        for label, cites in (
            ("Citations added", draft.get("citations_added", [])),
            ("Citations removed", draft.get("citations_removed", [])),
        ):
            if cites:
                st.write(f"**{label}:**", ", ".join(cites))


def render_diff_view(section_drafts: list[dict]) -> None:
    st.subheader("Section Drafts")
    if not section_drafts:
        st.write("No drafts available.")
        return
    for draft in section_drafts:
        render_section_diff(draft)


def render_critique_panel(critique: CritiqueResult) -> None:
    st.subheader("Critique")
    color = VERDICT_COLORS.get(critique.overall_verdict, "gray")
    st.markdown(
        f"<span style='background:{color};color:white;padding:4px 10px;"
        f"border-radius:4px;font-weight:bold;'>{critique.overall_verdict}</span>",
        unsafe_allow_html=True,
    )
    st.write("")
    if critique.section_results:
        for sec_name, sec_result in critique.section_results.items():
            icon = "✅" if sec_result.verdict == "PASS" else "❌"
            with st.expander(f"{icon} {sec_name}", expanded=sec_result.verdict == "FAIL"):
                for dim, data in sec_result.dimensions.items():
                    dim_icon = "✅" if data.verdict == "PASS" else "❌"
                    st.write(f"{dim_icon} **{dim}**: {data.notes}")
                if sec_result.suggested_fix:
                    st.info(f"Suggested fix: {sec_result.suggested_fix}")
    elif critique.dimension_results:
        for dim, result in critique.dimension_results.items():
            icon = "✅" if result.verdict == "PASS" else "❌"
            st.write(f"{icon} **{dim.replace('_', ' ').title()}**: {result.notes}")
    if critique.revision_instructions:
        st.write("**Revision instructions:**")
        for instr in critique.revision_instructions:
            st.write(f"- {instr}")
    if critique.discard_reason:
        st.error(f"Discard reason: {critique.discard_reason}")


def render_proposal_panel(proposal: EditProposal) -> None:
    st.subheader("Edit Proposal")
    col1, col2, col3 = st.columns(3)
    col1.metric("Input Grade",
                proposal.input_grade.letter_grade, f"{proposal.input_grade.overall_score:.1f}/10")
    col2.metric("Output Grade",
                proposal.output_grade.letter_grade, f"{proposal.output_grade.overall_score:.1f}/10")
    col3.metric("Quality Delta", f"{proposal.quality_delta:+.1f}", delta_color="normal")
    render_critique_panel(proposal.critique)
    if proposal.edit_summary:
        st.divider()
        st.subheader("Editorial Summary")
        st.write(proposal.edit_summary.narrative)
        st.divider()
        st.subheader("Submit to Wikipedia")
        st.text_area(
            "Edit summary (copy into Wikipedia's edit summary box)",
            proposal.edit_summary.disclosure_line,
            height=80,
        )
    col1, col2 = st.columns(2)
    if col1.button("✅ Approve edit", type="primary"):
        st.success("Approved. Copy the edit summary above and apply the diff to Wikipedia manually.")
    if col2.button("❌ Reject"):
        st.warning("Edit rejected.")


# ── Live streaming runner ──────────────────────────────────────────────────────

def run_and_render(url: str) -> None:
    # ── Sidebar placeholders ───────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("#### Agent Loop")
        loop_ph = st.empty()
        st.markdown("---")
        st.markdown("#### Task DAG")
        dag_ph = st.empty()
        st.markdown("---")
        counter_ph = st.empty()

    # ── Main tabs ──────────────────────────────────────────────────────────────
    tab_run, tab_debug = st.tabs(["▶ Run", "🔬 Debug"])

    with tab_run:
        feed_ph = st.empty()
        results_ph = st.empty()

    with tab_debug:
        debug_ph = st.empty()

    # ── Mutable state (captured by inner async function) ───────────────────────
    state = {
        "stage_history": [],        # stage names in order, with repeats on loops
        "current_stage": None,
        "done_stages": set(),
        "loop_count": 0,
        "feed_lines": [],           # accumulated thinking feed text
        "last_feed_stage": None,    # track when to insert stage separator
        "accumulated": {},          # all event.data merged
        "task_dag": {},
        "done_nodes": set(),
        "current_nodes": set(),
        "debug_sections": {},       # stage -> rendered markdown/html strings
    }

    def _refresh_loop_image():
        png = render_agent_loop(
            state["stage_history"],
            state["current_stage"],
            state["done_stages"],
            state["loop_count"],
        )
        loop_ph.image(png, use_container_width=True)

    def _refresh_dag_image():
        if state["task_dag"]:
            png = render_task_dag(
                state["task_dag"],
                state["done_nodes"],
                state["current_nodes"],
            )
            dag_ph.image(png, use_container_width=True)

    def _append_thought(stage: str, text: str):
        _, running_label, _ = STAGE_META.get(stage, ("•", stage, stage))
        if state["last_feed_stage"] != stage:
            state["feed_lines"].append(f"---\n**{running_label}**\n")
            state["last_feed_stage"] = stage
        state["feed_lines"].append(text)
        feed_ph.markdown("\n\n".join(state["feed_lines"]))

    def _render_debug(acc: dict) -> None:
        """Re-render the entire debug tab from accumulated data."""
        with debug_ph.container():
            if "grade" in acc and "environment" in acc:
                st.markdown("### GATHER")
                col1, col2 = st.columns(2)
                with col1:
                    render_environment_panel(EditorialEnvironment.model_validate(acc["environment"]))
                with col2:
                    render_grade_panel(ContentGrade.model_validate(acc["grade"]))
                if "audit" in acc:
                    st.subheader("Sources")
                    tab1, tab2 = st.tabs(["Existing Citations", "New Sources"])
                    with tab1:
                        for s in acc["audit"]:
                            icon = "✅" if s["recommendation"] == "USE" else (
                                "⚠️" if s["recommendation"] == "WEAK" else "❌"
                            )
                            note = f" ({s['status']})" if s["status"] != "LIVE" else ""
                            st.write(
                                f"{icon} [{s['overall_score']:.1f}] `{s['domain_type']}`{note}"
                                f" — {s['url'][:80]}"
                            )
                            if s.get("topic_coverage_summary"):
                                st.caption(f"   {s['topic_coverage_summary']}")
                    with tab2:
                        new = acc.get("new_sources", [])
                        if not new:
                            st.write("_(none found)_")
                        for s in new:
                            st.write(f"➕ [{s['overall_score']:.1f}] `{s['domain_type']}` — {s['url'][:80]}")
                            if s.get("topic_coverage_summary"):
                                st.caption(f"   {s['topic_coverage_summary']}")

            if "assessment" in acc:
                st.markdown("### ASSESS")
                render_assessment_panel(ArticleAssessment.model_validate(acc["assessment"]))

            if "dag" in acc:
                st.markdown("### PLAN")
                if state["task_dag"]:
                    png = render_task_dag(state["task_dag"], set(), set())
                    st.image(png, use_container_width=True)
                st.caption(acc.get("dag_narrative", ""))

            if "section_drafts" in acc:
                st.markdown("### EXEC")
                render_diff_view(acc["section_drafts"])

            if "critique" in acc:
                st.markdown("### CRITIQUE")
                render_critique_panel(CritiqueResult.model_validate(acc["critique"]))

            if "proposal" in acc:
                st.markdown("### GRADE")
                proposal = EditProposal.model_validate(acc["proposal"])
                col1, col2, col3 = st.columns(3)
                col1.metric("Input Grade",
                            proposal.input_grade.letter_grade,
                            f"{proposal.input_grade.overall_score:.1f}/10")
                col2.metric("Output Grade",
                            proposal.output_grade.letter_grade,
                            f"{proposal.output_grade.overall_score:.1f}/10")
                col3.metric("Quality Delta", f"{proposal.quality_delta:+.1f}", delta_color="normal")

    async def _stream():
        async for event in WikiWriterOrchestrator().run(url):
            stage = event.stage

            # ── Stage transition bookkeeping ───────────────────────────────────
            if stage != state["current_stage"]:
                # Detect back-edge: stage we've already completed is starting again
                if stage in state["done_stages"]:
                    state["loop_count"] += 1

                state["current_stage"] = stage
                if stage not in state["stage_history"] or stage in state["done_stages"]:
                    state["stage_history"].append(stage)

                _refresh_loop_image()

            # ── Handle event by status ─────────────────────────────────────────
            if event.status == "thinking":
                _append_thought(stage, f"*{event.message}*")

            elif event.status == "running":
                if event.count is not None and event.total is not None:
                    counter_ph.markdown(
                        f"**{event.message}:** {event.count} / {event.total}"
                    )
                # Track current DAG node for task DAG highlighting
                if stage == "EXEC" and ":" in event.message:
                    node_id = event.message.split(":")[0].strip()
                    state["current_nodes"].add(node_id)
                    _refresh_dag_image()

            elif event.status == "done":
                state["done_stages"].add(stage)
                counter_ph.empty()

                if event.data:
                    state["accumulated"].update(event.data)
                    if "dag" in event.data:
                        state["task_dag"] = event.data["dag"]
                        state["done_nodes"].clear()
                        state["current_nodes"].clear()
                        _refresh_dag_image()

                # Mark DAG node as done during EXEC
                if stage == "EXEC":
                    node_id = event.message.split(":")[0].strip() if ":" in event.message else None
                    if node_id and node_id in state["task_dag"]:
                        state["current_nodes"].discard(node_id)
                        state["done_nodes"].add(node_id)
                        _refresh_dag_image()

                _refresh_loop_image()
                _render_debug(state["accumulated"])

            elif event.status == "error":
                _append_thought(stage, f"❌ **{event.message}**")
                _refresh_loop_image()

    asyncio.run(_stream())

    # ── Render results in Run tab after completion ─────────────────────────────
    acc = state["accumulated"]
    with results_ph.container():
        st.divider()
        if "section_drafts" in acc:
            render_diff_view(acc["section_drafts"])
        if "proposal" in acc:
            render_proposal_panel(EditProposal.model_validate(acc["proposal"]))


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(page_title="WikiWriter", layout="wide")

    with st.sidebar:
        st.title("WikiWriter")
        st.caption("Quality-first Wikipedia editing agent")

    url = st.text_input(
        "Wikipedia article URL",
        placeholder="https://en.wikipedia.org/wiki/Super_Bowl_XXV",
    )
    analyse = st.button("Analyse & draft edit", type="primary")

    if not analyse or not url:
        return

    run_and_render(url)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Lint**

```bash
.venv/bin/flake8 app.py
```

Expected: no output.

- [ ] **Step 3: Run unit tests (no regressions)**

```bash
PYTHONPATH=. .venv/bin/pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "Rewrite app.py: sidebar agent loop, two-tab layout, flat thinking feed"
```

---

## Task 7: Playwright smoke test

**Files:**
- Create: `tests/test_ui_smoke.py`

This test starts Streamlit, navigates to it, submits the Super Bowl XXV URL, and verifies the UI structure appears correctly. It uses a short timeout since we're not waiting for the full LLM run — just verifying the page renders without JS errors and the expected elements exist.

- [ ] **Step 1: Write the smoke test**

```python
# ABOUTME: Playwright smoke test — verifies Streamlit app loads and run initiates correctly.
# ABOUTME: Does not wait for full LLM run; checks UI structure only.

import subprocess
import time

import pytest
from playwright.sync_api import sync_playwright, expect


@pytest.fixture(scope="module")
def streamlit_server():
    """Start Streamlit in a subprocess, yield, then kill it."""
    proc = subprocess.Popen(
        ["python", "-m", "streamlit", "run", "app.py",
         "--server.port", "8599",
         "--server.headless", "true",
         "--server.fileWatcherType", "none"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Give Streamlit time to start
    time.sleep(6)
    yield "http://localhost:8599"
    proc.terminate()
    proc.wait()


def test_app_loads(streamlit_server):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(streamlit_server, timeout=15000)
        # Title in sidebar
        expect(page.locator("text=WikiWriter")).to_be_visible(timeout=10000)
        browser.close()


def test_tabs_present(streamlit_server):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(streamlit_server, timeout=15000)
        page.wait_for_selector("text=WikiWriter", timeout=10000)
        # Before submitting, tabs are not visible yet (run_and_render not called)
        # Input and button should be present
        expect(page.locator("input[type='text']")).to_be_visible(timeout=5000)
        expect(page.locator("button", has_text="Analyse & draft edit")).to_be_visible(timeout=5000)
        browser.close()


def test_run_shows_tabs(streamlit_server):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(streamlit_server, timeout=15000)
        page.wait_for_selector("input[type='text']", timeout=10000)

        # Fill URL and submit
        page.fill("input[type='text']", "https://en.wikipedia.org/wiki/Super_Bowl_XXV")
        page.click("button:has-text('Analyse & draft edit')")

        # Tabs should appear almost immediately (before LLM calls complete)
        expect(page.locator("[data-baseweb='tab']", has_text="Run")).to_be_visible(timeout=15000)
        expect(page.locator("[data-baseweb='tab']", has_text="Debug")).to_be_visible(timeout=5000)

        # Sidebar agent loop image should appear
        expect(page.locator("[data-testid='stSidebar'] img")).to_be_visible(timeout=15000)

        browser.close()
```

- [ ] **Step 2: Start Streamlit manually and verify it loads**

```bash
cd /Users/jason/code/wikiwriter
PYTHONPATH=. .venv/bin/streamlit run app.py --server.port 8502 --server.headless true &
sleep 6
curl -s http://localhost:8502 | grep -c "streamlit" || echo "FAILED"
kill %1
```

Expected: a number > 0 (page returned HTML with streamlit references).

- [ ] **Step 3: Run the smoke test**

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_ui_smoke.py -v --timeout=60
```

Expected: all 3 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_ui_smoke.py
git commit -m "Add Playwright smoke tests for Streamlit UI"
```

---

## Task 8: End-to-end visual verification

This task is manual + automated — run the full agent against Super Bowl XXV and verify the UI looks correct.

- [ ] **Step 1: Start Streamlit**

```bash
cd /Users/jason/code/wikiwriter
PYTHONPATH=. .venv/bin/streamlit run app.py
```

- [ ] **Step 2: Write a Playwright script that submits the URL and screenshots the result at key moments**

```bash
PYTHONPATH=. .venv/bin/python - <<'EOF'
import time
import subprocess
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)  # visible for inspection
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto("http://localhost:8501")
    page.wait_for_selector("input[type='text']", timeout=10000)

    page.fill("input[type='text']", "https://en.wikipedia.org/wiki/Super_Bowl_XXV")
    page.screenshot(path="/tmp/ww_01_before_run.png")

    page.click("button:has-text('Analyse & draft edit')")

    # Wait for tabs to appear
    page.wait_for_selector("[data-baseweb='tab']", timeout=15000)
    page.screenshot(path="/tmp/ww_02_tabs_visible.png")

    # Wait for sidebar image to appear
    page.wait_for_selector("[data-testid='stSidebar'] img", timeout=20000)
    page.screenshot(path="/tmp/ww_03_sidebar_loop.png")

    # Wait for first thinking message
    page.wait_for_selector("em", timeout=30000)
    page.screenshot(path="/tmp/ww_04_thinking_feed.png")

    print("Screenshots saved to /tmp/ww_0*.png")
    browser.close()
EOF
```

- [ ] **Step 3: Open screenshots and verify**

```bash
open /tmp/ww_01_before_run.png /tmp/ww_02_tabs_visible.png /tmp/ww_03_sidebar_loop.png /tmp/ww_04_thinking_feed.png
```

Check:
- `ww_01`: URL input and button visible, WikiWriter title in sidebar
- `ww_02`: Run and Debug tabs visible
- `ww_03`: Agent loop diagram in sidebar (7 stage nodes, FETCH highlighted)
- `ww_04`: Italic thinking text appearing in Run tab

- [ ] **Step 4: If any visual issue found, fix and re-run from Task 6 Step 1**

- [ ] **Step 5: Final commit**

```bash
git add -p  # stage only relevant changes
git commit -m "UI redesign complete: verified against Super Bowl XXV"
```

---

## Self-Review

**Spec coverage:**
- ✅ Sidebar agent loop diagram — Task 3, Task 6
- ✅ Back-edge appears dynamically — Task 3 (loop_count > 0 path), Task 6 (back-edge detection)
- ✅ Task DAG with node highlighting — Task 3, Task 6
- ✅ Progress counters (count/total) — Task 1, Task 2, Task 6
- ✅ Two tabs (Run/Debug) — Task 6
- ✅ Flat thinking feed with stage separators — Task 6
- ✅ Results append after run completes — Task 6
- ✅ Debug tab shows all data panels progressively — Task 6
- ✅ `ProgressEvent` model change — Task 1
- ✅ Source eval counter in orchestrator — Task 2
- ✅ `dag_image.py` extracted from `app.py` — Task 3
- ✅ Playwright test — Task 7, Task 8

**Placeholder scan:** None found.

**Type consistency:**
- `render_agent_loop(stage_history, current_stage, done_stages, loop_count)` — used consistently in Task 3, Task 4, Task 6
- `render_task_dag(dag, done_nodes, current_nodes)` — used consistently in Task 3, Task 4, Task 6
- `state["done_stages"]` is a `set[str]` — consistent throughout Task 6
- `event.count`, `event.total` defined in Task 1, read in Task 6 ✅
