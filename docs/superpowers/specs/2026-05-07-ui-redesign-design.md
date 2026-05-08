# WikiWriter UI Redesign — Design Spec

## Goal

Replace the current Streamlit UI with a demo-quality interface that makes the agent's intelligence visible: a live thinking feed, a dynamic agent loop diagram, and task-level progress counters — with all raw data panels moved behind a Debug tab.

## Architecture

Two surfaces change: `app.py` (Streamlit) gets a full layout overhaul. `models.py` gets two new fields on `ProgressEvent`. The orchestrator gets minor additions to emit count/total progress during batch operations. The PIL rendering code (currently inside `app.py`) is extracted to `dag_image.py` and extended to render the agent loop diagram and support node highlighting.

No changes to the orchestrator's event model beyond the two new fields. No changes to workers or prompts.

---

## Layout

### Sidebar

Always visible. Three sections stacked vertically:

**1. Agent loop diagram** — a PIL-rendered PNG showing the full run graph. Canonical node order: FETCH → GATHER → ASSESS → PLAN → EXEC → CRITIQUE → GRADE. Node coloring:

- Gray fill — not yet reached
- Blue fill with bright border — currently active
- Green fill — completed
- Red fill — errored / discarded

Edges are drawn as arrows. The linear path is drawn from the start. Back-edges (e.g. CRITIQUE → PLAN on a revision loop) are **not shown until the agent actually takes them** — they appear the moment the second PLAN event fires, drawn as a curved red arrow labeled "Revision loop 1" (incrementing on subsequent loops).

The image is held in an `st.empty()` placeholder and re-rendered each time stage state changes.

**2. Task DAG** — the per-stage task graph, already generated from PLAN output. Appears once PLAN completes. Extended to accept `done_nodes: set[str]` and `current_nodes: set[str]`; completed nodes render green, in-flight nodes render blue. Re-rendered on each task completion event during EXEC. Also held in `st.empty()`.

**3. Progress counters** — plain text lines below the task DAG, updated during batch operations:

```
Evaluating sources: 12 / 20
Drafting sections:   3 /  7
```

Only shown when a batch is in progress. Cleared when the stage completes.

---

### Main panel — two tabs

#### Run tab (default)

A single flat thinking feed. Stage transitions are shown as bold separators:

```
── Gathering evidence ──────────────────────────────────────────

This article covers the 1965 Watts rebellion — one of the
defining moments in US civil rights history...

Talk page has an active dispute over casualty figures:
three editors arguing 34 vs 36 since 2019. No-touch zone.

── Drafting sections ───────────────────────────────────────────

"History" — four uncited claims. Found two NYT sources from
1965 that cover the timeline directly. This is fixable.

[thoughts continue appending...]
```

Thoughts accumulate as a single growing text block in one `st.empty()` container. No `st.status()` boxes. No collapsing. The feed is the primary content during the run.

After the run completes, results append below a visual divider — section diffs (one expander per section) followed by the edit proposal. The thinking feed stays in place above them as a record.

#### Debug tab

All existing data panels, in stage order, revealed progressively as each stage completes. Content appears live — the tab is not a post-run snapshot.

Sections:

- **GATHER** — grade metrics table, editorial environment (caution level, revert rate, disputes, affiliations), full sources audit (all rows with score, domain type, recommendation, coverage summary)
- **ASSESS** — importance tier, article class, effort ceiling, per-section decisions table
- **PLAN** — task DAG image (large), narrative
- **EXEC** — section diffs with word-level highlights (existing render_section_diff)
- **CRITIQUE** — per-section pass/fail with dimension breakdown, suggested fixes, revision instructions
- **GRADE** — input grade, output grade, delta

The thinking feed does **not** appear in the Debug tab — it lives in the Run tab only.

---

## Data model change

```python
class ProgressEvent(BaseModel):
    stage: str
    status: Literal["running", "done", "error", "thinking"]
    message: str
    data: dict | None = None
    count: int | None = None   # current item in a batch
    total: int | None = None   # total items in the batch
```

`count` and `total` are set on `status="running"` events during batch operations. The sidebar reads these and updates the counter display. No other consumers need to change — `count`/`total` are ignored everywhere they aren't explicitly read.

---

## Orchestrator changes

Two batch operations need per-item progress events:

**Source evaluation** (GATHER) — currently runs all tasks with `asyncio.gather`. Change to increment a shared counter after each task resolves and emit a `ProgressEvent(stage="GATHER", status="running", message="Evaluating sources", count=n, total=total)`.

**Section execution** (EXEC) — the DAG executor already emits per-node done events. No change needed; the app reads `dag_event.status == "done"` and updates `current_nodes` accordingly.

---

## Agent loop state tracking

The app maintains:

```python
stage_history: list[str]   # ordered stage names, with repeats on loops
current_stage: str | None
done_stages: set[str]
loop_count: int            # increments each time a back-edge is detected
```

A back-edge is detected when a stage in `stage_history` fires again after having already completed. The canonical stage order is fixed: `["FETCH", "GATHER", "ASSESS", "PLAN", "EXEC", "CRITIQUE", "GRADE"]`. Any new stage event whose name has a lower canonical index than the previous stage's name is a back-edge.

The loop diagram is re-rendered whenever `stage_history`, `current_stage`, or `done_stages` changes.

---

## New file: `dag_image.py`

Extract all PIL rendering from `app.py` into a standalone module. Two public functions:

```python
def render_agent_loop(
    stage_history: list[str],
    current_stage: str | None,
    done_stages: set[str],
    loop_count: int,
    width: int = 220,
) -> bytes:
    """Render the agent loop diagram as PNG bytes."""

def render_task_dag(
    dag: dict,
    done_nodes: set[str],
    current_nodes: set[str],
    width: int = 220,
) -> bytes:
    """Render the task DAG as PNG bytes. Extends existing _dag_png logic."""
```

Both return raw PNG bytes for `st.image()`. The existing `_dag_png` function in `app.py` is deleted and replaced by `render_task_dag`.

---

## What does NOT change

- `cli.py` — no changes. CLI remains as-is; it is a debug tool.
- All workers, prompts, models (except the two new ProgressEvent fields).
- The section diff logic in `diff_utils.py`.
- The orchestrator's event stream structure beyond the new fields and the source-evaluation counter.
- The `STAGE_META` constant in `constants.py`.
