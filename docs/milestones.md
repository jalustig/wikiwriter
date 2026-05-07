# WikiWriter — Build Milestones

**Goal:** Full prototype, one-shot with Claude Code. Target: under 3 hours of coding.

**Principle:** Every milestone leaves the system in a runnable state. The Streamlit app is introduced at Milestone 3 and grows incrementally — it is never "not yet working." Each milestone has a concrete verification command.

---

## Test Fixtures

### Wikipedia Articles

| URL | Why useful |
|-----|-----------|
| `https://en.wikipedia.org/wiki/Madison,_Alabama` | City article; C-class; good for general pipeline testing |
| `https://en.wikipedia.org/wiki/Work%E2%80%93life_balance` | NPOV-sensitive topic; exercises tone and framing critique |
| `https://en.wikipedia.org/wiki/USS_Macomb` | Stub/short article; few citations; good for source discovery |
| `https://en.wikipedia.org/wiki/Service_star` | Short article; exercises claim extractor on sparse content |
| `https://en.wikipedia.org/wiki/Central_Texas` | Geographic stub; good for Section Expansion mode |
| `https://en.wikipedia.org/wiki/Wall_Street_crash_of_1929` | Rich article; many citations; good for source audit at scale |

### Local PDFs (for PDF extraction testing)
- `~/Documents/Library/Germany/Rosenthal.pdf`
- `~/Documents/Library/Lustig.pdf`

---

## Milestone 0 — Foundation
**Estimate: 15 min**

Project skeleton, shared infrastructure, Wikipedia fetch.

**Deliverables:**
- `requirements.txt` — all dependencies from spec
- `.env.example` — `OPENAI_API_KEY`, `TAVILY_API_KEY`, `DRAFT_MODEL`, `CRITIC_MODEL`, `CACHE_DIR`
- `models.py` — all Pydantic schemas: `WikiArticle`, `Citation`, `ContentGrade`, `EditorialRiskProfile`, `ImprovementPlan`, `SectionPlan`, `Claim`, `ClaimMap`, `SourceEvaluation`, `SectionDraft`, `CritiqueResult`, `EditProposal`, `ProgressEvent`
- `cache.py` — diskcache setup, `cache_key()`, `@cached()` decorator (standalone functions only)
- `tools/wikipedia.py` — fetch article wikitext (+ parse into `WikiArticle`), edit history (last 500 edits), talk page(s) including archives
- `tools/fetcher.py` — httpx only at this stage (Playwright added in M8); `@cached("page_fetch")`, `@cached("page_text")`
- `tools/wayback.py` — `waybackpy` newest-snapshot lookup via `run_in_executor`
- `tools/pdf.py` — stub only (raises `NotImplementedError`; implemented in M8)
- `tools/search.py` — Tavily wrapper, `@cached("search_results")`

**Verify with:**
```bash
python -c "
from tools.wikipedia import fetch_article
import asyncio
article = asyncio.run(fetch_article('https://en.wikipedia.org/wiki/Madison,_Alabama'))
print(article.title, len(article.citations), 'citations')
"
```
Expected: prints `Madison, Alabama` with citation count > 0.

---

## Milestone 1 — Article Grader
**Estimate: 20 min**

First LLM worker. Independently runnable.

**Deliverables:**
- `workers/article_grader.py` + `prompts/article_grader.txt` — 7-dimension rubric (citation coverage, citation quality, NPOV, prose quality, structural completeness, freshness, lead quality); returns `ContentGrade` with overall score, letter grade, section-level scores, dimension scores, narrative

**Verify with:**
```bash
python -c "
from tools.wikipedia import fetch_article
from workers.article_grader import ArticleGrader
import asyncio

async def run():
    article = await fetch_article('https://en.wikipedia.org/wiki/USS_Macomb')
    grade = await ArticleGrader().run(article)
    print(grade.letter_grade, grade.overall_score, grade.dimension_scores)

asyncio.run(run())
```
Expected: letter grade, score, and a populated `dimension_scores` dict with 7 keys.

---

## Milestone 2 — Editorial Context Analyzer
**Estimate: 25 min**

Second intake worker. Reads the *human* environment around the article.

**Deliverables:**
- `workers/editorial_context.py` + `prompts/editorial_context.txt` — edit history analysis (activity level, revert rate, flip-flop detection, editor concentration) + talk page analysis (active disputes, resolved disputes, editor-imposed norms, WikiProject affiliations, protection history); returns `EditorialRiskProfile` with risk tier

**Verify with:**
```bash
python -c "
from tools.wikipedia import fetch_article
from workers.editorial_context import EditorialContextAnalyzer
import asyncio

async def run():
    article = await fetch_article('https://en.wikipedia.org/wiki/Work%E2%80%93life_balance')
    risk = await EditorialContextAnalyzer().run(article)
    print(risk.risk_tier, 'flip-flops:', risk.flip_flopped_sections)
    print('norms:', risk.editor_imposed_norms)

asyncio.run(run())
```
Expected: risk tier and (for this article) likely MODERATE or HIGH.

---

## Milestone 3 — Planner + First Streamlit App
**Estimate: 30 min — most important milestone**

The planner completes the intake → plan loop. The Streamlit app appears here and runs end-to-end (intake + plan only at this stage; later milestones add panels to it).

**Deliverables:**
- `workers/planner.py` + `prompts/planner.txt` — consumes `ContentGrade` + `EditorialRiskProfile`, returns `ImprovementPlan`
- `app.py` — **first working Streamlit app**: URL input, live progress (FETCH → INTAKE → PLAN stages), editorial risk panel (risk tier, revert rate, flip-flop map, dominant editor, editor-imposed norms), quality grade panel (7 dimensions), and the plan visualization chart. Later milestones add panels without breaking this baseline.

**Plan visualization** (`render_plan_chart` in `app.py`): a Plotly horizontal bar chart — one row per article section, bars sized by quality score (0–10), color-coded by action status:
- Blue — section being edited, label shows assigned mode(s) (e.g. "✏️ Cite Add + Rewrite")
- Red — section excluded, label shows reason (e.g. "⛔ flip-flop")
- Green — section left unchanged (quality sufficient)

This chart is the centrepiece of the plan review. It gives the operator an immediate read of what the agent decided to touch and why, without reading the full narrative.

**Planner routing rules (must be in the prompt):**
- CRITICAL risk tier → `sections_to_edit = []`, reason in narrative; pipeline stops
- Flip-flopped sections → always excluded, regardless of content grade
- Low citation coverage → `Claim Attribution` mode
- Low citation quality / dead links → `Citation Repair` mode
- Low NPOV score → `Section Rewrite` mode
- Multiple failing dimensions → multiple modes on the same section

**Planner unit tests (run before wiring into the app):**

| Input | Expected |
|-------|---------|
| CRITICAL risk, any grade | `sections_to_edit = []` |
| LOW risk, section citation coverage 3/10 | Section included, `Claim Attribution` |
| LOW risk, section is flip-flopped | Section excluded |
| MODERATE risk, section NPOV 4/10 | Section included, `Section Rewrite` |
| LOW risk, all section grades ≥ 8/10 | Minimal or empty `sections_to_edit` |

**Verify with:**
```bash
streamlit run app.py
```
Enter `https://en.wikipedia.org/wiki/Service_star`. The app should show: live progress through FETCH → INTAKE → PLAN, the risk panel, and the plan visualization chart — one colored bar per article section, with edit mode labels on blue bars and exclusion reasons on red bars. No empty panels, no crashes.

---

## Milestone 4 — Source Layer
**Estimate: 30 min**

Citation auditing and source discovery. Adds two panels to the Streamlit app.

**Deliverables:**
- `workers/source_evaluator.py` + `prompts/source_evaluator.txt` — fetch URL (via fetcher, Wayback fallback on failure), LLM-evaluate on 5 dimensions, return `SourceEvaluation`; uses manual cache check (not `@cached` — instance method)
- `workers/source_discovery.py` + `prompts/source_discovery.txt` — Tavily search for specific claim, evaluate candidates with `SourceEvaluator`, return ranked `list[SourceEvaluation]`
- Add SOURCES stage to orchestrator (parallel audit + discovery)
- Add to `app.py`: SOURCES progress (live per-URL updates), "Existing Citations" tab, "New Sources" tab

**Verify with:**
```bash
streamlit run app.py
```
Enter `https://en.wikipedia.org/wiki/USS_Macomb`. Source audit should run (all citations evaluated in parallel, results appearing live), and new sources should appear for any uncited claims. Second run should be noticeably faster (cache hits).

**Cache verification:**
```bash
python -c "
from cache import cache
print(f'{len(cache)} cache entries')
"
```

---

## Milestone 5 — Claim Extractor
**Estimate: 15 min**

Sentence-level claim parsing. Feeds the source discovery worker with precision inputs.

**Deliverables:**
- `workers/claim_extractor.py` + `prompts/claim_extractor.txt` — parse article into `ClaimMap`; tag each claim as cited / undercited / uncited / consensus-uncited; consensus-uncited claims excluded from discovery queue
- Wire into orchestrator between PLAN and SOURCES stages
- Add claim map panel to `app.py`

**Verify with:**
```bash
python -c "
from tools.wikipedia import fetch_article
from workers.claim_extractor import ClaimExtractor
import asyncio

async def run():
    article = await fetch_article('https://en.wikipedia.org/wiki/Central_Texas')
    from models import ImprovementPlan, SectionPlan
    # dummy plan
    plan = ImprovementPlan(sections_to_edit=[], sections_excluded=[], exclusion_reasons={}, narrative='')
    claim_map = await ClaimExtractor().run(article, plan)
    by_status = {}
    for c in claim_map.claims:
        by_status.setdefault(c.status, []).append(c.text[:60])
    for status, claims in by_status.items():
        print(status, len(claims))

asyncio.run(run())
```
Expected: four status categories printed, with at least one `uncited` claim.

---

## Milestone 6 — Draft + Synthesis
**Estimate: 25 min**

The writing workers. Adds diff view to the Streamlit app.

**Deliverables:**
- `workers/draft_writer.py` + `prompts/draft_writer.txt` — section-level draft; `run(section, source_report, editor_norms)` → `SectionDraft`; `revise(assembled_draft, revision_instructions, source_report)` → `str` (REVISION_MODE flag in same prompt)
- `workers/synthesis_writer.py` + `prompts/synthesis_writer.txt` — integrates section drafts, sharpens lead, removes redundancy; introduces no new factual claims
- Add DRAFT + SYNTHESIS stages to orchestrator (parallel section drafts, then synthesis pass)
- Add to `app.py`: DRAFT progress, diff view (before/after with `difflib`)

**Verify with:**
```bash
streamlit run app.py
```
Enter `https://en.wikipedia.org/wiki/Service_star`. After the full pipeline (up to synthesis), the diff view should show actual changes to the article text with at least one inline citation added or modified.

---

## Milestone 7 — Critique + Output Grading
**Estimate: 20 min**

Full quality gate. Completes the pipeline end-to-end. Adds critique panel and quality delta to the app.

**Deliverables:**
- `workers/critic.py` + `prompts/critic.txt` — 7 dimensions (citation fidelity, NPOV, original research, encyclopedic tone, necessity/concision, internal consistency, source quality); uses `CRITIC_MODEL` (gpt-5.5); returns `CritiqueResult`; no knowledge of prior revision cycles in its context
- `workers/output_grader.py` + `prompts/output_grader.txt` — same rubric as article grader; returns `ContentGrade`
- Add CRITIQUE and GRADE stages to orchestrator, including critique loop (max 2 revisions: PASS exits, REVISE calls `draft_writer.revise()`, two FAILs → DISCARD)
- Add to `app.py`: critique transcript panel (verdict per dimension), quality delta metric (input grade → output grade → Δ), approve/reject actions, pre-filled edit summary with disclosure tag

**Full E2E verification:**
```bash
streamlit run app.py
```
Run all six test articles. For each:
- [ ] Pipeline completes without crashing
- [ ] Critique verdict is shown (PASS / REVISE / DISCARD)
- [ ] Quality delta is computed (output score − input score)
- [ ] Edit summary panel is populated with disclosure tag

**Article-specific checks:**
- `Wall_Street_crash_of_1929` — many citations; source audit should take longest; check cache on second run
- `Work–life_balance` — NPOV-sensitive; critic should flag any promotional language
- `USS_Macomb` — sparse citations; source discovery should find new sources

---

## Milestone 8 — Fetcher Hardening
**Estimate: 20 min**

Playwright fallback and PDF support. The pipeline already works without these; this makes it robust to real-world sources.

**Deliverables:**
- Update `tools/fetcher.py` — add Playwright fallback (headless Chromium via `playwright.async_api`); trigger when httpx returns 403/429 or `<body>` text < 200 chars
- Implement `tools/pdf.py` — pypdf text extraction, page-by-page join, 8000-char cap, cached under `page_text`
- Update `tools/fetcher.py` — detect `Content-Type: application/pdf` (and `.pdf` URL extension fallback), route to `tools/pdf.py`

**Setup required:** `playwright install chromium`

**Verify with:**
```bash
# PDF extraction
python -c "
from tools.pdf import extract_pdf_text
import asyncio
text = asyncio.run(extract_pdf_text('$HOME/Documents/Library/Lustig.pdf'))
print(text[:500])
"

# Playwright (test with a known JS-heavy source)
python -c "
from tools.fetcher import fetch_readable
import asyncio
text = asyncio.run(fetch_readable('https://www.jstor.org/stable/2726088'))
print(len(text), 'chars extracted')
"
```

**PDF source evaluator test:**
```bash
python -c "
from workers.source_evaluator import SourceEvaluator
import asyncio
result = asyncio.run(SourceEvaluator().evaluate(
    'file://$HOME/Documents/Library/Rosenthal.pdf',
    claim='German Jewish emigration in the 1930s',
))
print(result.domain_type, result.overall_score, result.recommendation)
"
```

---

## Milestone 9 — Integration + Hardening
**Estimate: 25 min**

Full test run across all test articles. Fix what breaks.

**Full test checklist:**

| Article | Check |
|---------|-------|
| `Madison, Alabama` | Pipeline completes; plan has ≥ 1 section to edit |
| `Work–life balance` | NPOV critique dimension fires on draft (likely) |
| `USS Macomb` | Source discovery finds ≥ 2 new sources for uncited claims |
| `Service star` | Claim extractor finds uncited claims in a short article |
| `Central Texas` | Section Expansion mode triggered (thin content) |
| `Wall Street crash of 1929` | Source audit handles 20+ citations; cache significantly speeds up re-run |

**Quality checks (across all articles):**
- [ ] Zero fabricated citations — every cited source was fetched and verified
- [ ] CRITICAL risk articles produce empty improvement plans
- [ ] Flip-flopped sections never appear in `sections_to_edit`
- [ ] Cache hit on second run of same article (LLM token cost is near-zero)
- [ ] REVISE verdict triggers a revision cycle (not immediate DISCARD)
- [ ] Output grade ≥ input grade on at least 4 of 6 test articles
- [ ] PDF sources extracted and graded (test with `Rosenthal.pdf` or `Lustig.pdf` as a cited source URL)

---

## Total Estimate: ~3h 05min

| Milestone | Estimate | Runnable after? |
|-----------|----------|-----------------|
| 0 — Foundation | 15 min | `python tools/wikipedia.py` |
| 1 — Article Grader | 20 min | `python workers/article_grader.py` |
| 2 — Editorial Context | 25 min | `python workers/editorial_context.py` |
| 3 — Planner + Streamlit | 30 min | `streamlit run app.py` (intake + plan) |
| 4 — Source Layer | 30 min | `streamlit run app.py` (+ sources) |
| 5 — Claim Extractor | 15 min | `python workers/claim_extractor.py` |
| 6 — Draft + Synthesis | 25 min | `streamlit run app.py` (+ diff) |
| 7 — Critique + Grading | 20 min | `streamlit run app.py` (full pipeline) |
| 8 — Fetcher Hardening | 20 min | PDF + Playwright tests |
| 9 — Integration | 25 min | All test articles |
| **Total** | **~3h 05min** | |

### If time pressure hits, cut in this order:

1. **M8 (Playwright + PDF)** — defer; httpx-only still works for most sources
2. **Synthesis writer** — replace with simple section concatenation; mark TODO
3. **Critique revision loop** — single critique pass; REVISE verdict treated as DISCARD

Each cut keeps the pipeline runnable end-to-end.

---

## Deferred (Not in Prototype)

Corresponding to PRD Phases 3–4:

- **DAG execution engine** — `asyncio.gather` does the job for the prototype
- **Similar article finder** — PRD Phase 4
- **Contradiction analysis** — PRD Phase 4
- **Contradiction Integration and Full Article Rewrite edit modes** — PRD Phase 4
- **Parallel critique workers** (one per dimension) — PRD Phase 3; single critic in v1
- **Quality reporting dashboard** — PRD Phase 5
- **Audit log persistence** — PRD Phase 5 (results visible in UI only)
