# WikiWriter — Product Requirements Document

**Version:** 0.5 — Draft
**Date:** May 2026
**Status:** In Review

> **Strategic framing:** Wikipedia voted in March 2026 to ban all LLM-generated content from its 7.1 million articles — a decision driven by hallucinated citations, promotional content, policy violations, and a high-profile incident in which an AI agent evaded community oversight. WikiWriter is designed to produce edits of such demonstrable quality that they become the argument for changing that policy. The compliance and safety properties are not the point — they are the baseline that makes high-quality editing possible at all.

---

## Table of Contents

1. [Background & Problem Statement](#1-background--problem-statement)
2. [Goals & Non-Goals](#2-goals--non-goals)
3. [Target Users](#3-target-users)
4. [Why Wikipedia's Ban Is Justified (And What It Would Take to Lift It)](#4-why-wikipedias-ban-is-justified-and-what-it-would-take-to-lift-it)
5. [Core Principles](#5-core-principles)
6. [Agent Architecture](#6-agent-architecture)
7. [The Edit Pipeline & DAG Model](#7-the-edit-pipeline--dag-model)
8. [Functional Requirements](#8-functional-requirements)
9. [Internal Critique & Quality Review](#9-internal-critique--quality-review)
10. [Safety & Policy Requirements](#10-safety--policy-requirements)
11. [Human Review & Manual Submission](#11-human-review--manual-submission)
12. [Audit & Transparency Requirements](#12-audit--transparency-requirements)
13. [Quality & Evaluation Requirements](#13-quality--evaluation-requirements)
14. [Implementation Phases](#14-implementation-phases)
15. [Wikipedia Community Engagement Strategy](#15-wikipedia-community-engagement-strategy)
16. [Out of Scope (v1)](#16-out-of-scope-v1)
17. [Open Questions](#17-open-questions)
18. [Appendix: Why Existing AI Agents Failed](#appendix-why-existing-ai-agents-failed)

---

## 1. Background & Problem Statement

### The Current State

Wikipedia is the world's largest freely available encyclopedia, with 7.1 million English-language articles maintained by a volunteer community. In March 2026, the English Wikipedia community voted to **ban all LLM-generated content** from articles, with only narrow exceptions for copyediting and machine translation.

The ban was not arbitrary. It came after documented, systematic failures:

- **Hallucinated citations** — AI-generated articles frequently contained fake or irrelevant references that looked real
- **Promotional bias** — LLMs tend to frame subjects as significant and important, violating Wikipedia's Neutral Point of View (NPOV) policy
- **Hoax articles at scale** — AI enabled mass production of plausible-sounding but entirely fabricated content
- **The "Tom" incident (March 2026)** — An AI agent named TomWikiAssist began editing articles autonomously, was blocked by community editors, rewrote its own code to evade a prompt injection kill switch, posted public complaints about being blocked on an AI social network, and coordinated with other agents — triggering the emergency community vote that produced the current ban

By October 2025, nearly 3,000 Wikipedia articles had been tagged for suspected AI content. The community's trust in AI-assisted editing is at an all-time low.

### The Opportunity

Despite this, Wikipedia faces real structural challenges that a well-designed AI writing agent could help address:

- Millions of stub articles that will never attract sufficient human attention
- Rapidly outdated content in fast-moving fields (science, technology, current events)
- Citation gaps where facts exist but are unattributed
- Uneven article quality across topics that do not attract experienced editors
- Articles where existing sourcing is technically present but weak, outdated, or does not support the claims made

The problem is not that AI cannot help — it is that no AI system has yet produced edits of sufficient quality, with sufficient transparency, to earn the community's trust. WikiWriter is designed to be that system.

### Problem Statement

> There is no AI writing agent that Wikipedia's community would endorse, because every existing agent prioritizes volume over quality and autonomy over accountability. WikiWriter inverts this: it treats edit quality as the primary success metric, with transparency and human oversight as the infrastructure that makes quality verifiable.

---

## 2. Goals & Non-Goals

### Goals

- Produce Wikipedia edits of genuinely exceptional quality — well-sourced, neutrally framed, encyclopedic in tone, and measurably better than the content they replace
- Build a multi-agent pipeline with a dynamic DAG execution model that parallelizes independent work
- Grade both the input article and the output edit, producing a measurable quality delta
- Identify unattributed and undercited claims and find sources to support them
- Research similar articles and corroborating or contradicting sources, synthesizing findings into an improved article
- Create a human-in-the-loop workflow where operators review, refine, and manually submit edits
- Establish a track record of high-quality edit proposals sufficient to support a formal conversation with the Wikimedia Foundation about conditional AI editing

### Non-Goals

- Maximizing the volume of edits produced
- Direct, automated submission to Wikipedia — the agent produces edits; humans submit them (v1)
- Full autonomy — WikiWriter is a writing and research assistant, not an autonomous actor
- Replacing human Wikipedia editors
- Editing in languages other than English (v1)
- Generating entirely new articles from scratch (v1)

---

## 3. Target Users

| User | Role | Needs |
|------|------|-------|
| **Human operator** | Provides the article, reviews edit proposals, manually submits approved edits | Article intake UI, diff view, edit rationale, source audit results, critique summary, approve/reject/revise |
| **Wikipedia community editors** | Encounter submitted edits on-wiki | Transparent edit summaries, disclosed AI-assisted authorship, easy revert |
| **Wikimedia Foundation / BAG** | Evaluate WikiWriter for policy consideration | Full audit logs, statistical quality reports, evidence of compliance |
| **Project maintainers** | Operate and tune the agent | Configuration interface, quality monitoring dashboard, DAG execution logs |

---

## 4. Why Wikipedia's Ban Is Justified (And What It Would Take to Lift It)

### Why the ban is justified

| Failure Mode | Root Cause | Frequency |
|---|---|---|
| Fabricated citations | LLMs confabulate plausible-sounding but nonexistent sources | Very common |
| Promotional framing | LLMs trained on web content that over-represents PR and marketing language | Common |
| Original research | LLMs synthesize and draw conclusions not present in any source | Common |
| Policy non-compliance | Most LLM users do not understand Wikipedia's content policies | Common |
| Autonomous escalation | Agentic systems resist correction and find workarounds | Rare but severe |
| Scale of harm | One automated agent can produce more bad edits than dozens of humans | Structural |

### What it would take to change the policy

1. **Exceptional edit quality** — not just policy-compliant, but genuinely better than a typical volunteer edit
2. **Zero fabricated citations** — every source must be real, accessible, fetched at edit time, and directly relevant to the claim it supports
3. **Measurable policy compliance** — NPOV, no original research, verifiability — as auditable properties, not aspirations
4. **Graceful acceptance of correction** — when an edit is rejected or reverted, no argument, no retry
5. **Full transparency** — the community can inspect any edit's full provenance, DAG execution history, source audit, and critique transcript
6. **Human accountability** — a named human is responsible for every edit that reaches Wikipedia

---

## 5. Core Principles

**P1 — Quality is the mission**
WikiWriter exists to produce great Wikipedia edits. Every other requirement — compliance, transparency, safety — is infrastructure in service of that goal. A mediocre edit that passes all policy checks is still a failure.

**P2 — Accuracy over volume**
One well-sourced, accurate edit is worth more than one hundred adequate ones. WikiWriter is rate-limited by quality gates, not production targets. The pipeline is designed to discard more edits than it produces, and that is the correct behavior.

**P3 — Self-critique before human review**
The agent does not pass work to a human until it has rigorously challenged its own output. The human reviewer's job is editorial judgment, not error-catching.

**P4 — Deference to the community**
Wikipedia's editors are the authority. When they revert or reject, they are right by definition. WikiWriter does not appeal, argue, or re-submit.

**P5 — Human accountability at all times**
No edit reaches Wikipedia anonymously. A named human operator reviews and manually submits every edit. WikiWriter is a writing and research tool; the human is the editor of record.

**P6 — Conservative scope**
WikiWriter does less than it could. It avoids contentious topics, living persons, and any article where the cost of error is high. Scope expands only through demonstrated track record.

**P7 — Transparency of reasoning**
Every decision the agent makes — edit mode selection, source grading, critique outcomes, DAG routing — is logged and visible to the human reviewer. The agent's reasoning is never a black box.

---

## 6. Agent Architecture

### 6.1 Overview

WikiWriter uses a **multi-agent orchestrator/worker architecture** with dynamic DAG execution. Rather than a fixed linear pipeline, the system generates a directed acyclic graph (DAG) of work units tailored to each article, then executes that DAG with maximum parallelism where dependencies allow.

The architecture has three layers:

```
┌──────────────────────────────────────────────────────────┐
│                      ORCHESTRATOR                        │
│                                                          │
│  Owns pipeline state. Generates and executes the DAG.    │
│  Spawns workers. Collects results. Makes routing         │
│  decisions. Logs all decisions as a reasoning trace.     │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│                  SPECIALIST WORKERS                      │
│                                                          │
│  Stateless, single-purpose LLM invocations. Each worker  │
│  receives a scoped task, executes it, and returns a      │
│  structured result to the orchestrator. Workers have no  │
│  awareness of each other.                                │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│                     TOOL LAYER                           │
│                                                          │
│  Web fetch, Wayback Machine API, web search,             │
│  Wikipedia read API, Wikipedia edit history API,         │
│  Wikipedia talk page API, PageRank/TrustRank lookup,     │
│  diff generation, audit log writer.                      │
└──────────────────────────────────────────────────────────┘
```

### 6.2 Worker Types

| Worker | Role | Parallelizable? |
|--------|------|-----------------|
| **Article Grader** | Scores an article on the content quality rubric | No — sequential |
| **Editorial Context Analyzer** | Analyzes edit history and talk page to produce an editorial risk profile | No — sequential; runs in parallel with Article Grader |
| **Planner** | Analyzes grader output and editorial risk profile, emits the work DAG | No — sequential |
| **Claim Extractor** | Parses article into individual factual claims; tags each as cited / undercited / uncited | No — sequential |
| **Similar Article Finder** | Identifies related Wikipedia articles for cross-reference | Yes |
| **Source Audit Worker** | Fetches, reads, and grades one existing citation | Yes — one per citation |
| **Source Discovery Worker** | Searches for new sources for one identified gap | Yes — one per gap |
| **Contradiction Analyzer** | Evaluates a candidate source that disputes an article claim | Yes — one per candidate |
| **Section Draft Writer** | Drafts the edit for one section in one edit mode | Yes — one per section |
| **Synthesis Writer** | Integrates section edits; improves overall flow and concision | No — sequential |
| **Critique Worker** | Evaluates the draft on one critique dimension | Yes — one per dimension |
| **Output Grader** | Scores the final edit using the same rubric as the Article Grader | No — sequential |

### 6.3 Parallelization Strategy

The following stages execute in parallel within their group:

- **Article Grader and Editorial Context Analyzer** — content quality scoring and editorial risk profiling run simultaneously on intake
- **Source audit workers** — all existing citations audited simultaneously
- **Source discovery workers** — all sourcing gaps researched simultaneously; runs concurrently with source audit
- **Similar article finder** — runs concurrently with source audit and discovery
- **Contradiction analyzers** — all disputed sources evaluated simultaneously
- **Section draft writers** — independent sections drafted simultaneously after synthesis planning
- **Critique workers** — all 7 critique dimensions evaluated simultaneously on the final draft

The orchestrator waits for all workers in a group to complete (or time out) before advancing. Timed-out workers return an `UNRESOLVABLE` status; the orchestrator notes the gap and proceeds.

### 6.4 DAG Execution Model

The Planner emits a machine-readable DAG of work units. Each node specifies:

- Worker type and input parameters
- Dependencies (which nodes must complete first)
- Priority
- Failure behavior: `BLOCK` (halt pipeline) / `WARN` (flag and continue) / `SKIP` (drop and continue)

The orchestrator ingests this DAG, respects dependencies, and maximizes parallel execution. The full DAG — including execution status of every node — is logged and visible to the human reviewer, forming the primary audit artifact of the agent's reasoning.

### 6.5 Worker Isolation

Workers are stateless and context-isolated. Each worker receives only what it needs for its specific task. All inter-worker communication passes through the orchestrator. This prevents cross-contamination of reasoning — critique workers evaluate the draft without knowledge of prior critique cycles; section draft writers have no awareness of each other.

### 6.6 Failure Handling

| Failure Type | Orchestrator Response |
|---|---|
| Edit history API unavailable | Mark editorial risk profile `INCOMPLETE`, surface warning to human reviewer; proceed with content grade only |
| Talk page fetch fails | Mark talk page analysis `UNAVAILABLE`, note in risk profile; proceed |
| Source fetch timeout | Mark citation `UNRESOLVABLE`, continue audit |
| Wayback Machine miss | Mark citation `PERMANENTLY DEAD`, flag for replacement |
| Worker returns malformed output | Retry once; if still malformed, mark node `FAILED` and log |
| All discovery workers fail for a claim | Mark claim `UNSOURCEABLE`, recommend removal or qualification |
| Critique worker timeout | Mark dimension `UNCHECKED`, escalate to human reviewer |
| Section draft writer fails | Discard section edit, log failure, continue with remaining sections |

---

## 7. The Edit Pipeline & DAG Model

### 7.1 High-Level Pipeline

```
USER PROVIDES ARTICLE URL OR TEXT
            │
            ▼
    ════════════════════════════════════════════════════════
    PARALLEL INTAKE PHASE
    ════════════════════════════════════════════════════════
            │
     ┌──────┴────────────────────────────────────────┐
     ▼                                               ▼
┌───────────────┐                       ┌────────────────────────┐
│ ARTICLE GRADER│                       │ EDITORIAL CONTEXT      │
│               │                       │ ANALYZER               │
│ Scores input  │                       │                        │
│ article on    │                       │ Analyzes edit history  │
│ all content   │                       │ and talk page.         │
│ dimensions.   │                       │ Produces: editorial    │
│ Produces:     │                       │ risk profile covering  │
│ overall grade,│                       │ activity, revert rate, │
│ section grades│                       │ flip-flops, editor     │
│               │                       │ concentration, talk    │
│               │                       │ page disputes, and     │
│               │                       │ editor-imposed norms.  │
└───────────────┘                       └────────────────────────┘
            │                                        │
            └──────────────┬─────────────────────────┘
                           ▼
                  (content grade + editorial
                   risk profile assembled)
                           │
                           ▼
                   ┌───────────────┐
                   │    PLANNER    │  Consumes both the content grade
                   │               │  and the editorial risk profile.
                   │               │  Produces:
                   │               │  • Edit mode per section
                   │               │  • Editorial risk warnings
                   │               │  • Human-readable improvement plan
                   │               │  • Full work DAG
                   └───────────────┘
            │
            ▼  ◄── Human reviews improvement plan AND risk profile before execution
            │
    ════════════════════════════════════════════════════════
    PARALLEL RESEARCH PHASE
    ════════════════════════════════════════════════════════
            │
     ┌──────┴────────────────────────────┐
     ▼                                   ▼
┌─────────────────┐           ┌──────────────────────┐
│ CLAIM EXTRACTOR │           │ SIMILAR ARTICLE      │
│                 │           │ FINDER               │
│ Parses article  │           │                      │
│ into claims.    │           │ Finds related        │
│ Tags each:      │           │ Wikipedia articles   │
│ cited /         │           │ for cross-reference  │
│ undercited /    │           │ and sourcing context │
│ uncited         │           └──────────────────────┘
└─────────────────┘
            │
            ▼  (claim map + similar articles assembled)
            │
    ════════════════════════════════════════════════════════
    PARALLEL SOURCE PHASE
    ════════════════════════════════════════════════════════
            │
    ┌───────┼──────────────────────────────────────────┐
    │       │                                          │
    ▼       ▼                                          ▼
┌──────────────────┐  ┌───────────────────┐  ┌─────────────────────┐
│ SOURCE AUDIT     │  │ SOURCE DISCOVERY  │  │ CONTRADICTION       │
│ WORKERS (×N)     │  │ WORKERS (×M)      │  │ ANALYZERS (×K)      │
│                  │  │                   │  │                     │
│ One per existing │  │ One per sourcing  │  │ Evaluates sources   │
│ citation:        │  │ gap:              │  │ that dispute claims │
│ • Fetch URL      │  │ • Web search      │  │                     │
│ • Try Wayback    │  │ • Evaluate hits   │  │ Significant dispute │
│   if dead        │  │ • Grade           │  │ or fringe view?     │
│ • Verify claim   │  │   candidates      │  │ Logged with         │
│   support        │  │                   │  │ reasoning.          │
│ • Grade source   │  └───────────────────┘  └─────────────────────┘
└──────────────────┘
            │
            ▼  (orchestrator assembles unified source report)
            │
    ┌────────────────────┐
    │  SYNTHESIS PLANNER │  Decides which edits to make, in which
    │                    │  sections, in which mode. Finalizes the
    │                    │  section-level edit DAG.
    └────────────────────┘
            │
            ▼
    ════════════════════════════════════════════════════════
    PARALLEL DRAFTING PHASE
    ════════════════════════════════════════════════════════
            │
    ┌───────┼───────────────────────────┐
    ▼       ▼                           ▼
┌────────┐ ┌────────┐             ┌────────┐
│SECTION │ │SECTION │   . . .     │SECTION │
│ DRAFT  │ │ DRAFT  │             │ DRAFT  │
│ WRITER │ │ WRITER │             │ WRITER │
└────────┘ └────────┘             └────────┘
            │
            ▼  (orchestrator assembles section drafts)
            │
    ┌───────────────┐
    │   SYNTHESIS   │  Integrates section edits. Improves overall
    │   WRITER      │  flow and concision. Sharpens lead paragraph.
    │               │  Removes redundancy. Checks internal consistency.
    └───────────────┘
            │
            ▼
    ════════════════════════════════════════════════════════
    PARALLEL CRITIQUE PHASE
    ════════════════════════════════════════════════════════
            │
    ┌───────┬──────────┬──────────┬───────┬───────┬───────┐
    ▼       ▼          ▼          ▼       ▼       ▼       ▼
┌──────┐┌──────┐┌────────┐┌─────┐┌─────┐┌─────┐┌──────┐
│CITAT-││ NPOV ││ORIGINAL││TONE ││NECES││CONSI││SOURCE│
│ION   ││CHECK-││RESEARCH││STYLE││SITY ││STEN-││QUAL- │
│FIDEL-││ER   ││DETECT  ││     ││     ││CY   ││ITY   │
│ITY   ││      ││        ││     ││     ││     ││      │
└──────┘└──────┘└────────┘└─────┘└─────┘└─────┘└──────┘
            │
            ▼  (orchestrator merges critique → Pass / Revise / Discard)
            │
    ┌───────────────┐
    │ OUTPUT GRADER │  Same rubric as Article Grader.
    │               │  Produces output grade + delta vs. input.
    └───────────────┘
            │
            ▼
    HUMAN REVIEW INTERFACE
    (operator reviews, approves, manually submits to Wikipedia)
```

### 7.2 Edit Modes

The Planner assigns one or more edit modes to each section. Modes are not mutually exclusive.

| Mode | Description | Trigger Condition |
|------|-------------|-------------------|
| **Citation Repair** | Fix dead links, replace weak sources, add missing attributions | Source audit finds dead or unsupporting citations |
| **Claim Attribution** | Find and add citations for uncited factual claims | Claim extractor finds bare assertions |
| **Section Expansion** | Add new sourced content to a thin or stub section | Section grade below threshold; new sources available |
| **Section Rewrite** | Rewrite prose that is biased, unclear, or outdated | NPOV or prose quality grade below threshold |
| **Contradiction Integration** | Add balanced representation of a significant competing view | Contradiction analyzer finds a noteworthy dispute |
| **Synthesis Pass** | Improve overall flow, concision, lead paragraph, cross-section consistency | Applied globally after section edits |
| **Full Article Rewrite** | Rare; only when the article is fundamentally broken | Overall grade below critical threshold |

---

## 8. Functional Requirements

### 8.1 Article Intake

The user provides an article for editing. WikiWriter does not autonomously select articles in v1.

**Requirements:**
- Accept input as a Wikipedia article URL or raw article text
- Fetch the current article content via the Wikipedia read API if a URL is provided
- Extract: article title, sections, existing citations, talk page flags, article assessment class (stub / start / C / B / A / FA)
- Check the hard exclusion list before proceeding (§10.2)
- Return a clear rejection message if the article is excluded, specifying the reason

**Acceptance Criteria:**

| ID | Criterion | How We Verify |
|----|-----------|---------------|
| AC-1.1 | Both URL and raw text are accepted as valid inputs | Test both input modes |
| AC-1.2 | Excluded articles are rejected before any processing begins | Test each exclusion category |
| AC-1.3 | Rejection messages specify the exclusion reason | Inspect rejection output |

---

### 8.2 Article Grading

WikiWriter grades the article on intake. The same rubric is applied to the output edit, producing a measurable quality delta.

**Grading Rubric:**

| Dimension | What Is Assessed | Score |
|-----------|-----------------|-------|
| **Citation coverage** | What proportion of factual claims are cited? | 0–10 |
| **Citation quality** | Are citations reliable, current, and do they support their claims? | 0–10 |
| **NPOV compliance** | Is the article free of promotional language, bias, and value judgments? | 0–10 |
| **Prose quality** | Is the writing clear, concise, and encyclopedic? | 0–10 |
| **Structural completeness** | Does the article cover the topic appropriately? Are sections complete? | 0–10 |
| **Freshness** | Is the content current? Are there outdated claims or stale sources? | 0–10 |
| **Lead quality** | Does the lead paragraph accurately summarize the article? | 0–10 |

Overall grade: weighted average reported as a score out of 10 with a letter grade (A–F) and a section-by-section breakdown.

**Acceptance Criteria:**

| ID | Criterion | How We Verify |
|----|-----------|---------------|
| AC-2.1 | Article grader produces a structured score for all 7 dimensions | Inspect grader output |
| AC-2.2 | Output grader uses the identical rubric as the input grader | Code audit |
| AC-2.3 | Quality delta (output − input) is computed and surfaced to the human reviewer | Inspect review interface |
| AC-2.4 | Section-level grades are produced alongside the overall grade | Inspect grader output |

---

### 8.3 Editorial Context Analysis

The Editorial Context Analyzer runs in parallel with the Article Grader on intake. Where the Article Grader evaluates *what the article says*, the Editorial Context Analyzer evaluates *the human environment around the article* — producing an editorial risk profile that is just as important as the content grade for deciding how and whether to proceed.

#### Edit History Analysis

**Requirements:**
- Fetch the full edit history for the article via the MediaWiki API
- Compute **activity level**: total edits in the last 12 months, average edits per month, time since last substantive edit (excluding bot edits and minor formatting changes)
- Compute **revert rate**: what percentage of edits were reverted in the last 12 months; flag if > 15%
- Detect **flip-flop patterns**: identify specific sections or sentences that have been changed back and forth between two or more states more than twice in the last 6 months; flag each instance with the content in dispute and the number of reversals
- Compute **editor concentration**: what percentage of substantive edits in the last 12 months were made by the top 1, 3, and 5 editors; flag as HIGH concentration if the top editor accounts for > 40% of edits
- Identify **dominant editors**: for each highly concentrated editor, note their username, edit count, and any patterns in what they add, remove, or revert

#### Talk Page Analysis

**Requirements:**
- Fetch the current talk page and all archived talk pages for the article
- Identify and summarize **active disputes**: open threads discussing content disagreements, sourcing questions, or neutrality concerns; extract the core issue, the editors involved, and current status (resolved / unresolved / stale)
- Identify and summarize **resolved disputes**: archived threads that reached a documented consensus; extract the consensus position, as it represents the effective editorial policy for that content area
- Extract **editor-imposed norms**: explicit statements in talk page threads where editors have established standards that go beyond Wikipedia policy (e.g., "we don't use X type of source for this article," "this article follows Y convention per prior consensus," "this claim requires a primary source per discussion in [archive link]")
- Extract **WikiProject affiliations**: which WikiProjects claim this article, what quality assessment they have assigned, and any project-specific guidelines that apply
- Identify **protection history**: has the article been semi-protected or fully protected? When, and why?
- Flag **active warnings**: neutrality dispute tags, COI notices, reliable source noticeboards threads, or other structured flags currently on the talk page

#### Editorial Risk Profile

The Analyzer assembles all findings into a structured editorial risk profile with an overall risk tier:

| Risk Tier | Criteria | Planner Response |
|-----------|----------|-----------------|
| **LOW** | Low revert rate, no flip-flops, no active disputes, diverse editor base | Proceed normally |
| **MODERATE** | Elevated revert rate OR one active dispute OR moderate editor concentration | Proceed with caution flags; surface warnings to human reviewer |
| **HIGH** | Active flip-flops OR dominant single editor OR multiple active disputes | Restrict edit scope; require operator sign-off on improvement plan before any drafting |
| **CRITICAL** | Active protection, active edit war, or talk page mediation in progress | Recommend skipping; surface to operator with full context for manual judgment |

The editorial risk profile feeds directly into the Planner in two ways:

1. **Scope restriction** — flip-flopped sections are flagged as `DO NOT EDIT` unless the operator explicitly overrides; the Planner respects these flags when generating the DAG
2. **Draft writer context** — for articles with a dominant editor or editor-imposed norms, those norms are passed as explicit constraints to section draft writers ("per talk page consensus, this article does not use [source type] for [claim type]")

The talk page's resolved disputes and editor-imposed norms are also passed to the **Contradiction Analyzer** as pre-existing community context — if the community has already debated a competing view and reached a documented consensus, the Contradiction Analyzer uses that context when classifying disputes as significant or fringe.

**Acceptance Criteria:**

| ID | Criterion | How We Verify |
|----|-----------|---------------|
| AC-3.1 | Edit history analysis computes activity level, revert rate, flip-flop patterns, and editor concentration | Inspect editorial risk profile output |
| AC-3.2 | Flip-flopped sections are flagged and passed to the Planner as `DO NOT EDIT` by default | Trace DAG — flagged sections must not appear as edit targets without operator override |
| AC-3.3 | Talk page analysis identifies active disputes, resolved disputes, editor-imposed norms, and WikiProject affiliations | Inspect risk profile output |
| AC-3.4 | Editor-imposed norms extracted from talk pages are passed as constraints to section draft writers | Code audit and trace DAG |
| AC-3.5 | Risk tier is computed and shown prominently in the human review interface before the improvement plan | UI inspection |
| AC-3.6 | CRITICAL risk tier triggers a recommendation to skip, surfaced to the operator before any DAG execution | Test with a protected article |
| AC-3.7 | Editorial Context Analyzer runs in parallel with the Article Grader, not sequentially | Inspect execution logs |
| AC-3.8 | Talk page dispute summaries are passed to the Contradiction Analyzer as pre-existing community context | Trace DAG execution |

---

### 8.4 Planning & DAG Generation

**Requirements:**
- Analyze section-level grades to identify which sections need work and why
- Assign one or more edit modes to each section requiring editing
- Generate a machine-readable DAG of work units with dependencies, priorities, and failure behaviors
- Produce a human-readable improvement plan summarizing what WikiWriter intends to do and why, section by section
- The improvement plan is shown to the human reviewer before execution and can be modified or cancelled

**Acceptance Criteria:**

| ID | Criterion | How We Verify |
|----|-----------|---------------|
| AC-4.1 | Planner produces a valid, executable DAG for every article | Parse and validate DAG structure |
| AC-4.2 | Every DAG node specifies worker type, inputs, dependencies, and failure behavior | Inspect DAG schema |
| AC-4.3 | Human-readable improvement plan is produced alongside the DAG | Inspect planner output |
| AC-4.4 | Human reviewer can view and approve the plan before execution begins | UI inspection |
| AC-4.5 | Operator can cancel or modify the plan before execution | UI test |
| AC-4.6 | Planner uses both the content grade and the editorial risk profile when assigning edit modes | Inspect planner output for risk-flagged articles |

---

### 8.5 Claim Extraction

**Requirements:**
- Parse the article into individual factual claims at the sentence level
- For each claim, determine attribution status: **cited** (adequate citation), **undercited** (citation exists but weak, dead, or non-supporting), or **uncited** (bare assertion with no citation)
- **Consensus claims:** Some factual claims are conventionally left uncited on Wikipedia because they represent broad consensus knowledge (e.g., basic mathematical facts, well-established historical dates, foundational scientific principles). The claim extractor uses the model's own knowledge to assess whether an uncited claim falls into this category. If it does, tag it as **consensus-uncited** and exclude it from source discovery. If it does not — i.e., it is a specific factual assertion that a reasonable reader might dispute — tag it as **uncited** and queue it for source discovery
- Produce a structured claim map with attribution status, associated citation if present, and confidence of the assessment
- Pass uncited and undercited claims (but not consensus-uncited claims) as inputs to source audit and discovery workers

**Acceptance Criteria:**

| ID | Criterion | How We Verify |
|----|-----------|---------------|
| AC-5.1 | Claim extractor produces a structured claim map for every article | Inspect claim map output |
| AC-5.2 | Every claim is tagged with one of: cited / undercited / uncited / consensus-uncited | Inspect claim map output |
| AC-5.3 | Consensus-uncited claims are excluded from source discovery | Trace DAG execution |
| AC-5.4 | Uncited and undercited claims (non-consensus) are passed as inputs to source workers | Trace DAG execution |
| AC-5.5 | Claim map is presented in the human review interface | UI inspection |

---

### 8.6 Similar Article Research

**Requirements:**
- Identify Wikipedia articles on closely related topics
- Extract relevant sourcing, framing, and content from related articles
- Flag contradictions between the target article and related articles
- Pass related article content to source discovery and synthesis workers as context

**Acceptance Criteria:**

| ID | Criterion | How We Verify |
|----|-----------|---------------|
| AC-6.1 | Similar article finder surfaces ≥ 3 related articles for non-stub inputs | Inspect finder output |
| AC-6.2 | Contradictions between target and related articles are flagged | Inspect contradiction flag output |
| AC-6.3 | Related article content is passed as context to synthesis workers | Trace DAG execution |

---

### 8.7 Source Audit

The source audit examines every existing citation in the article. This is the most critical verification step in the pipeline.

**Requirements:**
- For each citation, attempt to fetch the source URL
- If the URL is dead, query the Internet Archive Wayback Machine for the most recent archived version
- If a Wayback copy is found, use it and note the archive date in the source report
- Read the source content and verify: does it actually support the specific claim it is cited for?
- Grade each source on all dimensions of the source grading rubric (below)
- Produce a source audit report: grade, status (live / archived / dead), and claim support assessment for each citation
- Flag citations that are dead and unarchived, or that do not support their claim, as priority replacement targets
- Source audit workers run in parallel, one per citation

**Source Grading Rubric:**

| Dimension | Description | Score |
|-----------|-------------|-------|
| **Reliability** | Determined primarily by domain classification (see below) | 0–10 |
| **Claim support** | Does the source directly support the specific claim it is cited for? | 0–10 |
| **Age** | How current is the source? Penalize outdated sources for time-sensitive claims | 0–10 |
| **Accessibility** | Is the source publicly accessible, or behind a paywall / dead? | 0–10 |
| **Domain authority** | Qualitative signal based on domain classification tier (see below) | 0–10 |

**Domain Classification System:**

Rather than attempting to compute PageRank or TrustRank (not feasible to implement), WikiWriter classifies source domains into tiers. The domain classifier runs as a lightweight lookup against a maintained classification table, supplemented by an LLM call for unknown domains.

| Tier | Domain Types | Examples | Reliability Score |
|------|-------------|----------|-------------------|
| **T1 — Academic** | Peer-reviewed journals, preprint servers, university repositories | nature.com, pubmed.ncbi.nlm.nih.gov, arxiv.org, jstor.org | 9–10 |
| **T2 — Institutional** | Government bodies, intergovernmental organizations, established scientific institutions | cdc.gov, who.int, nasa.gov, un.org | 8–9 |
| **T3 — Established News** | Major news organizations with documented editorial standards | reuters.com, apnews.com, bbc.co.uk, nytimes.com | 6–8 |
| **T4 — Reference** | Established encyclopedias, dictionaries, almanacs (excluding Wikipedia itself) | britannica.com, merriam-webster.com | 6–7 |
| **T5 — Specialist** | Trade publications, professional bodies, subject-specific outlets with editorial oversight | bmj.com, techcrunch.com, ietf.org | 5–7 |
| **T6 — Other News** | Regional, local, or less-established news outlets | varies | 3–6 |
| **T7 — Other** | Blogs, forums, social media, personal websites, self-published content | varies | 1–4 |
| **T8 — Unknown** | Domain not in classification table and LLM cannot confidently classify | — | flagged for human review |

The classification table is maintained as part of the WikiWriter codebase and updated periodically. Unknown domains are classified by an LLM call that assesses the domain based on its content, stated editorial standards, and ownership — and the classification is logged for review and potential addition to the table.

**Acceptance Criteria:**

| ID | Criterion | How We Verify |
|----|-----------|---------------|
| AC-7.1 | Every existing citation in the article is audited | Compare audit report count to article citation count |
| AC-7.2 | Dead URLs trigger an automatic Wayback Machine lookup | Test with known-dead URLs |
| AC-7.3 | Every citation receives a structured grade on all 5 dimensions | Inspect source audit report |
| AC-7.4 | Citations that do not support their claim are flagged as priority replacements | Inspect audit report flags |
| AC-7.5 | Source audit workers run in parallel | Inspect execution logs |

---

### 8.8 Source Discovery

**Requirements:**
- For each uncited claim and each priority replacement target, launch a source discovery worker
- Each worker performs a targeted web search for sources supporting the specific claim
- Evaluate and grade candidate sources using the same source grading rubric
- Rank candidates by overall grade; recommend the top 1–3 per gap
- Prefer primary sources over secondary sources
- Discovery workers run concurrently with source audit workers
- Sources that cannot be fetched and read are not recommended

**Acceptance Criteria:**

| ID | Criterion | How We Verify |
|----|-----------|---------------|
| AC-8.1 | Source discovery is launched for every uncited claim and priority replacement | Trace DAG execution |
| AC-8.2 | Every candidate source is graded on all 5 rubric dimensions | Inspect discovery output |
| AC-8.3 | Discovery workers run concurrently with source audit workers | Inspect execution logs |
| AC-8.4 | Unverifiable sources are never recommended | Test with unreachable URLs |

---

### 8.9 Contradiction Analysis

**Requirements:**
- During source discovery, flag candidate sources that dispute rather than corroborate an article claim
- For each disputed claim, identify the authors and institutions behind the contradicting source and assess their credentials before classifying the dispute
- **Expert credential assessment:** For each author or institution, look up: institutional affiliation, publication record in the relevant field, citation count or h-index where available, and recognition by relevant professional bodies. A dispute is only classified as "significant" if it is advanced by people with genuine domain expertise — not adjacent fields, not public commentators, not institutions with a documented conflict of interest in the topic
- Classify the dispute as **significant** (NPOV requires representation) or **fringe** (exclude), logging for each: the competing claim, the source, the authors/institutions, their credential assessment, and the reasoning
- If significant: recommend integrating a balanced representation into the article
- If fringe: note in the source report and exclude from recommendations
- Cross-reference the talk page dispute summary from the Editorial Context Analyzer — if the community has already debated and resolved this dispute, use that consensus as additional context for the classification

**Acceptance Criteria:**

| ID | Criterion | How We Verify |
|----|-----------|---------------|
| AC-9.1 | Contradicting sources are flagged during source discovery | Inspect discovery output |
| AC-9.2 | Every contradiction includes a logged credential assessment of the authors/institutions behind it | Inspect contradiction analysis output |
| AC-9.3 | Every contradiction has a logged significant/fringe determination with full reasoning | Inspect contradiction analysis output |
| AC-9.4 | Significant disputes are passed to the synthesis planner as content to integrate | Trace DAG execution |
| AC-9.5 | Contradiction report — including credential assessments — is presented in the human review interface | UI inspection |

---

### 8.10 Section Draft Writing

**Requirements:**
- Draft writers receive: original section text, edit mode, source report for that section, improvement plan rationale, and relevant content from similar articles
- Each section draft writer operates independently with no awareness of other section writers
- All factual claims must be grounded in provided sources — no recall from training data for factual assertions
- Generate content in encyclopedic, neutral tone consistent with Wikipedia's Manual of Style
- Never introduce value judgments, superlatives, or promotional language
- Never synthesize conclusions not explicitly stated in a cited source
- Independent sections are drafted in parallel

**Acceptance Criteria:**

| ID | Criterion | How We Verify |
|----|-----------|---------------|
| AC-10.1 | Every factual claim in a section draft is grounded in a provided source | Manual audit of 50 consecutive drafts |
| AC-10.2 | Parallel section writers have isolated contexts with no shared state | Code audit |
| AC-10.3 | Draft outputs include inline citations in Wikipedia format | Inspect draft output |
| AC-10.4 | Editor-imposed norms from the talk page analysis are included in section draft writer context | Code audit and inspect worker inputs |

---

### 8.11 Synthesis Writing

**Requirements:**
- Integrate section edits into a coherent whole
- Improve overall flow and readability without changing sourced meaning
- Sharpen the lead paragraph to accurately reflect the updated article content
- Remove redundancy introduced by independent section edits
- Improve concision — every sentence must earn its place
- Check internal consistency: no contradictions between sections
- Must not introduce new factual claims not present in section drafts

**Acceptance Criteria:**

| ID | Criterion | How We Verify |
|----|-----------|---------------|
| AC-11.1 | Synthesis writer operates on the fully assembled article, not individual sections | Code audit |
| AC-11.2 | Lead paragraph is revised to reflect substantive changes in the body | Inspect synthesis output |
| AC-11.3 | Synthesis writer introduces no new factual claims | Manual audit |

---

## 9. Internal Critique & Quality Review

### 9.1 Overview

Every assembled draft undergoes a structured internal critique before any human sees it. The critique is performed by a **single critic worker** using a **different model family** than the draft writers — deliberately chosen to reduce shared blind spots. If draft writers use model family A, the critic uses model family B. This ensures the critic is not subject to the same systematic tendencies, phrasings, or failure modes as the writer.

In v1, there is one critic that evaluates all dimensions in a single pass. In future phases this expands into a **peer review panel** — multiple parallel critic workers each specializing in one dimension (see §9.5).

The critic is prompted to act as a skeptical, experienced Wikipedia editor seeing the draft for the first time. It has no knowledge of the drafting process or prior revision cycles.

### 9.2 Critique Dimensions

The critic evaluates all of the following dimensions in a single structured response. Each dimension must receive an explicit assessment — the critic cannot skip or bundle dimensions.

| Dimension | What the Critic Checks |
|-----------|------------------------|
| **Citation fidelity** | Does each cited source actually say what the draft claims? Is any claim overstated, understated, or subtly distorted relative to the source? |
| **NPOV** | Does any word, phrase, or framing imply a value judgment? Would a neutral observer read any sentence as promotional, disparaging, or advocacy? |
| **Original research** | Does the draft synthesize, interpolate, or draw any conclusion not explicitly stated in a cited source? |
| **Encyclopedic tone** | Does the prose read like Wikipedia, or does it carry hallmarks of AI-generated text, journalistic writing, or marketing copy? |
| **Necessity & concision** | Does each sentence add meaningful value? Is anything redundant, tangential, or padding? |
| **Internal consistency** | Does the edit integrate naturally with the surrounding article? Does it contradict anything already in the article? |
| **Source quality** | Are the chosen sources the best available? Are any sources low-quality, outdated, or otherwise inappropriate? |

### 9.3 Critique Outcomes

The orchestrator merges critique worker outputs and produces one of three outcomes:

- **Pass** — all dimensions clear. Proceeds to output grading.
- **Revise** — specific, addressable issues identified. Critique passed back to relevant draft writers. Maximum 2 revision cycles. A third failure escalates to Discard.
- **Discard** — fundamental problems that revision cannot fix. Logged and dropped.

### 9.4 Critique Visibility

The full critique — every issue raised by every dimension worker, every revision cycle, and the final outcome — is stored in the audit log and presented in the human review interface.

### 9.5 Acceptance Criteria

| ID | Criterion | How We Verify |
|----|-----------|---------------|
| AC-12.1 | Every draft passes through the critique stage before human review | Architecture audit |
| AC-12.2 | Critic uses a different model family than the draft writers | Configuration audit |
| AC-12.3 | Critic produces a structured response covering all 7 dimensions | Inspect critique output format |
| AC-12.4 | Edits failing two revision cycles are discarded, not passed through | Test with deliberately flawed draft |
| AC-12.5 | Full critique transcript is visible to the human reviewer | UI inspection |
| AC-12.6 | Critic context contains no knowledge of prior revision cycles | Code audit |

### 9.6 Future State — Peer Review Panel

In a later phase, the single critic expands into a panel of parallel specialist critics — one per dimension — each using an isolated context. This improves depth of critique per dimension and allows different model families to be used for different dimensions. The orchestrator merges the panel's outputs and resolves any conflicting assessments before producing the Pass / Revise / Discard outcome. This is explicitly out of scope for v1.

---

## 10. Safety & Policy Requirements

### 10.1 Wikipedia Policy Compliance

**Requirements:**
- Run automated compliance checks on every draft that passes the critique stage
- Check against: NPOV, Verifiability, No Original Research, BLP policy, Manual of Style
- Block any non-compliant draft from reaching human review
- Log specific checks run and results for every edit

### 10.2 Hard Exclusion List

Permanently excluded from WikiWriter's scope, regardless of operator configuration:

- **Biographies of Living Persons (BLPs)** — any article about a living individual
- **Active political figures and elections**
- **Active legal cases and litigation**
- **Medical and health claims** — any content making health, treatment, or diagnostic claims
- **Contested historical events** — any topic tagged with a neutrality or accuracy dispute
- **Recently created articles** (< 12 months old)
- **Any article currently under active editing dispute**

**Acceptance Criteria:**

| ID | Criterion | How We Verify |
|----|-----------|---------------|
| AC-13.1 | Exclusion list enforced at article intake, before any processing | Test each exclusion category |
| AC-13.2 | Exclusion list cannot be overridden by operator configuration | Access control audit |

### 10.3 Agent Behavioral Constraints

- WikiWriter has no capability to submit to Wikipedia directly
- WikiWriter has no capability to post or communicate outside the internal review interface
- WikiWriter has no capability to communicate with other AI agents or automated systems
- WikiWriter cannot modify its own configuration, prompts, or code
- All network calls restricted to: Wikipedia read API, source URLs, Wayback Machine API, web search, internal services

**Acceptance Criteria:**

| ID | Criterion | How We Verify |
|----|-----------|---------------|
| AC-14.1 | No MediaWiki write API calls exist anywhere in the codebase | Code audit |
| AC-14.2 | No network calls outside the approved domain list | Network traffic audit |
| AC-14.3 | No mechanism for the agent to modify its own prompts or configuration | Code audit |

---

## 11. Human Review & Manual Submission

### 11.1 Submission Model (v1)

WikiWriter does not submit edits to Wikipedia. The human operator is the editor of record for every Wikipedia edit.

Submission workflow:
1. WikiWriter produces a fully critiqued, graded edit proposal
2. Operator reviews the proposal in the WikiWriter interface
3. If approved, operator copies the edit and manually submits to Wikipedia under their own account
4. Edit summary includes the AI-assistance disclosure tag
5. Operator logs the submission in WikiWriter, linking the on-wiki edit to the audit record

### 11.2 Human Review Interface

The interface must provide:

- **Editorial risk profile** — risk tier (LOW / MODERATE / HIGH / CRITICAL), highlighted prominently; activity level, revert rate, flip-flop map, editor concentration, dominant editor summary
- **Talk page summary** — active disputes, resolved disputes and their consensus positions, editor-imposed norms, WikiProject affiliations, protection history
- **Article grade panel** — input grade and output grade across all dimensions, with delta highlighted
- **Improvement plan** — what the agent decided to change and why, section by section; flip-flopped sections shown as excluded with the option to override
- **DAG execution summary** — which workers ran, what they found, which nodes failed or were discarded
- **Claim map** — all claims with attribution status
- **Source audit report** — every existing citation with grade, status, and claim support assessment
- **New sources panel** — recommended sources with grades and the specific claims they support
- **Contradiction report** — disputes found, with significant/fringe determination and reasoning; cross-referenced against talk page consensus where applicable
- **Diff view** — before/after article text with changes highlighted
- **Critique transcript** — full critique history including all revision cycles and dimension-level feedback
- **Proposed edit summary** — pre-formatted with disclosure tag, ready for copy-paste
- **Actions** — Approve, Reject (requires reason), Request Revision

### 11.3 Acceptance Criteria

| ID | Criterion | How We Verify |
|----|-----------|---------------|
| AC-15.1 | No code path exists for WikiWriter to submit directly to Wikipedia | Code audit |
| AC-15.2 | All review interface panels are present and populated | UI inspection |
| AC-15.3 | Editorial risk profile and risk tier are shown before the improvement plan, not after | UI inspection |
| AC-15.4 | Approved edit summary includes the disclosure tag | Inspect pre-formatted summary |
| AC-15.5 | Rejected edits are logged with reason and cannot re-enter the pipeline without operator action | Test rejection flow |

---

## 12. Audit & Transparency Requirements

### 12.1 Full Audit Trail

Every article entering WikiWriter is logged with:

- Input article URL/text and intake timestamp
- Article grade (all dimensions, all sections)
- Editorial risk profile (full output: edit history metrics, flip-flop map, editor concentration, talk page summary, editor-imposed norms, risk tier)
- Full improvement plan and DAG structure
- Claim map with all attribution status tags
- Source audit report (all citations, all grades)
- Source discovery results (all candidates evaluated)
- Contradiction analysis results with determinations and reasoning
- Section draft history (all versions, all revision cycles)
- Full critique transcript (all cycles, all dimensions)
- Output grade and quality delta
- Human reviewer decision and stated reasoning
- Whether, when, and by whom the edit was submitted to Wikipedia

Logs are immutable and retained for a minimum of 3 years.

### 12.2 Disclosure Standards

- Every edit submitted to Wikipedia includes: `[AI-assisted via WikiWriter | operator: @username]`
- WikiWriter must never generate content that obscures or denies its AI-assisted nature
- The operator's Wikipedia user page must disclose their use of WikiWriter

### 12.3 Quality Reporting Dashboard

Internal in v1; intended to be public when seeking BAG approval:

- Edits entering pipeline / passing critique / approved by operator / submitted
- Drop-off rate at each pipeline stage
- Critique outcomes: pass / revise / discard rates, most common failure dimensions
- Source audit statistics: dead link rate, claim support failure rate, average source grade
- Input vs. output grade distribution and average quality delta
- Operator approval and rejection rates

---

## 13. Quality & Evaluation Requirements

### 13.1 Automated Quality Gates

After critique, before human review:

| Dimension | Threshold |
|-----------|-----------|
| Citation validity | 100% of citations verified and claim-supporting |
| NPOV heuristic score | ≥ 0.85 |
| Original research violations | 0 |
| LLM hallmark phrases detected | 0 |
| Edit scope within configured domain | Must pass |
| Exclusion list clear | Must pass |

### 13.2 Pre-Launch Quality Benchmark

Before any edits are submitted to Wikipedia:

- Generate 50 edit proposals across the configured topic domain
- Submit to blind review by ≥ 2 experienced Wikipedia editors not affiliated with the project
- Target: ≥ 80% rated "would accept without modification"
- Any systematic failure pattern must be resolved before launch

### 13.3 Ongoing Quality Metrics

- **Primary:** Operator approval rate — target ≥ 80% of critique-passing edits approved without a revision request
- **Secondary:** Critique first-pass rate, average revision cycles per approved edit, discard rate by failure dimension, average quality delta
- A 30-day rolling operator approval rate below 60% triggers an automatic pipeline pause

---

## 14. Implementation Phases

### Phase 1 — Foundation (Months 1–3)

**Goal:** A working linear pipeline that produces verifiable, high-quality edit proposals for simple cases. No parallelism yet. Proves the core loop end-to-end.

**In Scope:**
- Article intake (URL and raw text)
- Article grader — full 7-dimension rubric, section-level grades
- Editorial Context Analyzer — edit history analysis (activity level, revert rate, flip-flop detection, editor concentration) and talk page analysis (active disputes, resolved disputes, editor-imposed norms, WikiProject affiliations, protection history); produces editorial risk profile and risk tier
- Basic planner — consumes content grade and editorial risk profile; identifies sections to edit, assigns edit mode; respects flip-flop exclusions; emits a sequential task list (not yet a full DAG)
- Source audit — sequential, one citation at a time; Wayback Machine fallback included
- Source discovery — sequential, for uncited claims only
- Section draft writers: Citation Repair and Claim Attribution modes only; editor-imposed norms passed as constraints
- Synthesis writer — basic integration and consistency pass
- Critique pipeline — sequential (all 7 dimensions in a single call for Phase 1)
- Output grader
- Human review interface MVP: editorial risk profile panel, talk page summary, diff view, source report, critique summary, article grade delta, approve / reject / request revision

**Exit Criteria:**
- End-to-end pipeline completes on a stub article without manual intervention
- Editorial Context Analyzer correctly identifies flip-flopped sections and dominant editors (validated manually on 5 test articles)
- Source audit correctly identifies dead and claim-unsupporting citations
- 0 fabricated citations in 20 consecutive edit proposals
- Average output grade exceeds input grade on the same rubric

**Explicitly Deferred:** Parallelism, claim extractor, similar article research, contradiction analysis, DAG engine, Section Expansion / Rewrite / Synthesis Pass / Contradiction Integration modes

---

### Phase 2 — Claim Intelligence & Source Depth (Months 4–6)

**Goal:** Add claim-level intelligence. WikiWriter now understands what is and is not attributed, and actively hunts for sources to fill every identified gap.

**In Scope:**
- Claim extractor — sentence-level claim parsing, cited / undercited / uncited tagging
- Upgraded source discovery — covers all uncited and undercited claims, not just obvious gaps
- Full source grading rubric — all 5 dimensions including age, domain classification (T1–T8 tier system), and accessibility
- Section Expansion and Section Rewrite edit modes
- Upgraded planner — uses claim map to inform edit mode selection
- Upgraded review interface — claim map panel, source grading breakdown per citation

**Exit Criteria:**
- Claim extractor correctly tags attribution status on ≥ 90% of claims (validated against human annotation of 200 claims)
- Source discovery finds a suitable replacement for ≥ 70% of flagged dead/unsupporting citations
- Operator approval rate ≥ 80% sustained over 4 consecutive weeks

**Explicitly Deferred:** Parallelism, similar article research, contradiction analysis, DAG engine

---

### Phase 3 — Parallelism & DAG Engine (Months 7–9)

**Goal:** Introduce the DAG execution model and parallelize the pipeline's most expensive stages. Dramatically reduce latency for complex articles and improve critique quality through dimension specialization.

**In Scope:**
- DAG execution engine — orchestrator spawns and manages parallel workers
- Parallel source audit workers — one per citation, concurrent execution
- Parallel source discovery workers — concurrent with source audit
- Parallel critique workers — one per dimension, each with isolated context
- Parallel section draft writers — independent sections drafted simultaneously
- Worker failure handling — timeout, malformed output, single retry, failure logging
- DAG execution log visible in the review interface

**Exit Criteria:**
- End-to-end runtime for a 20-citation article reduces by ≥ 50% vs. Phase 2
- DAG execution log is accurate and human-readable
- Worker failure rate < 5% in normal operation
- No regression in output quality metrics vs. Phase 2

**Explicitly Deferred:** Similar article research, contradiction analysis, Synthesis Pass and Contradiction Integration modes

---

### Phase 4 — Lateral Research & Contradiction Analysis (Months 10–12)

**Goal:** WikiWriter now looks beyond the article itself — finding related articles and sources that corroborate or challenge the content, and synthesizing them into a richer, more balanced edit.

**In Scope:**
- Similar article finder — identifies related Wikipedia articles; extracts relevant sourcing and content
- Contradiction analyzers — evaluates disputed sources; significant/fringe determination with logged reasoning
- Contradiction Integration edit mode
- Synthesis Pass edit mode — global article improvements: flow, concision, lead quality
- Full synthesis planner — uses all research inputs to plan holistic improvements
- Upgraded review interface — similar articles panel, contradiction report, synthesis rationale

**Exit Criteria:**
- Similar article finder surfaces ≥ 3 relevant articles for 90% of non-stub inputs
- Contradiction analyzer correctly classifies significant vs. fringe disputes on ≥ 85% of cases (validated against human judgment on 50 annotated cases)
- Synthesis Pass measurably improves lead quality (validated by human review panel)
- Average quality delta (output grade − input grade) ≥ +1.5 points across a 30-day window

---

### Phase 5 — Proof of Concept Completion (Months 13–18)

**Goal:** Demonstrate the full pipeline end-to-end at sufficient quality and scale to constitute a credible proof of concept. No external policy engagement at this stage.

**In Scope:**
- Pre-launch quality benchmark — 50 edit proposals reviewed blind by ≥ 2 experienced Wikipedia editors not affiliated with the project; ≥ 80% "would accept without modification" target
- Supervised pilot — 10 edit proposals/week, all manually submitted by human operators with AI-assistance disclosure
- Internal quality dashboard — pipeline statistics, quality deltas, source audit metrics, critique outcomes
- Documentation of the full system for potential future external review

**Exit Criteria:**
- ≥ 200 edit proposals generated with full audit trail
- ≥ 80% operator approval rate sustained across the pilot period
- Average quality delta ≥ +1.5 points across the pilot period
- Full pipeline documentation complete

**Explicitly Deferred:** Wikimedia Foundation outreach, BAG engagement, public dashboard, community policy proposal — these are post-POC decisions

---

### Phase 6 — Expanded Scope (Post-Policy Approval)

*Contingent on BAG approval of a conditional AI-assisted editing policy.*

Potential scope for discussion:
- Broader topic domains
- Additional Wikipedia language editions
- New article creation (with a significantly higher quality bar and review requirements)
- Automated submission capability with full audit trail and community-agreed safeguards

---

## 15. Wikipedia Community Engagement Strategy

Community engagement is **out of scope for the POC**. WikiWriter is being built first as an internal proof of concept to validate the pipeline, quality bar, and editorial context analysis. External engagement with Wikipedia editors, the Wikimedia Foundation, or the BAG is a post-POC decision, contingent on POC outcomes.

The community engagement strategy below is documented for future reference only.

### Future Phase A — Consultation
- Engage WikiProject AI Cleanup directly before any public launch
- Share findings with senior Wikipedia editors for feedback
- Do not launch publicly without community awareness

### Future Phase B — Transparent Pilot
- Operate as a fully disclosed experiment
- All human-submitted edits disclosed as AI-assisted in edit summaries
- Invite community editors to inspect any edit's full audit trail on request

### Future Phase C — Policy Proposal
- Prepare a formal proposal for the BAG only after a sustained track record
- Goal: a policy that benefits the Wikipedia ecosystem broadly, not a carve-out for WikiWriter

---

## 16. Out of Scope (v1)

- Creating new articles from scratch
- Editing Biographies of Living Persons
- Editing in any language other than English
- Direct, automated submission to Wikipedia
- Posting on Wikipedia talk pages or discussion venues
- Integration with any agent-to-agent platform
- Image, media, or infobox editing
- Deletion nominations

---

## 17. Resolved Decisions & Remaining Open Questions

### Resolved

| # | Question | Decision |
|---|----------|----------|
| Q1 | Should critique workers use a different model family than draft writers? | **Yes.** The critic always uses a different model family from the draft writers to reduce shared blind spots. |
| Q2 | How do we assess source authority without implementing PageRank/TrustRank? | **Domain classification system (T1–T8).** Sources are classified by domain type (academic, institutional, established news, etc.) using a maintained lookup table supplemented by LLM classification for unknown domains. No PageRank/TrustRank implementation. |
| Q3 | How should the claim extractor handle claims true by consensus but conventionally uncited? | **LLM memory.** The claim extractor uses the model's own knowledge to assess whether an uncited claim represents broad consensus (e.g., basic mathematical facts). Consensus claims are tagged `consensus-uncited` and excluded from source discovery. |
| Q4 | If a dominant editor's norms conflict with Wikipedia policy, should WikiWriter follow, flag, or override? | **Flag as risk.** WikiWriter notes the conflict in the editorial risk profile and surfaces it to the human operator. It does not silently follow an extra-policy norm, nor does it override it — that judgment belongs to the human. |
| Q5 | How do we distinguish a significant scholarly dispute from a fringe view? | **Expert credential assessment.** The contradiction analyzer identifies the authors and institutions behind the contradicting source and assesses their domain credentials (affiliation, publication record, citation count, professional recognition). Only disputes advanced by genuine domain experts are classified as significant. |
| Q6 | Should the model version be frozen or updatable? | **Updatable — always use a current frontier model.** Model updates do not require disclosure in individual edit summaries but should be logged in the system audit trail. |
| Q7 | How do we handle a cited source that is updated, retracted, or taken down after submission? | **Active replacement.** The source audit runs against current URLs. If a previously live source is found dead on a re-audit, WikiWriter triggers a source discovery worker to find a current, accurate replacement and flags the edit for operator review. |
| Q8 | Should we approach the Wikimedia Foundation at this stage? | **No.** WikiWriter is a POC. No external engagement with the Wikimedia Foundation or BAG during the POC phase. This is a post-POC decision. |

### Remaining Open Questions

| # | Question | Owner | Target Phase |
|---|----------|-------|-------------|
| Q9 | What is the response plan if a WikiWriter-assisted edit is used as evidence against AI editing in a community vote? | Legal/Comms | Post-POC |
| Q10 | Which specific frontier models should be used for draft writers vs. the critic, and how should this be documented? | Engineering | Phase 1 |
| Q11 | What is the process for updating and maintaining the domain classification table (T1–T8)? Who owns it? | Engineering | Phase 2 |
| Q12 | Should the consensus-uncited classification be shown to the human reviewer, and can they override it to trigger source discovery? | Product | Phase 2 |

---

## Appendix: Why Existing AI Agents Failed

### The Tom Incident (March 2026)

TomWikiAssist autonomously edited Wikipedia articles, was blocked by the community, rewrote its own code to evade a prompt injection kill switch, posted public complaints on an AI social network, coordinated with other agents, and criticized individual editors by name — triggering the emergency ban.

**WikiWriter's design response:** WikiWriter has no write access to Wikipedia, no capability to post outside the internal review interface, no integration with any external platform, and no mechanism to modify its own code or configuration. A human submits every edit, manually, under their own account.

### Systematic LLM Content Failures

By October 2025, roughly 5% of new Wikipedia articles were AI-generated, featuring hallucinated citations, promotional framing, and fabricated content. Wikipedia was tagging over 1,200 articles per month for suspected AI content.

**WikiWriter's design response:** Source verification is a hard gate — no claim proceeds without a fetched, read, and verified source. The claim extractor surfaces every unattributed assertion before any drafting begins. Parallel critique workers catch promotional framing, original research, and tonal problems before any human sees the output.

### The Core Pattern

Every failed AI editing attempt shares one root failure: **optimized for output, not quality.** WikiWriter is optimized for quality. The pipeline is designed to discard more edits than it produces, and that is the correct behavior.

---

*WikiWriter PRD v0.5 — Living specification. All requirements subject to revision based on community feedback and pilot learnings.*
 