# WikiWriter — Implementation Spec

**Purpose:** Build guide for the prototype. Scoped to what is demoable and defensible.
**Not:** A PRD. No acceptance criteria, no phases, no policy framing.

---

## What We Are Building

A multi-agent Wikipedia editing assistant that:

1. Takes a Wikipedia article URL
2. Reads both the article content AND the human environment around it (edit history, talk page)
3. Produces a graded improvement plan
4. Spawns parallel workers to audit existing citations and find new sources
5. Drafts targeted edits grounded exclusively in verified sources
6. Runs a single critic (different model) to evaluate the draft
7. Shows its work live as it runs — every stage, every decision, visible in real time
8. Presents a final human review UI with diff, sources, and reasoning trace

The differentiating insight: **the system understands the article's editorial environment before deciding what to touch.** This is what separates it from a citation repair tool.

---

## Challenges Expected

The actual workflow is straightforward (even if there are a lot of moving parts), the risk is that we will not be *reliable*, due to:

- Inability to pull web page contents (CAPTCHAs, paywalls)
- Inability to process web page HTML (too messy!)
- Latency of LLM calls
- Latency of HTTP requests
- Running out of credits with OpenAI, Tavily, and other resources
- Code complexity getting out of control!

We need to make the system robust and also fast to iterate. That is why we have the caching system, during implementation caching is critical because it allows the test iterations to run quickly rather than take a long time we can skip to the next stage. However, it's critical that we cache properly: for instance if we cache an LLM response, we need to use (a hash of) the prompt as the key so that if we re-run the agent from the beginning, it doesn't have to call the same LLM prompt.

NOTE: We must also write defensive code with unit tests. That way, we know that each stage is working properly.
The most importnat unit tests are going to be around *planning*, because what will happen is that if we do not get a good plan - then we will not do the work properly. The plan is the core of the agentic workflow and it is what MAKES this an agent.


---

## Stack

```
UI:          Streamlit  (live progress + final review in one app)
Agent calls: OpenAI Python SDK
             - gpt-5.4-mini  →  all workers (draft, grade, plan, extract)
             - gpt-5.5       →  critic only (different model family)
Async:       asyncio + anyio (Streamlit-compatible async execution)
HTTP:        httpx  (async fetching for all external URLs)
Parsing:     beautifulsoup4  (HTML → readable text for source evaluation)
             mwparserfromhell  (wikitext parsing)
Wikipedia:   wikipedia-api  (Python wrapper for MediaWiki REST API)
             + direct MediaWiki API calls for edit history and talk pages
Web search:  tavily-python  (Tavily API — best for LLM-grounded search)
Wayback:     waybackpy  (Wayback Machine CDX + Availability API wrapper; no auth needed)
Caching:     diskcache  (persistent key-value cache; survives restarts)
Diffing:     difflib  (stdlib — unified diff of article text)
Config:      python-dotenv
Validation:  pydantic v2
```

**Why Streamlit over FastAPI + HTML:**
Streamlit's `st.status()`, `st.spinner()`, and incremental `st.write()` calls let you show live pipeline progress without any WebSocket plumbing. The agent's thought process is visible as it runs, not just at the end. This is dramatically better for a demo.

**Why diskcache over Redis/SQLite:**
Zero infrastructure. One `pip install`. Persistent across runs. Fast enough for a demo. The cache is a directory on disk — inspectable, clearable, no server to start.

**Why Tavily over Brave Search:**
Tavily is purpose-built for LLM research agents — it returns cleaned, structured content rather than raw HTML, which means source discovery workers can evaluate content quality without a separate fetch step for search results.

---

## Repository Structure

```
wikiwriter/
├── app.py                   # Streamlit app — UI + pipeline runner
├── orchestrator.py          # Pipeline coordinator; emits progress events
├── workers/
│   ├── article_grader.py    # Content quality scorer
│   ├── editorial_context.py # Edit history + talk page analyzer
│   ├── claim_extractor.py   # Sentence-level claim parser
│   ├── source_evaluator.py  # Unified: fetch + read + grade any URL
│   ├── source_discovery.py  # New source finder (wraps Tavily + evaluator)
│   ├── draft_writer.py      # Section editor
│   ├── critic.py            # Evaluator — gpt-5.4
│   └── output_grader.py     # Scores final draft, same rubric as grader
├── tools/
│   ├── wikipedia.py         # MediaWiki API: article, history, talk page
│   ├── wayback.py           # waybackpy wrapper — newest snapshot lookup for dead URLs
│   ├── search.py            # Tavily wrapper
│   └── fetcher.py           # httpx fetch → BeautifulSoup → clean text (should cache both raw HTML and clean text!)
├── cache.py                 # diskcache setup and helpers
├── models.py                # Pydantic schemas for all worker I/O
├── prompts/                 # One .txt file per worker
│   ├── article_grader.txt
│   ├── editorial_context.txt
│   ├── claim_extractor.txt
│   ├── source_evaluator.txt
│   ├── source_discovery.txt
│   ├── draft_writer.txt
│   ├── critic.txt
│   └── output_grader.txt
├── .env
└── requirements.txt
```

---

## External APIs and Python Packages

### APIs Required

| API | Purpose | Auth | Cost |
|-----|---------|------|------|
| **OpenAI API** | All LLM calls | `OPENAI_API_KEY` | Pay per token |
| **Tavily API** | Web search for source discovery | `TAVILY_API_KEY` | Free tier: 1000 searches/month |
| **MediaWiki REST API** | Article content, edit history, talk pages | None — public | Free |
| **Wayback Machine CDX API** | Check archived snapshots of dead URLs (via waybackpy) | None — public | Free |

### Python Packages

```
# requirements.txt

# Core
openai>=2.35.0             # OpenAI SDK
streamlit>=1.35.0          # UI + live progress
pydantic>=2.0.0            # Typed data models
python-dotenv>=1.0.0       # .env loading

# HTTP + parsing
httpx>=0.27.0              # Async HTTP client
beautifulsoup4>=4.12.0     # HTML parsing for source content extraction
lxml>=5.0.0                # Fast HTML parser (bs4 backend)
mwparserfromhell>=0.6.6    # Wikitext parsing

# Wikipedia
wikipedia-api>=0.6.0       # MediaWiki REST API wrapper

# Wayback Machine
waybackpy>=3.0.6           # Wayback CDX + Availability API — check archived snapshots
                           # of dead citation URLs; no auth required

# Search
tavily-python>=0.3.0       # Tavily search client

# Caching
diskcache>=5.6.0           # Persistent disk-based cache

# Utilities
difflib                    # stdlib — no install needed
anyio>=4.0.0               # Async compatibility layer for Streamlit
```

---

## Caching System

All expensive external operations are cached. The cache key is always a deterministic hash of the inputs so identical requests never hit the network twice.

When caching LLM outputs, we should create the cache key as a hash of: model name, prompt, input parameters (e.g. page contents)

The actual cached value should be a python dictionary which has the non-hashed inputs (so we can have observability into what we are looking at in the cache) and then "cached_value" which stores what we are actually caching. 

```python
# cache.py

import diskcache
import hashlib, json

cache = diskcache.Cache(".wikiwriter_cache")

def cache_key(*args) -> str:
    """Deterministic cache key from any inputs."""
    payload = json.dumps(args, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()

def cached(namespace: str):
    """Decorator: cache the result of any async function."""
    def decorator(fn):
        async def wrapper(*args, **kwargs):
            key = f"{namespace}:{cache_key(*args, **kwargs)}"
            if key in cache:
                return cache[key]
            result = await fn(*args, **kwargs)
            cache[key] = result
            return result
        return wrapper
    return decorator
```

### What Gets Cached and Why

| Cache Namespace | What | TTL | Reason |
|----------------|------|-----|--------|
| `page_fetch` | Raw HTML of any fetched URL | 7d | Fetching the same source URL in two different pipeline runs should not hit the network twice |
| `page_text` | BeautifulSoup-cleaned text of a fetched page | 7d | Parsing is cheap but redundant if fetch is cached |
| `source_eval` | Full LLM source evaluation of a URL | 7d | Source quality of a given URL is stable over days; no reason to re-evaluate |
| `wayback` | Wayback Machine availability result for a URL | 7d | The archive either has it or it doesn't |
| `wiki_article` | Full article wikitext | 1h | Articles change; shorter TTL |
| `wiki_history` | Edit history (last 500 edits) | 1h | Same |
| `wiki_talkpage` | Talk page content | 1h | Same |
| `search_results` | Tavily search results for a query | 48h | Same search query in the same session should not burn API quota |

Usage throughout the workers is transparent:

```python
# tools/fetcher.py

@cached("page_fetch")
async def fetch_url(url: str) -> str:
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        response = await client.get(url, headers={"User-Agent": "WikiWriter/1.0"})
        response.raise_for_status()
        return response.text

@cached("page_text")
async def fetch_readable(url: str) -> str:
    html = await fetch_url(url)
    soup = BeautifulSoup(html, "lxml")
    # Remove nav, footer, scripts, ads
    for tag in soup(["nav", "footer", "script", "style", "aside"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)[:8000]  # token budget
```

Notes on fetcher:

- It should fall back to Playwright if we get a CAPTCHA or if it is unable to render e.g. due to Javascript

---

## Source Evaluator — Unified Worker

There is no separate domain classifier tool. Any URL — whether an existing citation being audited or a candidate found during source discovery — goes through the same `SourceEvaluator` worker. The worker fetches the page, reads it, and asks an LLM to evaluate it holistically as a potential Wikipedia source.

Note that the source evaluator must ALSO extract relevant information from the page related to the article topic.

Further, if the source is a PDF (or if it is an article which has a PDF copy for download), then we must call another tool which translates the PDF into a text form so that we can extract information from the document.

```python
# workers/source_evaluator.py

class SourceEvaluator:
    """
    Unified source evaluation for any URL.
    Used by both source_audit (existing citations) and source_discovery (new candidates).
    All fetches are cached — evaluating the same URL twice costs nothing.
    """

    async def evaluate(
        self,
        url: str,
        claim: str,           # the specific claim this source should support
        context: str = "",    # surrounding article context for relevance assessment
    ) -> SourceEvaluation:

        # 1. Try to fetch the page
        try:
            page_text = await fetcher.fetch_readable(url)
            status = "LIVE"
        except httpx.HTTPStatusError:
            # Dead URL — check Wayback Machine for the most recent snapshot
            # waybackpy is synchronous; run in executor to avoid blocking the event loop
            loop = asyncio.get_event_loop()
            archive_url = await loop.run_in_executor(None, self._wayback_lookup, url)
            if archive_url:
                page_text = await fetcher.fetch_readable(archive_url)
                url = archive_url
                status = "ARCHIVED"
            else:
                return SourceEvaluation(url=url, status="DEAD", overall_score=0.0, ...)

        # 2. LLM evaluation — the whole page is passed to the model
        # The model assesses domain type, content quality, claim support, age, and authority
        # No separate domain lookup table needed
        result = await self.llm_evaluate(url, page_text, claim, context, status)
        return result

    def _wayback_lookup(self, url: str) -> str | None:
        """Synchronous waybackpy call — run via run_in_executor to stay async-safe."""
        from waybackpy import WaybackMachineAvailabilityAPI
        try:
            api = WaybackMachineAvailabilityAPI(url, user_agent="WikiWriter/1.0")
            snapshot = api.newest()
            return snapshot.archive_url
        except Exception:
            return None

    @cached("source_eval")
    async def llm_evaluate(self, url, page_text, claim, context, status) -> SourceEvaluation:
        prompt = self.prompts.source_evaluator.format(
            url=url,
            page_text=page_text,
            claim=claim,
            context=context,
            status=status,
        )
        response = await openai_call(model=DRAFT_MODEL, prompt=prompt)
        return SourceEvaluation.model_validate_json(response)
```

### Source Evaluator Prompt

```
You are evaluating a web page as a potential Wikipedia source. You must evaluate the claim considered here, AND output any additional claims which may be relevant to the article that we are editing.

URL: {url}
STATUS: {status}  (LIVE / ARCHIVED)

ARTICLE EDITING:
{article title}

CLAIM TO SUPPORT:
{claim}

ARTICLE CONTEXT:
{context}

PAGE CONTENT:
{page_text}

Evaluate this source on the following dimensions and score each 0-10:

1. domain_type: Classify the domain as one of:
   - academic (peer-reviewed journal, university repository, preprint server)
   - government (official government or intergovernmental body)
   - established_news (major news organization with documented editorial standards)
   - reference (established encyclopedia, dictionary, almanac)
   - specialist (trade publication, professional body, subject-specific outlet)
   - other_news (regional or smaller news outlet)
   - other (blog, forum, personal site, social media, self-published)
   Score: academic=10, government=9, established_news=7, reference=7,
          specialist=6, other_news=4, other=2

2. claim_support (0-10): Does this page directly support the specific claim stated above?
   Does it say what the claim asserts, or is the connection indirect / tangential?

3. age (0-10): How current is the content?
   Score based on: publication date visible in the page, recency of information.
   10 = current year, 8 = 1-2 years, 6 = 3-5 years, 4 = 6-10 years, 2 = >10 years
   For time-insensitive topics (historical facts, foundational science) penalize less.

4. credibility (0-10): Based on the actual page content:
   Does it cite its own sources? Is authorship clear? Is there editorial oversight?
   Does the writing demonstrate expertise? Any signs of bias or conflict of interest?

5. accessibility (0-10):
   10 = fully readable, 5 = partially paywalled, 2 = fully paywalled, 0 = dead

Overall score: weighted average (domain_type * 0.25 + claim_support * 0.35 +
               age * 0.15 + credibility * 0.15 + accessibility * 0.10)

Also note: author(s) if identifiable, publication name, publication date if visible,
and a one-sentence summary of what the page actually says about the claim.

Return only valid JSON:
{
  "domain_type": "...",
  "scores": {
    "domain_type": 0.0,
    "claim_support": 0.0,
    "age": 0.0,
    "credibility": 0.0,
    "accessibility": 0.0
  },
  "overall_score": 0.0,
  "author": "...",
  "publication": "...",
  "publication_date": "...",
  "claim_support_summary": "...",
  "recommendation": "USE / WEAK / REJECT",
  "further_claims": [
      <list of other relevant claims coming from this article>
  ]
}
```

Note that we should not use the "score" blindly, but we should have the LLM evaluate these signals on 3 axes: trustworthiness, accuracy, relevance

---

## Live Progress with Streamlit

The demo cannot silently process and then show a result. Every stage must be visible as it runs. Streamlit's `st.status()` and streaming patterns make this straightforward.

### Progress Architecture

The orchestrator emits progress events via an async generator. The Streamlit app consumes them and renders each one immediately.

```python
# orchestrator.py  — yields progress events as it works

async def run(self, url: str):
    yield ProgressEvent(stage="FETCH", status="running", message=f"Fetching article: {url}")
    article = await self.tools.wikipedia.fetch(url)
    yield ProgressEvent(stage="FETCH", status="done", message=f"Loaded '{article.title}' — {len(article.sections)} sections, {len(article.citations)} citations")

    yield ProgressEvent(stage="INTAKE", status="running", message="Grading article quality and analyzing editorial environment (parallel)...")
    content_grade, editorial_risk = await asyncio.gather(
        self.workers.article_grader.run(article),
        self.workers.editorial_context.run(article)
    )
    yield ProgressEvent(stage="INTAKE", status="done",
        message=f"Content grade: {content_grade.letter_grade} ({content_grade.overall_score:.1f}/10) | Risk tier: {editorial_risk.risk_tier}",
        data={"grade": content_grade, "risk": editorial_risk}
    )

    yield ProgressEvent(stage="PLAN", status="running", message="Planning edits based on content grade and editorial risk...")
    plan = await self.workers.planner.run(article, content_grade, editorial_risk)
    yield ProgressEvent(stage="PLAN", status="done",
        message=f"Plan: editing {len(plan.sections_to_edit)} sections, excluding {len(plan.sections_excluded)} (risk/flip-flop)",
        data={"plan": plan}
    )

    # Source phase — emit one event per worker as it completes
    yield ProgressEvent(stage="SOURCES", status="running",
        message=f"Auditing {len(article.citations)} existing citations and searching for new sources (parallel)...")

    audit_tasks = [self.workers.source_evaluator.evaluate(c.url, c.claim) for c in article.citations]
    discovery_tasks = [self.workers.source_discovery.run(claim) for claim in uncited_claims]

    completed = 0
    total = len(audit_tasks) + len(discovery_tasks)
    async for result in as_completed_stream(audit_tasks + discovery_tasks):
        completed += 1
        yield ProgressEvent(stage="SOURCES", status="running",
            message=f"  [{completed}/{total}] Evaluated: {result.url[:60]}... → {result.recommendation} ({result.overall_score:.1f})",
            data={"source_result": result}
        )

    yield ProgressEvent(stage="SOURCES", status="done",
        message=f"Source audit complete. {dead_count} dead links, {weak_count} weak sources, {new_count} new sources found.")

    # Draft + critique
    yield ProgressEvent(stage="DRAFT", status="running", message=f"Drafting edits for {len(plan.sections_to_edit)} sections (parallel)...")
    # ... etc

    yield ProgressEvent(stage="CRITIQUE", status="running",
        message=f"Running critique (gpt-5.5)...")
    critique = await self.workers.critic.run(assembled_draft, source_report)
    yield ProgressEvent(stage="CRITIQUE", status="done",
        message=f"Critique verdict: {critique.overall_verdict}",
        data={"critique": critique}
    )
```

### Streamlit App Structure

```python
# app.py

import streamlit as st
import asyncio
from orchestrator import WikiWriterOrchestrator

st.set_page_config(page_title="WikiWriter", layout="wide")
st.title("WikiWriter")
st.caption("Quality-first Wikipedia editing agent")

url = st.text_input("Wikipedia article URL", placeholder="https://en.wikipedia.org/wiki/...")
run_button = st.button("Analyse & Draft Edit", type="primary")

if run_button and url:

    # ── LIVE PROGRESS PANEL ──────────────────────────────────
    st.subheader("Pipeline Progress")
    progress_container = st.container()

    stage_icons = {
        "FETCH": "🌐", "INTAKE": "📊", "PLAN": "🗺️",
        "SOURCES": "🔍", "DRAFT": "✏️", "CRITIQUE": "🔬", "GRADE": "📈"
    }
    stage_placeholders = {}
    for stage in stage_icons:
        stage_placeholders[stage] = progress_container.empty()

    # Collect final proposal for the review panel
    proposal = None
    partial_sources = []

    async def run_pipeline():
        nonlocal proposal, partial_sources
        orchestrator = WikiWriterOrchestrator()

        async for event in orchestrator.run(url):
            icon = stage_icons.get(event.stage, "•")
            placeholder = stage_placeholders[event.stage]

            if event.status == "running":
                placeholder.info(f"{icon} **{event.stage}** — {event.message}")
            elif event.status == "done":
                placeholder.success(f"{icon} **{event.stage}** — {event.message}")

            # Accumulate partial source results for live source list
            if event.data and "source_result" in event.data:
                partial_sources.append(event.data["source_result"])
                # Update a live source count
                progress_container.caption(f"Sources evaluated so far: {len(partial_sources)}")

            # Capture final proposal
            if event.data and "proposal" in event.data:
                proposal = event.data["proposal"]

    asyncio.run(run_pipeline())

    # ── FINAL REVIEW PANEL ───────────────────────────────────
    if proposal:
        st.divider()
        st.subheader("Edit Proposal")

        # Risk tier — shown first, prominent
        tier_colors = {"LOW": "green", "MODERATE": "orange", "HIGH": "red", "CRITICAL": "red"}
        risk = proposal.editorial_risk
        st.error(f"⚠️ Risk Tier: **{risk.risk_tier}**") if risk.risk_tier in ("HIGH", "CRITICAL") else \
        st.warning(f"Risk Tier: **{risk.risk_tier}**") if risk.risk_tier == "MODERATE" else \
        st.success(f"Risk Tier: **{risk.risk_tier}**")

        col1, col2, col3 = st.columns(3)
        col1.metric("Revert Rate (12mo)", f"{risk.revert_rate_12mo:.0%}")
        col2.metric("Flip-flopped Sections", len(risk.flip_flopped_sections))
        col3.metric("Dominant Editor", risk.dominant_editor or "None")

        if risk.editor_imposed_norms:
            with st.expander("Editor-imposed norms (from talk page)"):
                for norm in risk.editor_imposed_norms:
                    st.write(f"• {norm}")

        # Quality delta
        st.subheader("Quality")
        col1, col2, col3 = st.columns(3)
        col1.metric("Input Grade", proposal.input_grade.letter_grade,
                    f"{proposal.input_grade.overall_score:.1f}/10")
        col2.metric("Output Grade", proposal.output_grade.letter_grade,
                    f"{proposal.output_grade.overall_score:.1f}/10")
        col3.metric("Quality Delta", f"+{proposal.quality_delta:.1f}")

        # Improvement plan
        with st.expander("Improvement Plan", expanded=True):
            for section in proposal.improvement_plan.sections_to_edit:
                st.write(f"✅ **{section.name}** — {', '.join(section.modes)}")
            for section_name, reason in proposal.improvement_plan.exclusion_reasons.items():
                st.write(f"⛔ **{section_name}** — excluded: {reason}")

        # Sources
        tab1, tab2 = st.tabs(["Existing Citations", "New Sources"])
        with tab1:
            for s in proposal.source_audit:
                icon = "✅" if s.recommendation == "USE" else "⚠️" if s.recommendation == "WEAK" else "❌"
                st.write(f"{icon} `{s.domain_type}` [{s.overall_score:.1f}] {s.url}")
                if s.status in ("ARCHIVED", "DEAD"):
                    st.caption(f"   Status: {s.status}")
        with tab2:
            for s in proposal.new_sources:
                st.write(f"➕ `{s.domain_type}` [{s.overall_score:.1f}] {s.url}")
                st.caption(f"   Supports: {s.claim_support_summary}")

        # Diff
        with st.expander("Article Diff", expanded=True):
            st.code(proposal.full_diff, language="diff")

        # Critique
        verdict_color = {"PASS": "green", "REVISE": "orange", "DISCARD": "red"}
        st.subheader(f"Critique: {proposal.critique.overall_verdict}")
        for dimension, result in proposal.critique.dimension_results.items():
            icon = "✅" if result.verdict == "PASS" else "❌"
            st.write(f"{icon} **{dimension}**: {result.notes}")

        # Approve
        st.divider()
        st.subheader("Submit")
        st.text_area("Edit summary (copy this into Wikipedia)", proposal.disclosure_edit_summary)
        col1, col2 = st.columns(2)
        if col1.button("✅ Approve", type="primary"):
            st.success("Approved. Copy the edit summary above and submit manually to Wikipedia.")
        if col2.button("❌ Reject"):
            reason = st.text_input("Rejection reason (logged)")
            if reason:
                st.warning(f"Rejected: {reason}")
```

---

## Data Models

Every worker has typed input and output. No raw strings between workers.

```python
# models.py

class ProgressEvent(BaseModel):
    stage: str
    status: Literal["running", "done", "error"]
    message: str
    data: dict | None = None

class SourceEvaluation(BaseModel):
    url: str
    status: Literal["LIVE", "ARCHIVED", "DEAD"]
    domain_type: str
    scores: dict[str, float]
    overall_score: float
    author: str | None
    publication: str | None
    publication_date: str | None
    claim_support_summary: str
    recommendation: Literal["USE", "WEAK", "REJECT"]

class ContentGrade(BaseModel):
    overall_score: float
    letter_grade: str
    section_grades: dict[str, float]
    dimension_scores: dict[str, float]
    narrative: str

class EditorialRiskProfile(BaseModel):
    risk_tier: Literal["LOW", "MODERATE", "HIGH", "CRITICAL"]
    revert_rate_12mo: float
    edit_velocity: int
    dominant_editor: str | None
    flip_flopped_sections: list[str]
    active_disputes: list[dict]
    resolved_disputes: list[dict]
    editor_imposed_norms: list[str]
    wikiproject_affiliations: list[str]
    risk_narrative: str

class SectionPlan(BaseModel):
    name: str
    modes: list[str]
    rationale: str

class ImprovementPlan(BaseModel):
    sections_to_edit: list[SectionPlan]
    sections_excluded: list[str]
    exclusion_reasons: dict[str, str]
    narrative: str

class Claim(BaseModel):
    text: str
    status: Literal["cited", "undercited", "uncited", "consensus-uncited"]
    citation_id: str | None

class SectionDraft(BaseModel):
    section_name: str
    original_text: str
    revised_text: str
    changes_made: list[str]
    citations_added: list[str]
    citations_removed: list[str]

class DimensionCritique(BaseModel):
    verdict: Literal["PASS", "FAIL"]
    notes: str

class CritiqueResult(BaseModel):
    overall_verdict: Literal["PASS", "REVISE", "DISCARD"]
    dimension_results: dict[str, DimensionCritique]
    revision_instructions: list[str]
    discard_reason: str | None

class EditProposal(BaseModel):
    input_grade: ContentGrade
    output_grade: ContentGrade
    quality_delta: float
    editorial_risk: EditorialRiskProfile
    improvement_plan: ImprovementPlan
    source_audit: list[SourceEvaluation]
    new_sources: list[SourceEvaluation]
    section_drafts: list[SectionDraft]
    critique: CritiqueResult
    full_diff: str
    disclosure_edit_summary: str
```

---

## Orchestrator Logic

```python
# orchestrator.py

class WikiWriterOrchestrator:

    async def run(self, url: str):
        # Stage 1: Fetch
        yield ProgressEvent(stage="FETCH", status="running", message=f"Fetching {url}...")
        article = await self.tools.wikipedia.fetch(url)
        self.check_exclusions(article)
        yield ProgressEvent(stage="FETCH", status="done",
            message=f"Loaded '{article.title}' — {len(article.sections)} sections, {len(article.citations)} citations")

        # Stage 2: Parallel intake
        yield ProgressEvent(stage="INTAKE", status="running",
            message="Grading content quality and analyzing editorial environment (parallel)...")
        content_grade, editorial_risk = await asyncio.gather(
            self.workers.article_grader.run(article),
            self.workers.editorial_context.run(article)
        )
        yield ProgressEvent(stage="INTAKE", status="done",
            message=f"Grade: {content_grade.letter_grade} | Risk: {editorial_risk.risk_tier}",
            data={"grade": content_grade, "risk": editorial_risk})

        # Stage 3: Planning
        yield ProgressEvent(stage="PLAN", status="running", message="Planning edits...")
        plan = await self.workers.planner.run(article, content_grade, editorial_risk)

        if not plan.sections_to_edit:
            yield ProgressEvent(stage="PLAN", status="done",
                message="No sections worth editing given current risk profile. Recommend skip.")
            return

        yield ProgressEvent(stage="PLAN", status="done",
            message=f"Editing {len(plan.sections_to_edit)} sections, excluding {len(plan.sections_excluded)}",
            data={"plan": plan})

        # Stage 4: Claim extraction
        claim_map = await self.workers.claim_extractor.run(article, plan)
        uncited = [c for c in claim_map.claims if c.status in ("uncited", "undercited")]

        # Stage 5: Parallel source phase
        # All citation audits + all discovery searches run simultaneously
        yield ProgressEvent(stage="SOURCES", status="running",
            message=f"Auditing {len(article.citations)} citations + searching for {len(uncited)} uncited claims...")

        audit_tasks = [
            self.workers.source_evaluator.evaluate(c.url, c.claim_text)
            for c in article.citations
        ]
        discovery_tasks = [
            self.workers.source_discovery.run(claim.text, article.title)
            for claim in uncited
        ]

        all_results = await asyncio.gather(
            *audit_tasks, *discovery_tasks, return_exceptions=True
        )
        audit_results = [r for r in all_results[:len(audit_tasks)] if not isinstance(r, Exception)]
        discovery_results = [r for r in all_results[len(audit_tasks):] if not isinstance(r, Exception)]

        # Emit individual source results for live display
        for r in audit_results + discovery_results:
            yield ProgressEvent(stage="SOURCES", status="running",
                message=f"  {r.recommendation} [{r.overall_score:.1f}] {r.url[:70]}",
                data={"source_result": r})

        yield ProgressEvent(stage="SOURCES", status="done",
            message=f"Sources complete: {sum(1 for r in audit_results if r.recommendation=='USE')} usable existing, {len(discovery_results)} new candidates")

        source_report = self.assemble_source_report(audit_results, discovery_results)

        # Stage 6: Parallel drafting
        yield ProgressEvent(stage="DRAFT", status="running",
            message=f"Drafting {len(plan.sections_to_edit)} sections (parallel)...")
        draft_tasks = [
            self.workers.draft_writer.run(
                section=s,
                source_report=source_report,
                editor_norms=editorial_risk.editor_imposed_norms,
            )
            for s in plan.sections_to_edit
        ]
        section_drafts = [
            r for r in await asyncio.gather(*draft_tasks, return_exceptions=True)
            if not isinstance(r, Exception)
        ]
        assembled = self.assemble_full_draft(article, section_drafts)
        yield ProgressEvent(stage="DRAFT", status="done",
            message=f"Drafts complete for {len(section_drafts)} sections")

        # Stage 7: Critique loop (max 2 revisions)
        yield ProgressEvent(stage="CRITIQUE", status="running",
            message="Running critique (gpt-5.5)...")
        critique, final_draft = await self.critique_loop(assembled, source_report)
        yield ProgressEvent(stage="CRITIQUE", status="done",
            message=f"Verdict: {critique.overall_verdict}",
            data={"critique": critique})

        if critique.overall_verdict == "DISCARD":
            yield ProgressEvent(stage="CRITIQUE", status="error",
                message=f"Edit discarded: {critique.discard_reason}")
            return

        # Stage 8: Output grading
        yield ProgressEvent(stage="GRADE", status="running", message="Grading final output...")
        output_grade = await self.workers.output_grader.run(final_draft, article)
        delta = output_grade.overall_score - content_grade.overall_score
        yield ProgressEvent(stage="GRADE", status="done",
            message=f"Output grade: {output_grade.letter_grade} (Δ +{delta:.1f})")

        proposal = self.build_proposal(
            article, content_grade, output_grade, editorial_risk,
            plan, source_report, audit_results, discovery_results,
            section_drafts, critique, final_draft
        )
        yield ProgressEvent(stage="GRADE", status="done",
            message="Pipeline complete.", data={"proposal": proposal})

    async def critique_loop(self, draft, source_report, cycles=0):
        if cycles >= 2:
            return CritiqueResult(overall_verdict="DISCARD",
                discard_reason="Failed critique twice — fundamental issues not resolvable by revision"), draft
        critique = await self.workers.critic.run(draft, source_report)
        if critique.overall_verdict == "PASS":
            return critique, draft
        if critique.overall_verdict == "REVISE":
            revised = await self.workers.draft_writer.revise(draft, critique.revision_instructions, source_report)
            return await self.critique_loop(revised, source_report, cycles + 1)
        return critique, draft
```

---

## Parallelization — What Is Parallel and Why

| Stage | Parallel? | Why |
|-------|-----------|-----|
| Article Grader + Editorial Context Analyzer | ✅ Yes | Completely independent inputs. No shared state. Sequential would double intake latency. |
| Source Audit + Source Discovery | ✅ Yes | Citations and claim gaps are independent tasks. Both pools run simultaneously — no dependency between them. Cache means repeat URLs cost nothing. |
| Section Draft Writers | ✅ Yes | Sections are independent once the source report is assembled. Context isolation prevents cross-contamination. |
| Critique | ❌ No (v1) | Single critic in v1. Parallel dimension specialists are a future upgrade. |
| Synthesis Writer | ❌ No | Global pass — requires all section drafts first. Sequential by definition. |
| Output Grader | ❌ No | Requires the final draft. |

---

## The Genuinely Dynamic Behaviors

These are the points to articulate in the interview:

**1. Planner routing**
Two independent signals (content grade + editorial risk) produce a different edit scope for every article. HIGH risk + LOW content grade → narrow scope. CRITICAL risk → skip entirely. Flip-flopped sections excluded by default regardless of content grade. This is not a template.

**2. Runtime worker budget**
Source audit workers = number of citations in the article. Discovery workers = number of uncited/undercited claims found by the extractor. Both determined at runtime, not hardcoded.

**3. Critique loop termination**
Terminates at 0, 1, or 2 additional cycles depending on the critic's verdict. PASS exits immediately. Two failures force DISCARD. The path is genuinely conditional.

**4. Cache-aware execution**
If a source URL has been evaluated in a prior run, the evaluation is retrieved from disk instantly — no LLM call, no HTTP fetch. The system adapts its actual work to what has and hasn't been seen before.

---

## What to Build First (In Order)

Stop at any level — each is a complete, demoable artifact.

**Level 1 — Differentiating core** *(do this first)*
- Wikipedia fetch + article parsing
- Article grader (LLM)
- Editorial context analyzer (edit history + talk page)
- Planner (consumes both, produces risk-aware plan)
- Streamlit app showing live progress + risk profile + quality grade

*Why this alone stands out: no other demo reads the human environment before deciding what to touch.*

**Level 2 — Agentic behavior**
- Source evaluator (unified fetch + LLM grade)
- diskcache integration
- Parallel citation audit + source discovery
- Live source results in Streamlit as each worker completes

*Demonstrates: parallelization with clear justification + caching.*

**Level 3 — Full quality loop**
- Claim extractor
- Draft writer (section-level, parallel)
- Critic (gpt-5.5, different model)
- Diff view in Streamlit

*Demonstrates: evaluator-optimizer loop + cross-model critique.*

**Level 4 — Polish**
- Critique revision loop (max 2 cycles)
- Output grader + quality delta metric
- Pre-filled edit summary with disclosure tag
- Wayback Machine fallback for dead URLs

---

## Environment Variables

```bash
# .env
OPENAI_API_KEY=
DRAFT_MODEL=gpt-5.4-mini
CRITIC_MODEL=gpt-5.5          # must differ from DRAFT_MODEL
TAVILY_API_KEY=
CACHE_DIR=.wikiwriter_cache         # diskcache directory
CACHE_TTL_PAGE=86400                # 24h in seconds
CACHE_TTL_SOURCE_EVAL=604800        # 7 days in seconds
CACHE_TTL_WIKI=3600                 # 1h for article/history/talk page
```

---

## Interview Talking Points

**"Why Streamlit?"**
> The agent's value isn't just the final edit — it's the reasoning that produced it. Streamlit lets us show every stage as it runs: which sources passed, which were dead, what the planner decided to skip, what the critic flagged. That's the demo. A silent spinner followed by a result page throws all of that away.

**"Why a unified source evaluator rather than a domain lookup table?"**
> A lookup table can only classify domains it knows about. The evaluator reads the actual page and asks the model to assess domain type, content quality, age, credibility, and claim support together. It's more accurate for obscure or unfamiliar sources, and it produces a richer output — not just a tier but a summary of what the page actually says about the claim. The cache means we pay the cost once per URL.

**"Why diskcache?"**
> Fetching and evaluating a source URL is the most expensive operation in the pipeline — both in latency and API cost. If the same URL appears in two different articles, or if we re-run the pipeline on the same article during development, we should not be doing that work twice. diskcache gives us this for free with zero infrastructure.

**"Why multi-agent at all?"**
> Each worker has a distinct role that benefits from a clean context. Mixing citation verification with claim extraction with critique in a single prompt produces worse results than isolating them. The decomposition also makes parallelization natural — independent tasks run simultaneously without contaminating each other's context.

**"Why a different model for the critic?"**
> If the same model writes the draft and evaluates it, they share the same systematic tendencies. Using gpt-5.5 to critique work done by gpt-5.4-mini makes the critique genuinely adversarial. They are different model families with different training dynamics.

**"What makes this genuinely agentic?"**
> The planner makes a different decision for every article based on two independent signals. The worker budget is determined at runtime. The critique loop terminates conditionally. The cache changes which work actually gets done on any given run. These are not fixed templates — they are decisions made in response to what the system finds.

---

*WikiWriter Implementation Spec v2 — Build guide only. See wikiwriter-agent-prd.md for full requirements.*
